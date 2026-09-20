import os
import unittest
from unittest.mock import Mock, patch

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

    def test_health_reports_openai_safe_engine(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["ai_engine"], "openai-safe")

    @patch("majd_sales_bot.requests.post")
    @patch("majd_sales_bot.load_history", return_value=[])
    def test_general_question_uses_openai_responses_api(self, _history, post):
        api_response = Mock()
        api_response.json.return_value = {"output_text": "رد مخصص"}
        api_response.raise_for_status.return_value = None
        post.return_value = api_response

        reply = majd_sales_bot.ai_reply("1", "buyer", "لدي متجر إلكتروني")

        self.assertEqual(reply, "رد مخصص")
        self.assertEqual(post.call_args.args[0], "https://api.openai.com/v1/responses")
        self.assertNotIn("لدي متجر إلكتروني", post.call_args.kwargs["headers"].values())

    @patch("majd_sales_bot.requests.post")
    def test_contact_details_stay_local(self, post):
        reply = majd_sales_bot.ai_reply("1", "buyer", "رقمي 0994539551")

        post.assert_not_called()
        self.assertIn("تم تسجيل بياناتك", reply)


if __name__ == "__main__":
    unittest.main()
