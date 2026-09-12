import os
import tempfile
import unittest
from unittest import mock


_TEST_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_TEST_DIR.name, "productization.db"))
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("DASHBOARD_SESSION_SECRET", "test-dashboard-secret")

import app as customer_agent
import dashboard as customer_dashboard


class ProductizationTests(unittest.TestCase):
    def setUp(self):
        self.client = customer_agent.app.test_client()
        customer_agent.ADMIN_API_KEY = "test-admin-key"
        customer_dashboard.ADMIN_API_KEY = "test-admin-key"
        customer_agent.SESSIONS.clear()

        conn = customer_agent.db_connect()
        conn.execute("DELETE FROM order_status_events")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM processed_updates")
        conn.execute("DELETE FROM processed_messages")
        conn.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()

    def admin_headers(self):
        return {"X-Admin-Key": "test-admin-key"}

    def create_order(self, name="عميل", phone="0933000000", currency="$", price=30, status="new"):
        conn = customer_agent.db_connect()
        cursor = conn.execute(
            customer_agent.db_sql(
                """
                INSERT INTO orders(
                    customer_name, customer_phone, product_name, quantity,
                    price, currency, country, city, status,
                    customer_message, created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """
            ),
            (
                name, phone, "الجهاز", 1, price, currency, "سوريا", "دمشق",
                status, "test", "2026-09-12T12:00:00",
            ),
        )
        order_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return order_id

    def test_health_and_readiness_do_not_expose_values(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        private_url = "http://private-host.example/telegram"
        with (
            mock.patch.object(customer_agent, "BOT_TOKEN", "private-token"),
            mock.patch.object(customer_agent, "WEBHOOK_URL", private_url),
            mock.patch.object(customer_agent, "WEBHOOK_SECRET", "secret"),
            mock.patch.object(customer_agent, "ADMIN_API_KEY", "admin"),
            mock.patch.object(customer_agent, "DASHBOARD_SESSION_SECRET", "session"),
        ):
            response = self.client.get("/ready")

        self.assertEqual(response.status_code, 503)
        self.assertIn("WEBHOOK_URL must use HTTPS", response.get_json()["configuration_errors"])
        self.assertNotIn(private_url, response.get_data(as_text=True))
        self.assertNotIn("private-token", response.get_data(as_text=True))

    def test_valid_custom_catalog_and_invalid_schema_fallback(self):
        errors_before = list(customer_agent.CONFIGURATION_ERRORS)
        customer_agent.CONFIGURATION_ERRORS.clear()
        try:
            with mock.patch.dict(
                os.environ,
                {"PRODUCTS_JSON": '{"حاسوب":{"price":99,"currency":"$"}}'},
            ):
                catalog = customer_agent._json_env(
                    "PRODUCTS_JSON", customer_agent.DEFAULT_PRODUCTS, customer_agent._valid_products
                )
            self.assertEqual(catalog["حاسوب"]["price"], 99)

            with mock.patch.dict(os.environ, {"PRODUCTS_JSON": '{"ناقص":{"currency":"$"}}'}):
                catalog = customer_agent._json_env(
                    "PRODUCTS_JSON", customer_agent.DEFAULT_PRODUCTS, customer_agent._valid_products
                )
            self.assertIs(catalog, customer_agent.DEFAULT_PRODUCTS)
            self.assertEqual(customer_agent.CONFIGURATION_ERRORS, ["PRODUCTS_JSON has an invalid schema"])
        finally:
            customer_agent.CONFIGURATION_ERRORS[:] = errors_before

    def test_admin_auth_pagination_and_literal_wildcard_search(self):
        self.create_order(name="أحمد % المميز")
        self.create_order(name="سارة")

        self.assertEqual(self.client.get("/admin/orders").status_code, 401)
        response = self.client.get(
            "/admin/orders?limit=1&offset=0&q=%25", headers=self.admin_headers()
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["pagination"]["total"], 1)
        self.assertEqual(payload["orders"][0]["customer_name"], "أحمد % المميز")

        invalid = self.client.get("/admin/orders?limit=all", headers=self.admin_headers())
        self.assertEqual(invalid.status_code, 400)

    def test_status_update_is_audited_and_revenue_is_split_by_currency(self):
        order_id = self.create_order(currency="$", price=30)
        self.create_order(phone="0933000001", currency="ل.س", price=500000, status="delivered")
        self.create_order(phone="0933000002", currency="$", price=90, status="cancelled")

        changed = self.client.patch(
            f"/admin/orders/{order_id}/status",
            json={"status": "processing"},
            headers=self.admin_headers(),
        )
        self.assertEqual(changed.status_code, 200)

        history = self.client.get(
            f"/admin/orders/{order_id}/history", headers=self.admin_headers()
        ).get_json()["events"]
        self.assertEqual(history[-1]["old_status"], "new")
        self.assertEqual(history[-1]["new_status"], "processing")

        stats = self.client.get("/admin/stats", headers=self.admin_headers()).get_json()
        self.assertEqual(stats["recorded_revenue_by_currency"], {"$": 30.0, "ل.س": 500000.0})

    def test_large_payload_is_rejected_before_bot_call(self):
        with mock.patch.object(customer_agent, "telegram_api") as telegram_api:
            response = self.client.post(
                "/telegram",
                data=b"x" * (customer_agent.MAX_REQUEST_BYTES + 1),
                content_type="application/json",
                headers={"X-Telegram-Bot-Api-Secret-Token": customer_agent.WEBHOOK_SECRET},
            )
        self.assertEqual(response.status_code, 413)
        telegram_api.assert_not_called()

    def test_failed_telegram_delivery_can_be_retried(self):
        update = {"update_id": 9001, "message": {"text": "مرحبا", "chat": {"id": 8}}}
        with (
            mock.patch.object(customer_agent, "WEBHOOK_SECRET", "test-secret"),
            mock.patch.object(customer_agent, "telegram_api", side_effect=RuntimeError("private-token")),
        ):
            response = self.client.post(
                "/telegram", json=update,
                headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(customer_agent.update_was_processed(9001))


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.client = customer_dashboard.dashboard_app.test_client()
        customer_dashboard.ADMIN_API_KEY = "test-admin-key"

    def csrf_token(self):
        with self.client.session_transaction() as browser_session:
            return browser_session["csrf_token"]

    def test_login_requires_csrf_and_sets_security_headers(self):
        self.assertEqual(
            self.client.post("/login", data={"password": "test-admin-key"}).status_code,
            400,
        )
        self.client.get("/login")
        login = self.client.post(
            "/login",
            data={"password": "test-admin-key", "csrf_token": self.csrf_token()},
        )
        self.assertEqual(login.status_code, 302)
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["X-Frame-Options"], "DENY")
        self.assertEqual(page.headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'self'", page.headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
