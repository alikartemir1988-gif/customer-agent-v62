"""Regressions from Revoke's Telegram conversation review."""

import copy
import os
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.pop("DATABASE_URL", None)
import app as agent


class ConversationControlTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in (
            ("DB_PATH", os.path.join(directory.name, "conversation.db")),
            ("DATABASE_URL", ""),
            ("PRODUCTS", copy.deepcopy(agent.DEFAULT_PRODUCTS)),
            ("DELIVERY", copy.deepcopy(agent.DEFAULT_DELIVERY)),
        ):
            manager = patch.object(agent, name, value)
            manager.start()
            self.addCleanup(manager.stop)
        agent.SESSIONS.clear()
        self.addCleanup(agent.SESSIONS.clear)
        agent.init_db()
        manager = patch.object(agent, "gemini_reply", return_value="جواب عن السؤال نفسه.")
        self.ai = manager.start()
        self.addCleanup(manager.stop)

    def ask(self, text, chat="customer", source="telegram"):
        return agent.handle_message(chat, text, source=source)

    def pending_city(self, chat="customer", source="telegram"):
        for message in ("بدي أطلب الجهاز", "اسمي أحمد خالد", "0933123456"):
            self.ask(message, chat, source)
        self.assertEqual(agent.session(chat)["order_step"], "city")

    def webhook(self, text, update_id=71001):
        with patch.object(agent, "telegram_api") as telegram, patch.object(agent, "WEBHOOK_SECRET", "test-secret"):
            response = agent.app.test_client().post(
                "/telegram", json={"update_id": update_id, "message": {
                    "text": text, "chat": {"id": "customer"},
                }}, headers={"X-Telegram-Bot-Api-Secret-Token": "test-secret"},
            )
        self.assertEqual(response.status_code, 200)
        telegram.assert_called_once()
        return telegram.call_args.kwargs["text"]

    def test_start_from_telegram_clears_old_draft_and_persisted_context(self):
        self.pending_city()
        agent.session("customer")["public_dialogue"] = [{"question": "كم السعر؟", "answer": "30$"}]
        agent.save_session("customer", agent.session("customer"))
        agent.SESSIONS.clear()
        answer = self.webhook("/start")
        self.assertIn("ريفوك", answer)
        agent.SESSIONS.clear()
        state = agent.session("customer")
        self.assertFalse(state["buying"])
        self.assertIsNone(state["name"])
        self.assertIsNone(state["phone"])
        self.assertEqual(state["public_dialogue"], [])
        self.assertNotIn("المدينة للتوصيل", self.ask("ما فهمت، وضحلي"))

    def test_start_does_not_delete_confirmed_orders(self):
        self.pending_city()
        self.ask("دمشق")
        self.ask("تأكيد")
        self.assertEqual(agent.list_orders()[1], 1)
        self.webhook("/start")
        self.assertEqual(agent.list_orders()[1], 1)
        self.assertFalse(agent.session("customer")["done"])
        self.assertIsNone(agent.session("customer")["order_id"])

    def test_start_and_reset_keep_arabic_in_a_new_telegram_chat(self):
        for number, command in enumerate(("/start", "/reset", "/start@RevokeBot")):
            with self.subTest(command=command):
                answer = self.webhook(command, update_id=71100 + number)
                self.assertIn("ريفوك", answer)
                self.assertEqual(agent.session("customer")["language"], "ar")

    def test_start_closes_only_current_support_ticket(self):
        self.ask("بدي أتواصل مع المالك")
        current_ticket = agent.session("customer")["support_ticket_id"]
        self.ask("موظف", chat="other")
        other_ticket = agent.session("other")["support_ticket_id"]
        self.webhook("/start")
        self.assertIsNone(agent.session("customer")["support_ticket_id"])
        self.assertEqual(agent.support_store.ticket(current_ticket)["status"], "closed")
        self.assertEqual(agent.support_store.ticket(other_ticket)["status"], "open")

    def test_asking_how_to_restart_or_cancel_explains_without_resetting(self):
        self.pending_city()
        before = copy.deepcopy(agent.session("customer"))
        for question in ("كيف أبدأ من جديد", "كيف ألغي الطلب؟", "How do I start over?"):
            with self.subTest(question=question):
                answer = self.ask(question)
                self.assertIn("/start" if "cancel" not in question and "ألغي" not in question else "cancel", answer)
                self.assertEqual(agent.session("customer"), before)
                self.assertNotIn("لغيت المحادثة", answer)
        self.ai.assert_not_called()

    def test_negated_restart_is_not_a_reset_command(self):
        self.pending_city()
        before = copy.deepcopy(agent.session("customer"))
        for message in ("ما بدي أبدأ من جديد", "لا تبدأ من جديد", "I don't want to start over", "ليش قلت ابدأ من جديد؟"):
            with self.subTest(message=message):
                self.ask(message)
                self.assertEqual(agent.session("customer"), before)
        self.assertEqual(agent.list_orders()[1], 0)

    def test_declining_to_continue_clears_pending_order_in_all_channels(self):
        messages = ("ما بدي نكمل الطلب السابق", "ما بدي أكمل طلبي", "لا أريد متابعة الطلب", "I don't want to continue my previous order")
        for source in ("telegram", "messenger", "botpress", "demo"):
            for number, message in enumerate(messages):
                with self.subTest(source=source, message=message):
                    chat = f"{source}:{number}"
                    self.pending_city(chat, source)
                    answer = self.ask(message, chat, source)
                    self.assertIn("لغيت", answer)
                    state = agent.session(chat)
                    self.assertFalse(state["buying"])
                    self.assertFalse(state["awaiting_confirmation"])
                    self.assertIsNone(state["name"])
                    self.assertIsNone(state["phone"])
        self.assertEqual(agent.list_orders()[1], 0)

    def test_declining_discount_or_explanation_preserves_order(self):
        self.pending_city()
        before = copy.deepcopy(agent.session("customer"))
        for message in ("ما بدي خصم", "ما بدي نكمل الشرح عن الطلب", "I don't want a discount"):
            with self.subTest(message=message):
                self.ask(message)
                self.assertEqual(agent.session("customer"), before)

    def test_negated_cancel_during_name_step_does_not_become_a_name(self):
        self.ask("بدي أطلب الجهاز")
        before = copy.deepcopy(agent.session("customer"))
        for message in ("لا تلغي الطلب", "ما بدي ألغي الطلب", "don't reset", "ما بدي أبدأ من جديد"):
            with self.subTest(message=message):
                self.ask(message)
                self.assertEqual(agent.session("customer"), before)
                self.assertIsNone(agent.session("customer")["name"])
        self.ai.assert_not_called()

    def test_unrelated_question_does_not_append_pending_delivery_reminder(self):
        self.pending_city()
        before = copy.deepcopy(agent.session("customer"))
        answer = self.ask("عندكم جهاز بيحوّل الهواء لذهب؟")
        self.assertEqual(answer, "جواب عن السؤال نفسه.")
        self.assertEqual(agent.session("customer"), before)

    def test_order_step_explanation_is_local_and_cannot_become_customer_name(self):
        self.ask("بدي أطلب الجهاز")
        before = copy.deepcopy(agent.session("customer"))
        answer = self.ask("ما فهمت شو لازم أعمل؟")
        self.assertIn("شو اسمك", answer)
        self.assertIn("مثال", answer)
        self.assertEqual(agent.session("customer"), before)
        self.ai.assert_not_called()

    def test_identity_and_unknown_owner_are_answered_without_catalog_promotion(self):
        for message, expected in (("ليش اسمك revoke", "ريفوك"), ("شو اسم المالك تبعك", "اسم")):
            with self.subTest(message=message):
                answer = self.ask(message)
                self.assertIn(expected, answer)
                self.assertNotIn("30", answer)
                self.assertNotIn("بدي أطلب", answer)
        self.ai.assert_not_called()

    def test_explicit_owner_contact_queues_followup_without_promising_owner_connection(self):
        answer = self.ask("بدي أتواصل مع المالك")
        tickets = agent.support_store.tickets()
        self.assertEqual(len(tickets), 1)
        self.assertIn("متابعة", answer)
        self.assertIn("اتصال مباشر", answer)
        self.assertFalse(agent.session("customer")["buying"])
        self.assertEqual(agent.session("customer")["support_ticket_id"], tickets[0]["id"])
        self.ai.assert_not_called()

    def test_approved_public_owner_answer_takes_precedence_over_unknown_owner(self):
        agent.support_store.save_faq({
            "question": "شو اسم المالك تبعك", "answer": "صاحب المتجر: الاسم التجاري المعتمد.",
            "approved": True, "source_title": "بيانات المتجر", "aliases": [],
        })
        answer = self.ask("شو اسم المالك تبعك")
        self.assertIn("الاسم التجاري المعتمد", answer)
        self.assertIn("المصدر", answer)
        self.assertNotIn("غير مضاف", answer)
        self.ai.assert_not_called()

    def test_negative_owner_contact_does_not_open_ticket(self):
        self.ask("ما بدي أتواصل مع المالك")
        self.assertEqual(agent.support_store.tickets(), [])

    def test_general_question_with_greeting_reaches_ai_instead_of_store_greeting(self):
        answer = self.ask("هلا سؤال، ليش السماء زرقاء")
        self.assertEqual(answer, "جواب عن السؤال نفسه.")
        self.ai.assert_called_once()


class AiResponseStyleTests(unittest.TestCase):
    def test_unrequested_purchase_paragraph_and_markdown_are_removed(self):
        response = Mock()
        response.json.return_value = {"candidates": [{"finishReason": "STOP", "content": {
            "parts": [{"text": "السعر **30$** للقطعة.\n\nإذا حابب تطلب الآن، اكتب ببساطة: **بدي أطلب**."}],
        }}]}
        with (patch.object(agent, "GEMINI_API_KEY", "test-key"),
              patch.object(agent, "GEMINI_MODEL", "gemini-3.5-flash-lite"),
              patch.object(agent.requests, "post", return_value=response)):
            agent.GEMINI_RECOVERY.reset()
            answer = agent.gemini_reply("ما فهمت السعر، وضحلي بمثال")
            agent.GEMINI_RECOVERY.reset()
        self.assertEqual(answer, "السعر 30$ للقطعة.")

    def test_invitation_after_answer_in_same_paragraph_keeps_the_answer(self):
        answer = "سعر القطعة 30$. إذا حابب تطلب، اكتب بدي أطلب."
        self.assertEqual(agent.clean_ai_style(answer, "وضح السعر"), "سعر القطعة 30$.")

    def test_customer_ordering_question_retains_requested_steps(self):
        answer = "إذا بدك تطلب، اكتب: بدي أطلب، ثم أرسل البيانات المطلوبة."
        self.assertEqual(agent.clean_ai_style(answer, "كيف أطلب الجهاز؟"), answer)


if __name__ == "__main__":
    unittest.main()
