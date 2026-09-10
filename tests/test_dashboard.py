import os
import tempfile
import unittest


_TEST_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_TEST_DIR.name, "dashboard_test.db"))
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("DASHBOARD_SESSION_SECRET", "test-dashboard-session-secret")

import app as customer_agent
import dashboard as customer_dashboard


class DashboardSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = customer_dashboard.dashboard_app.test_client()
        customer_dashboard.ADMIN_API_KEY = "test-admin-key"
        conn = customer_agent.db_connect()
        conn.execute("DELETE FROM order_status_events")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM orders")
        conn.commit()
        conn.close()

    def csrf_token(self):
        with self.client.session_transaction() as browser_session:
            return browser_session["csrf_token"]

    def login(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        return self.client.post(
            "/login",
            data={"password": "test-admin-key", "csrf_token": self.csrf_token()},
        )

    def create_order(self, name="عميل", phone="+963900000000", city="دمشق"):
        now = customer_agent.utc_now()
        conn = customer_agent.db_connect()
        cursor = conn.execute(
            """
            INSERT INTO orders(
                chat_id, customer_name, customer_phone, product_name, quantity,
                unit_price, total_price, currency, country, city, status,
                customer_message, created_at, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                phone, name, phone, "الجهاز", 1, 30, 30, "$",
                "سوريا", city, "new", "test", now, now,
            ),
        )
        conn.commit()
        order_id = cursor.lastrowid
        conn.close()
        return order_id

    def test_login_requires_csrf_token(self):
        response = self.client.post("/login", data={"password": "test-admin-key"})
        self.assertEqual(response.status_code, 400)

    def test_login_sets_hardened_response_headers(self):
        response = self.login()
        self.assertEqual(response.status_code, 302)
        dashboard_response = self.client.get("/")
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(dashboard_response.headers["Cache-Control"], "no-store")
        self.assertEqual(dashboard_response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(dashboard_response.headers["X-Content-Type-Options"], "nosniff")

    def test_status_change_requires_valid_csrf_token(self):
        order_id = self.create_order()
        self.login()

        rejected = self.client.post(
            f"/orders/{order_id}/status",
            data={"status": "confirmed"},
        )
        self.assertEqual(rejected.status_code, 400)

        self.client.get("/")
        accepted = self.client.post(
            f"/orders/{order_id}/status",
            data={"status": "confirmed", "csrf_token": self.csrf_token()},
        )
        self.assertEqual(accepted.status_code, 302)

        conn = customer_agent.db_connect()
        status = conn.execute(
            "SELECT status FROM orders WHERE id=?", (order_id,)
        ).fetchone()["status"]
        event = conn.execute(
            """
            SELECT old_status, new_status, source
            FROM order_status_events WHERE order_id=?
            """,
            (order_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(status, "confirmed")
        self.assertEqual(tuple(event), ("new", "confirmed", "dashboard"))

    def test_dashboard_search_finds_customer_and_preserves_status_filter(self):
        self.create_order(name="أحمد المميز", phone="0933111111")
        self.create_order(name="سارة", phone="0944222222")
        self.login()

        response = self.client.get("/?q=0933111111&status=new")
        page = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("أحمد المميز", page)
        self.assertNotIn("سارة", page)
        self.assertIn('value="0933111111"', page)
        self.assertIn('name="status" value="new"', page)

    def test_dashboard_search_treats_wildcards_as_text(self):
        self.create_order(name="أحمد")
        self.login()

        response = self.client.get("/?q=%25")

        self.assertEqual(response.status_code, 200)
        self.assertIn("لا توجد طلبات ضمن هذا الفلتر", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
