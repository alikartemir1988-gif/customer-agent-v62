import os
import tempfile
import unittest
from unittest import mock


_TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = os.path.join(_TEST_DIR.name, "customer_agent_test.db")
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ.pop("WEBHOOK_URL", None)

import app as customer_agent


class CustomerAgentTests(unittest.TestCase):
    def setUp(self):
        self.client = customer_agent.app.test_client()
        conn = customer_agent.db_connect()
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM orders")
        conn.commit()
        conn.close()

    def test_health_reports_database_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["database"], "ok")

    def test_admin_api_rejects_missing_key(self):
        response = self.client.get("/admin/stats")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_admin_api_accepts_configured_key(self):
        response = self.client.get(
            "/admin/stats",
            headers={"X-Admin-Key": "test-admin-key"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total_orders"], 0)

    def test_admin_orders_rejects_non_integer_limit(self):
        response = self.client.get(
            "/admin/orders?limit=all",
            headers={"X-Admin-Key": "test-admin-key"},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "limit must be an integer")

    def test_admin_orders_rejects_unknown_status(self):
        response = self.client.get(
            "/admin/orders?status=unknown",
            headers={"X-Admin-Key": "test-admin-key"},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid status")

    def test_telegram_webhook_rejects_wrong_secret(self):
        response = self.client.post(
            "/telegram",
            json={"message": {"text": "مرحبا", "chat": {"id": 1}}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_webhook_info_does_not_expose_bot_token_on_failure(self):
        secret_token = "secret-token-that-must-not-leak"
        secret_api_url = f"https://api.telegram.org/bot{secret_token}"
        failure = RuntimeError(f"request failed for {secret_api_url}/getWebhookInfo")

        with (
            mock.patch.object(customer_agent, "BOT_TOKEN", secret_token),
            mock.patch.object(customer_agent, "API", secret_api_url),
            mock.patch.object(customer_agent.requests, "get", side_effect=failure),
            mock.patch("builtins.print") as print_mock,
        ):
            response = self.client.get("/webhook-info")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], "telegram request failed")
        self.assertNotIn(secret_token, response.get_data(as_text=True))
        logged = " ".join(str(arg) for call in print_mock.call_args_list for arg in call.args)
        self.assertNotIn(secret_token, logged)

    def test_order_flow_persists_one_order_and_blocks_duplicate(self):
        chat_id = 9001

        first = customer_agent.handle_message(chat_id, "بدي اشتري الجهاز")
        self.assertIn("اسم", first)

        second = customer_agent.handle_message(chat_id, "اسمي أحمد علي")
        self.assertIn("رقم الهاتف", second)

        third = customer_agent.handle_message(chat_id, "+963 944 123 456")
        self.assertIn("المدينة", third)

        fourth = customer_agent.handle_message(chat_id, "دمشق")
        self.assertIn("تم تسجيل طلبك", fourth)

        duplicate = customer_agent.handle_message(chat_id, "دمشق")
        self.assertIn("مسجل مسبقاً", duplicate)

        conn = customer_agent.db_connect()
        count = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
        row = conn.execute(
            "SELECT customer_name, product_name, quantity, city, status FROM orders"
        ).fetchone()
        conn.close()

        self.assertEqual(count, 1)
        self.assertEqual(row["customer_name"], "أحمد علي")
        self.assertEqual(row["product_name"], "الجهاز")
        self.assertEqual(row["quantity"], 1)
        self.assertEqual(row["city"], "دمشق")
        self.assertEqual(row["status"], "new")


if __name__ == "__main__":
    unittest.main()
