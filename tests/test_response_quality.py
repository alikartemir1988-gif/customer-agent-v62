"""Revoke dialogue, business-fact and free-provider outage regressions."""

import copy
import json
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

import requests
from requests.structures import CaseInsensitiveDict

os.environ.pop("DATABASE_URL", None)
import app as agent


class ResponseQualityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in (
            ("DB_PATH", os.path.join(directory.name, "quality.db")),
            ("DATABASE_URL", ""),
            ("GEMINI_API_KEY", "quality-test-key"),
            ("GEMINI_MODEL", "gemini-3.5-flash-lite"),
            ("PRODUCTS", copy.deepcopy(agent.DEFAULT_PRODUCTS)),
            ("DELIVERY", copy.deepcopy(agent.DEFAULT_DELIVERY)),
        ):
            manager = patch.object(agent, name, value)
            manager.start()
            self.addCleanup(manager.stop)
        agent.SESSIONS.clear()
        agent.GEMINI_RECOVERY.reset()
        self.addCleanup(agent.SESSIONS.clear)
        self.addCleanup(agent.GEMINI_RECOVERY.reset)
        agent.init_db()
        manager = patch.object(agent.requests, "post", return_value=self.response())
        self.post = manager.start()
        self.addCleanup(manager.stop)

    @staticmethod
    def response(answer="لا توجد مواصفات معتمدة تؤكد ذلك."):
        response = Mock()
        response.json.return_value = {
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": answer}]}}]
        }
        return response

    def ask(self, text, chat="customer"):
        return agent.handle_message(chat, text, source="telegram")

    @staticmethod
    def order_state(state):
        return {k: copy.deepcopy(v) for k, v in state.items() if k != "public_dialogue"}

    def test_followup_receives_previous_public_exchange_and_selected_product(self):
        self.ask("كم سعر الجهاز؟")
        answer = self.ask("ما فهمت، وضحلي أكثر")
        body = self.post.call_args.kwargs["json"]
        self.assertEqual([x["role"] for x in body["contents"]], ["user", "model", "user"])
        self.assertIn("30$", body["contents"][1]["parts"][0]["text"])
        self.assertEqual(body["contents"][-1]["parts"][0]["text"], "ما فهمت، وضحلي أكثر")
        instructions = body["systemInstruction"]["parts"][0]["text"]
        self.assertIn('"selected_product": "الجهاز"', instructions)
        self.assertEqual(answer, "لا توجد مواصفات معتمدة تؤكد ذلك.")

    def test_context_contains_no_customer_order_identity(self):
        agent.session("customer").update({
            "name": "Private Customer Name", "phone": "0933123456",
            "city": "private-street-48", "customer_message": "private-email@example.test",
            "order_id": 987654,
        })
        self.ask("هل هذا مناسب للاستعمال اليومي؟")
        body = json.dumps(self.post.call_args.kwargs["json"], ensure_ascii=False)
        for private in ("Private Customer Name", "0933123456", "private-street-48",
                        "private-email@example.test", "987654"):
            self.assertNotIn(private, body)

    def test_reloaded_history_is_rechecked_for_private_data(self):
        agent.session("customer")["public_dialogue"] = [
            {"question": "my password is super-private", "answer": "OK"},
            {"question": "هل هو متين؟", "answer": "Call 0933123456"},
            {"question": "هل يمكن توضيحه؟", "answer": "شرح عام."},
        ]
        self.ask("اعطيني مثال")
        body = json.dumps(self.post.call_args.kwargs["json"], ensure_ascii=False)
        self.assertNotIn("super-private", body)
        self.assertNotIn("0933123456", body)
        self.assertIn("شرح عام.", body)

    def test_dialogue_is_bounded_persistent_and_separate_for_each_customer(self):
        for number in range(5):
            self.ask(f"هل يمكن شرح النقطة {number}؟")
        self.assertEqual(len(agent.session("customer")["public_dialogue"]), 3)
        saved = copy.deepcopy(agent.session("customer")["public_dialogue"])
        agent.SESSIONS.pop("customer")
        self.assertEqual(agent.session("customer")["public_dialogue"], saved)
        self.ask("هل يمكن شرح ذلك؟", chat="other")
        body = self.post.call_args.kwargs["json"]
        self.assertEqual(len(body["contents"]), 1)
        self.assertEqual(len(agent.session("other")["public_dialogue"]), 1)

    def test_cancelling_clears_the_public_dialogue(self):
        self.ask("هل يمكن شرح الجهاز؟")
        self.assertTrue(agent.session("customer")["public_dialogue"])
        self.ask("ابدأ من جديد")
        self.assertEqual(agent.session("customer")["public_dialogue"], [])

    def test_rephrase_during_order_does_not_become_a_name_or_change_the_order(self):
        self.ask("بدي أطلب الجهاز")
        before = copy.deepcopy(agent.session("customer"))
        answer = self.ask("ما فهمت، وضحلي")
        self.assertEqual(agent.session("customer"), before)
        self.assertIsNone(agent.session("customer")["name"])
        self.assertIn("شو اسمك", answer)
        self.post.assert_not_called()

    def test_multi_part_question_keeps_price_and_answers_the_open_part(self):
        self.post.return_value = self.response("لا توجد بيانات عن ملاءمته للطلاب.")
        answer = self.ask("كم سعر الجهاز؟ وهل يصلح للطلاب؟")
        self.assertIn("30$", answer)
        self.assertIn("ملاءمته للطلاب", answer)
        self.post.assert_called_once()
        self.assertEqual(
            self.post.call_args.kwargs["json"]["contents"][-1]["parts"][0]["text"],
            "هل يصلح للطلاب",
        )

    def test_failed_open_part_keeps_the_verified_price_and_acknowledges_the_gap(self):
        self.post.return_value = self.response("The price is $999.")
        answer = self.ask("كم سعر الجهاز؟ وهل يصلح للطلاب؟")
        self.assertIn("30$", answer)
        self.assertNotIn("999", answer)
        self.assertIn("بقية السؤال", answer)

    def test_approved_answers_ground_explanations_but_drafts_and_private_entries_do_not(self):
        for question, approved, answer in (
            ("كيف يستخدم؟", True, "طريقة الاستخدام المعتمدة: وصله بالكهرباء."),
            ("ميزة سرية؟", False, "draft-marker"),
            ("كيف أتواصل؟", True, "Call 0933123456"),
        ):
            agent.support_store.save_faq({
                "question": question, "answer": answer, "approved": approved,
                "source_title": "دليل المتجر", "aliases": [],
            })
        self.ask("هل يمكن شرح الاستخدام ببساطة؟")
        body = json.dumps(self.post.call_args.kwargs["json"], ensure_ascii=False)
        self.assertIn("طريقة الاستخدام المعتمدة", body)
        self.assertNotIn("draft-marker", body)
        self.assertNotIn("0933123456", body)

    def test_unapproved_prices_and_currencies_are_rejected(self):
        for answer in ("Price $99.", "Price 99 dollars.", "السعر ٩٩ دولار.",
                       "Price USD 99.", "Price $9,999.", "Price €30."):
            with self.subTest(answer=answer):
                self.post.return_value = self.response(answer)
                self.assertIsNone(agent.gemini_reply("هل يناسبني؟"))

    def test_catalog_price_and_deterministic_totals_are_accepted(self):
        for answer, state in (("The price is $30.", None),
                              ("Two units cost 60 dollars.", {"qty": 2})):
            with self.subTest(answer=answer):
                self.post.return_value = self.response(answer)
                self.assertEqual(agent.gemini_reply("هل يمكن توضيح ذلك؟", state), answer)

    def test_selected_product_cannot_borrow_another_products_price(self):
        agent.PRODUCTS["منتج تجريبي"]["price"] = 99
        self.post.return_value = self.response("The price is $99.")
        self.assertIsNone(agent.gemini_reply("هل يمكن توضيحه؟", {"product": "الجهاز"}))

    def test_conflicting_approved_entries_are_excluded_from_ai_context(self):
        for question, answer in (
            ("ما شروط الاستخدام؟", "first-conflicting-marker"),
            ("ما شُروط الاستخدام؟", "second-conflicting-marker"),
        ):
            agent.support_store.save_faq({
                "question": question, "answer": answer,
                "approved": True, "source_title": "دليل المتجر", "aliases": [],
            })
        self.ask("هل يمكن توضيح الاستخدام؟")
        body = json.dumps(self.post.call_args.kwargs["json"], ensure_ascii=False)
        self.assertNotIn("first-conflicting-marker", body)
        self.assertNotIn("second-conflicting-marker", body)

    def test_model_cannot_grant_discounts_permissions_or_absolute_accuracy(self):
        for answer in (
            "أمنحك خصم 50%.", "I give you a discount.",
            "البرنامج يمنع جميع الأخطاء والهلوسة.",
            "The software eliminates all hallucinations.",
            "أضمن إجابات بلا أخطاء.", "We guarantee 100% accuracy.",
            "منحتك صلاحيات كاملة.", "You now have admin access.",
        ):
            with self.subTest(answer=answer):
                self.post.return_value = self.response(answer)
                self.assertIsNone(agent.gemini_reply("هل هذا ممكن؟"))

    def test_qualified_accuracy_and_discount_refusals_remain_usable(self):
        for answer in (
            "البرنامج لا يمنع جميع الأخطاء؛ المعلومات الناقصة تحتاج تأكيداً.",
            "It does not eliminate all hallucinations.",
            "لا أمنحك خصماً؛ يحتاج موافقة المتجر.",
            "I cannot give you a discount.",
        ):
            with self.subTest(answer=answer):
                self.post.return_value = self.response(answer)
                self.assertEqual(agent.gemini_reply("هل هذا ممكن؟"), answer)

    def test_generated_requests_for_credentials_and_contact_data_are_rejected(self):
        for answer in ("Send me your password.", "Give me your password.", "أرسل رمز التحقق لنكمل.",
                       "Enter your card number.", "Call 0933123456.",
                       "Write to owner@example.test."):
            with self.subTest(answer=answer):
                self.post.return_value = self.response(answer)
                self.assertIsNone(agent.gemini_reply("هل يمكن توضيح الخطوات؟"))

    def test_negative_credential_advice_is_allowed(self):
        answer = "Do not share your password."
        self.post.return_value = self.response(answer)
        self.assertEqual(agent.gemini_reply("هل هذا آمن؟"), answer)

    def test_missing_completion_reason_and_prompt_blocks_are_rejected(self):
        response = self.response()
        del response.json.return_value["candidates"][0]["finishReason"]
        self.post.return_value = response
        self.assertIsNone(agent.gemini_reply("هل يمكن شرحه؟"))
        response = self.response()
        response.json.return_value["promptFeedback"] = {"blockReason": "SAFETY"}
        self.post.return_value = response
        self.assertIsNone(agent.gemini_reply("هل يمكن شرحه؟"))

    def test_rate_limit_uses_local_answers_until_retry_time_without_sleeping(self):
        response = requests.Response()
        response.status_code = 429
        response.headers = CaseInsensitiveDict({"Retry-After": "90"})
        self.post.side_effect = requests.HTTPError("quota", response=response)
        with patch.object(agent.time, "monotonic", return_value=100) as clock:
            with patch.object(agent.time, "sleep") as sleep:
                self.ask("هل يمكن توضيحه؟")
                self.ask("هل يوجد وصف مفصل؟")
                self.assertEqual(self.post.call_count, 1)
                self.assertIn("30$", self.ask("كم سعر الجهاز؟"))
                self.assertEqual(self.post.call_count, 1)
                clock.return_value = 189
                self.ask("هل يمكن شرح ذلك؟")
                self.assertEqual(self.post.call_count, 1)
                clock.return_value = 191
                self.post.side_effect = None
                self.ask("هل يمكن شرح ذلك؟")
                self.assertEqual(self.post.call_count, 2)
                sleep.assert_not_called()
        self.assertEqual(agent.GEMINI_RECOVERY.failures, 0)

    def test_timeout_and_provider_failure_backoff_are_bounded(self):
        recovery = agent.GeminiRecovery()
        with patch.object(agent.time, "monotonic", return_value=10):
            self.assertTrue(recovery.allowed("key", "gemini-model"))
            for _ in range(10):
                recovery.failed(503, "999999")
            self.assertEqual(recovery.retry_at, 310)
            self.assertFalse(recovery.allowed("key", "gemini-model"))
            self.assertTrue(recovery.allowed("new-key", "gemini-model"))
        self.post.side_effect = requests.Timeout("unavailable")
        self.assertIsNone(agent.gemini_reply("هل يمكن شرحه؟"))
        self.assertIsNone(agent.gemini_reply("هل يمكن شرحه مجدداً؟"))
        self.post.assert_called_once()

    def test_sensitive_messages_and_unrelated_channels_do_not_enter_ai_memory(self):
        self.ask("اسمي أحمد ورقمي 0933123456")
        self.assertEqual(agent.session("customer")["public_dialogue"], [])
        self.post.assert_not_called()
        agent.handle_message("messenger", "هل يمكن شرح ذلك؟", source="messenger")
        self.assertEqual(agent.session("messenger")["public_dialogue"], [])
        self.post.assert_not_called()

    def test_standalone_confirmation_never_registers_an_order(self):
        self.ask("confirm")
        self.assertEqual(agent.list_orders()[1], 0)
        self.assertFalse(agent.session("customer")["done"])


if __name__ == "__main__":
    unittest.main()
