import os
import tempfile
import unittest
from unittest import mock

import requests


_TEST_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_TEST_DIR.name, "gemini.db"))

import app as customer_agent


class GeminiIntegrationTests(unittest.TestCase):
    def setUp(self):
        customer_agent.SESSIONS.clear()

    @staticmethod
    def gemini_response(answer):
        response = mock.Mock()
        response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": answer}]}}]
        }
        return response

    def test_open_telegram_question_uses_gemini_with_catalog(self):
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(
                customer_agent.requests,
                "post",
                return_value=self.gemini_response("ما عندي معلومة مؤكدة عن الضمان."),
            ) as post,
        ):
            answer = customer_agent.handle_message(
                "gemini-open", "في ضمان؟", source="telegram"
            )

        self.assertEqual(answer, "ما عندي معلومة مؤكدة عن الضمان.")
        self.assertIn("الجهاز", post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        self.assertEqual(
            post.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"],
            "في ضمان؟",
        )

    def test_contact_details_and_order_flow_stay_local(self):
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(customer_agent.requests, "post") as post,
        ):
            self.assertIsNone(customer_agent.gemini_reply("اسمي أحمد ورقمي 0933123456"))
            self.assertIn(
                "شو اسمك",
                customer_agent.handle_message(
                    "gemini-order", "بدي أطلب الجهاز", source="telegram"
                ),
            )
            self.assertIn(
                "رقم الهاتف",
                customer_agent.handle_message(
                    "gemini-order", "أحمد محمد", source="telegram"
                ),
            )
            self.assertIn(
                "30$",
                customer_agent.handle_message(
                    "gemini-price", "كم سعر الجهاز؟", source="telegram"
                ),
            )
            post.assert_not_called()

    def test_gemini_rate_limit_keeps_local_reply(self):
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(
                customer_agent.requests,
                "post",
                side_effect=requests.HTTPError("429"),
            ),
        ):
            answer = customer_agent.handle_message(
                "gemini-limit", "في ضمان؟", source="telegram"
            )

        self.assertIn("جرب اسألني", answer)

    def test_gemini_cannot_claim_an_order_was_registered(self):
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(
                customer_agent.requests,
                "post",
                return_value=self.gemini_response("تم تسجيل طلبك بنجاح"),
            ),
        ):
            answer = customer_agent.handle_message(
                "gemini-claim", "في ضمان؟", source="telegram"
            )

        self.assertIn("جرب اسألني", answer)

    def test_other_channels_do_not_call_gemini(self):
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(customer_agent.requests, "post") as post,
        ):
            answer = customer_agent.handle_message(
                "gemini-other", "في ضمان؟", source="messenger"
            )

        self.assertIn("جرب اسألني", answer)
        post.assert_not_called()
