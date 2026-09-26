import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("MAJD_TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("MAJD_WEBHOOK_URL", "https://example.test")
os.environ.setdefault("MAJD_WEBHOOK_SECRET", "secret")

import majd_sales_bot


class MajdSalesBotTests(unittest.TestCase):
    def setUp(self):
        majd_sales_bot.SCRIPTED_STATES.clear()
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

    def test_health_reports_gemini_free_safe_engine(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["ai_engine"], "gemini-free-safe")

    @patch("majd_sales_bot.requests.post")
    @patch("majd_sales_bot.load_history", return_value=[])
    def test_general_question_uses_gemini_api(self, _history, post):
        api_response = Mock()
        api_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "رد مخصص"}]}}]
        }
        api_response.raise_for_status.return_value = None
        post.return_value = api_response

        reply = majd_sales_bot.ai_reply("1", "buyer", "لدي متجر إلكتروني")

        self.assertEqual(reply, "رد مخصص")
        self.assertIn("generativelanguage.googleapis.com", post.call_args.args[0])
        self.assertNotIn("لدي متجر إلكتروني", post.call_args.kwargs["headers"].values())

    @patch("majd_sales_bot.requests.post")
    def test_contact_details_stay_local(self, post):
        reply = majd_sales_bot.ai_reply("1", "buyer", "رقمي 0994539551")

        post.assert_not_called()
        self.assertIn("تم تسجيل بياناتك", reply)
        self.assertIn("customer-agent-v6-demo.onrender.com", reply)
        self.assertNotIn("لمشاركة الديمو", reply)

    @patch("majd_sales_bot.requests.post")
    def test_price_question_is_local_and_uses_public_price(self, post):
        reply = majd_sales_bot.ai_reply("1", "buyer", "كم سعره")

        post.assert_not_called()
        self.assertIn("6,500", reply)
        self.assertNotIn("5,000", reply)

    @patch("majd_sales_bot.requests.post")
    def test_speed_question_is_local_and_direct(self, post):
        reply = majd_sales_bot.ai_reply("1", "buyer", "ما سرعته")

        post.assert_not_called()
        self.assertIn("ثوان", reply)

    @patch("majd_sales_bot.requests.post")
    def test_demo_request_returns_demo_url_directly(self, post):
        reply = majd_sales_bot.ai_reply("1", "buyer", "اريد رابط الديمو")

        post.assert_not_called()
        self.assertIn("customer-agent-v6-demo.onrender.com", reply)

    @patch("majd_sales_bot.requests.post")
    def test_owner_question_is_local_and_clear(self, post):
        reply = majd_sales_bot.ai_reply("1", "buyer", "من هو المالك")

        post.assert_not_called()
        self.assertIn("المسؤول عن الاتفاق النهائي", reply)

    @patch("majd_sales_bot.requests.post")
    def test_channel_answer_advances_conversation_without_repeating_prompt(self, post):
        majd_sales_bot.ai_reply("flow", "buyer", "تجارة")
        reply = majd_sales_bot.ai_reply("flow", "buyer", "Facebook")

        post.assert_not_called()
        self.assertIn("سجّلت القناة الأساسية: Facebook", reply)
        self.assertIn("عدد رسائل العملاء", reply)
        self.assertNotIn("على أي قناة", reply)

    @patch("majd_sales_bot.requests.post")
    def test_volume_answer_after_channel_advances_to_lead_capture(self, post):
        majd_sales_bot.ai_reply("flow", "buyer", "تجارة")
        majd_sales_bot.ai_reply("flow", "buyer", "Facebook")
        reply = majd_sales_bot.ai_reply("flow", "buyer", "تقريباً 700 رسالة")

        post.assert_not_called()
        self.assertIn("700 رسالة يومياً", reply)
        self.assertIn("أرسل اسمك", reply)
        self.assertNotIn("اختر ما تريد", reply)

    @patch("majd_sales_bot.requests.post")
    def test_task_request_is_understood_as_sales_requirement(self, post):
        reply = majd_sales_bot.ai_reply("1", "buyer", "تنفيذ الرد على العملاء وجدولة المهتمين")

        post.assert_not_called()
        self.assertIn("تنفيذ الرد على العملاء", reply)
        self.assertIn("جدولة الحالات الجدية", reply)

    @patch("majd_sales_bot.requests.post")
    @patch("majd_sales_bot.load_history", return_value=[])
    def test_gemini_failure_falls_back_to_local_sales_flow(self, _history, post):
        post.side_effect = majd_sales_bot.requests.RequestException("quota")

        reply = majd_sales_bot.ai_reply("2", "buyer", "مرحبا")

        self.assertIn("وكيل العملاء V6", reply)


if __name__ == "__main__":
    unittest.main()
