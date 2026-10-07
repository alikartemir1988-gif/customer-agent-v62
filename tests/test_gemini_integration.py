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
        response = self.gemini_response("ما عندي معلومة مؤكدة عن الضمان.")
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(customer_agent, "GEMINI_MODEL", "gemini-3.5-flash-lite"),
            mock.patch.object(
                customer_agent.requests,
                "post",
                return_value=response,
            ) as post,
        ):
            answer = customer_agent.handle_message(
                "gemini-open", "في ضمان؟", source="telegram"
            )

        self.assertEqual(answer, "ما عندي معلومة مؤكدة عن الضمان.")
        response.raise_for_status.assert_called_once_with()
        self.assertEqual(
            post.call_args.args[0],
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.5-flash-lite:generateContent",
        )
        self.assertEqual(post.call_args.kwargs["timeout"], (3, 12))
        self.assertIn("الجهاز", post.call_args.kwargs["json"]["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(post.call_args.kwargs["headers"]["x-goog-api-key"], "test-key")
        config = post.call_args.kwargs["json"]["generationConfig"]
        self.assertNotIn("temperature", config)
        self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "minimal"})
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

    def test_missing_key_keeps_local_reply_without_remote_request(self):
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", ""),
            mock.patch.object(customer_agent.requests, "post") as post,
        ):
            answer = customer_agent.handle_message(
                "gemini-no-key", "في ضمان؟", source="telegram"
            )

        self.assertIn("جرب اسألني", answer)
        post.assert_not_called()

    def test_invalid_key_or_unavailable_model_keeps_local_reply(self):
        for status, chat_id, model in (
            (401, "gemini-bad-key", "gemini-3.5-flash-lite"),
            (404, "gemini-bad-model", "gemini-unavailable"),
        ):
            with self.subTest(status=status):
                response = self.gemini_response("This must not be used")
                response.status_code = status
                response.raise_for_status.side_effect = requests.HTTPError(
                    f"{status}", response=response
                )
                with (
                    mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
                    mock.patch.object(customer_agent, "GEMINI_MODEL", model),
                    mock.patch.object(customer_agent.requests, "post", return_value=response),
                ):
                    answer = customer_agent.handle_message(
                        chat_id, "في ضمان؟", source="telegram"
                    )

                self.assertIn("جرب اسألني", answer)
                response.raise_for_status.assert_called_once_with()
                response.json.assert_not_called()

    def test_unexpected_success_payload_keeps_local_reply(self):
        response = mock.Mock()
        response.json.return_value = {"candidates": [{"content": None}]}
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(customer_agent.requests, "post", return_value=response),
        ):
            answer = customer_agent.handle_message(
                "gemini-bad-payload", "في ضمان؟", source="telegram"
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

    def test_incomplete_or_blocked_generations_use_local_fallback(self):
        for reason in ("MAX_TOKENS", "SAFETY", "RECITATION", "OTHER"):
            with self.subTest(reason=reason):
                response = self.gemini_response("An unfinished or blocked answer")
                response.json.return_value["candidates"][0]["finishReason"] = reason
                with (
                    mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
                    mock.patch.object(customer_agent.requests, "post", return_value=response),
                ):
                    self.assertIsNone(customer_agent.gemini_reply("في ضمان؟"))

    def test_thought_parts_never_appear_in_customer_answer(self):
        response = self.gemini_response("Public answer")
        response.json.return_value["candidates"][0].update({
            "finishReason": "STOP",
            "content": {"parts": [
                {"text": "Internal thought", "thought": True},
                {"text": "Public answer"},
                {"text": 123},
            ]},
        })
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(customer_agent.requests, "post", return_value=response),
        ):
            self.assertEqual(customer_agent.gemini_reply("في ضمان؟"), "Public answer")

    def test_english_order_claims_are_rejected(self):
        for claim in ("Your order is confirmed.", "The order has been registered.",
                      "I've saved your order.", "We have placed your order."):
            with (
                self.subTest(claim=claim),
                mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
                mock.patch.object(customer_agent.requests, "post", return_value=self.gemini_response(claim)),
            ):
                self.assertIsNone(customer_agent.gemini_reply("Can you tell me a joke?"))

    def test_authentication_and_payment_data_never_leave_the_app(self):
        for text in ("verification code is 123", "my credit card expires soon",
                     "my API key is secret", "my token is confidential"):
            with (
                self.subTest(text=text),
                mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
                mock.patch.object(customer_agent.requests, "post") as post,
            ):
                self.assertIsNone(customer_agent.gemini_reply(text))
                post.assert_not_called()

    def test_open_question_during_arabic_order_uses_gemini_without_changing_details(self):
        customer_agent.handle_message("gemini-active", "بدي أطلب الجهاز", source="telegram")
        before = dict(customer_agent.session("gemini-active"))
        with (
            mock.patch.object(customer_agent, "GEMINI_API_KEY", "test-key"),
            mock.patch.object(customer_agent.requests, "post", return_value=self.gemini_response("لا توجد معلومات عن الغناء.")),
        ):
            answer = customer_agent.handle_message("gemini-active", "هل يغني؟", source="telegram")
        self.assertIn("لا توجد معلومات عن الغناء", answer)
        self.assertIn("شو اسمك", answer)
        self.assertEqual(customer_agent.session("gemini-active"), before)

    def test_synthetic_deployment_qa_does_not_create_sessions_or_orders(self):
        with (
            mock.patch.object(customer_agent, "gemini_reply", return_value="لا توجد معلومات مؤكدة.") as reply,
            mock.patch.object(customer_agent, "save_session") as save_session,
            mock.patch.object(customer_agent, "create_order") as create_order,
            mock.patch("builtins.print"),
        ):
            results = customer_agent.run_gemini_smoke_tests()
        self.assertEqual(len(results), 3)
        self.assertEqual(reply.call_count, 3)
        self.assertTrue(all(customer_agent.safe_for_gemini(call.args[0]) for call in reply.call_args_list))
        self.assertEqual(customer_agent.SESSIONS, {})
        save_session.assert_not_called()
        create_order.assert_not_called()

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
