import os
import unittest
from unittest.mock import patch

os.environ.setdefault("MAJD_TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("MAJD_WEBHOOK_URL", "https://example.test")
os.environ.setdefault("MAJD_WEBHOOK_SECRET", "secret")

import majd_sales_bot


class MajdSalesBotTests(unittest.TestCase):
    def setUp(self):
        self.client = majd_sales_bot.app.test_client()

    def test_rejects_wrong_webhook_secret(self):
        response = self.client.post(
            "/majd/webhook",
            json={"message": {"chat": {"id": 1}, "text": "مرحبا"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    @patch("majd_sales_bot.telegram_send")
    @patch("majd_sales_bot.save_message")
    def test_start_greets_customer(self, _save, send):
        response = self.client.post(
            "/majd/webhook",
            json={"message": {"chat": {"id": 1}, "from": {"username": "buyer"}, "text": "/start"}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("وكيل العملاء V6", send.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
