import os
import re
import tempfile
import unittest
from unittest import mock

_TEST_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_TEST_DIR.name, "support.db"))
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")

import app as agent
import dashboard
from demo_app import demo_app
from support import find_reviewed_answer


class SupportReadinessTests(unittest.TestCase):
    def setUp(self):
        self.client = agent.app.test_client()
        self.headers = {"X-Admin-Key": "test-admin-key"}
        agent.ADMIN_API_KEY = dashboard.ADMIN_API_KEY = "test-admin-key"
        agent.SESSIONS.clear()
        self.clear_support()

    def clear_support(self):
        conn = agent.db_connect()
        for table in ("support_faqs", "support_tickets", "support_daily_counts", "sessions"):
            conn.execute(f"DELETE FROM {table}")
        conn.commit()
        conn.close()

    def tearDown(self):
        self.clear_support()

    @staticmethod
    def faq(**changes):
        return {"question": "شو سياسة الضمان؟", "answer": "ضمان سنة ضد عيوب التصنيع.",
                "aliases": ["في ضمان؟"], "source_title": "سياسة الضمان المعتمدة",
                "source_url": "https://merchant.example/warranty", "approved": True, **changes}

    def add_faq(self, **changes):
        response = self.client.post("/admin/support/faqs", json=self.faq(**changes), headers=self.headers)
        self.assertEqual(response.status_code, 201)
        return response.get_json()["id"]

    def test_all_support_admin_operations_require_auth(self):
        operations = [("GET", "/admin/support/faqs"), ("GET", "/admin/support/tickets"),
                      ("GET", "/admin/support/stats"), ("POST", "/admin/support/faqs"),
                      ("PUT", "/admin/support/faqs/1"), ("DELETE", "/admin/support/faqs/1"),
                      ("POST", "/admin/support/tickets/1/close")]
        for method, path in operations:
            with self.subTest(path=path, method=method):
                self.assertEqual(self.client.open(path, method=method).status_code, 401)

    def test_draft_answers_are_not_published(self):
        self.add_faq(approved=False)
        with mock.patch.object(agent, "GEMINI_API_KEY", ""):
            reply = agent.handle_message("draft", "في ضمان؟", source="telegram")
        self.assertNotIn("ضمان سنة", reply)
        self.assertIn("موظف", reply)
        self.assertEqual(agent.support_store.metrics()["faq_answers"], 0)

    def test_approved_answers_include_source_and_work_across_channels(self):
        self.add_faq()
        with mock.patch.object(agent, "gemini_reply") as gemini:
            for channel in ("telegram", "messenger", "botpress"):
                reply = agent.handle_message(f"faq-{channel}", "في ضمان؟", source=channel)
                self.assertIn("ضمان سنة", reply)
                self.assertIn("المصدر: سياسة الضمان المعتمدة", reply)
                self.assertIn("https://merchant.example/warranty", reply)
        gemini.assert_not_called()
        self.assertEqual(agent.support_store.metrics()["faq_answers"], 3)
        self.assertIn("not verified", agent.support_store.metrics()["measurement"])

    def test_composite_question_can_use_an_exact_approved_policy_clause(self):
        self.add_faq()
        reply = agent.handle_message(
            "composite-reviewed", "كم سعر الجهاز؟ في ضمان؟", source="telegram"
        )
        self.assertIn("30$", reply)
        self.assertIn("ضمان سنة", reply)
        self.assertIn("المصدر: سياسة الضمان المعتمدة", reply)

    def test_invalid_schema_and_unsafe_sources_are_rejected(self):
        changes = [{"source_url": "javascript:alert(1)"}, {"source_url": "https://secret:password@merchant.example"},
                   {"approved": "false"}, {"aliases": "ضمان"}, {"answer": ""}, {"question": "؟!"}]
        for change in changes:
            with self.subTest(change=change):
                response = self.client.post("/admin/support/faqs", json=self.faq(**change), headers=self.headers)
                self.assertEqual(response.status_code, 400)
        self.assertEqual(agent.support_store.faqs(), [])

    def test_updates_and_deletion_take_effect_without_restart(self):
        faq_id = self.add_faq()
        changed = self.client.put(f"/admin/support/faqs/{faq_id}",
                                 json=self.faq(answer="السياسة الجديدة: ضمان ستة أشهر."), headers=self.headers)
        self.assertEqual(changed.status_code, 200)
        self.assertIn("ستة أشهر", agent.handle_message("update", "في ضمان؟", source="messenger"))
        self.assertEqual(self.client.delete(f"/admin/support/faqs/{faq_id}", headers=self.headers).status_code, 200)
        self.assertNotIn("ستة أشهر", agent.handle_message("deleted", "في ضمان؟", source="messenger"))

    def test_ambiguous_and_partial_questions_are_not_given_an_arbitrary_faq(self):
        item = self.faq()
        self.assertIsNone(find_reviewed_answer("في ضمان وهل في استرجاع؟", [item]))
        self.assertIsNone(find_reviewed_answer("في ضمان؟", [item, self.faq(answer="ضمان أسبوع.")]))

    def test_english_reviewed_questions_are_supported(self):
        self.add_faq(question="What is the warranty?", aliases=["Is there a warranty?"],
                     answer="A one-year warranty.", source_title="Merchant warranty policy")
        reply = agent.handle_message("english", "IS THERE A WARRANTY?", source="messenger")
        self.assertIn("Source: Merchant warranty policy", reply)

    def test_handoff_is_persistent_deduplicated_and_contains_context(self):
        state = agent.session("ticket-customer")
        state.update({"product": "الجهاز", "qty": 2, "order_id": 70})
        with mock.patch.object(agent, "gemini_reply") as gemini:
            reply = agent.handle_message("ticket-customer", "بدي احكي مع موظف", source="telegram")
            agent.SESSIONS.clear()
            agent.handle_message("ticket-customer", "هذه تفاصيل المشكلة", source="telegram")
            agent.handle_message("ticket-customer", "موظف", source="telegram")
        gemini.assert_not_called()
        tickets = agent.support_store.tickets()
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0]["context"]["order_id"], 70)
        self.assertIn("هذه تفاصيل المشكلة", [m["text"] for m in tickets[0]["messages"]])
        self.assertIn(str(tickets[0]["id"]), reply)
        self.assertEqual(agent.support_store.metrics()["handoffs"], 1)

    def test_closed_ticket_releases_bot_on_next_message(self):
        agent.handle_message("close", "موظف", source="messenger")
        ticket_id = agent.support_store.tickets()[0]["id"]
        response = self.client.post(f"/admin/support/tickets/{ticket_id}/close", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("30$", agent.handle_message("close", "كم سعر الجهاز؟", source="messenger"))
        self.assertEqual(agent.support_store.metrics()["open_tickets"], 0)

    def test_handoff_pauses_confirmation_and_resume_preserves_order(self):
        chat_id = "resume-order"
        for text in ("بدي جهازين", "اسمي أحمد محمد", "0933123456", "دمشق"):
            agent.handle_message(chat_id, text, source="messenger")
        self.assertTrue(agent.session(chat_id)["awaiting_confirmation"])
        agent.handle_message(chat_id, "موظف", source="messenger")
        agent.handle_message(chat_id, "تأكيد", source="messenger")
        self.assertFalse(agent.session(chat_id)["done"])
        agent.handle_message(chat_id, "ارجع للبوت", source="messenger")
        reply = agent.handle_message(chat_id, "تأكيد", source="messenger")
        self.assertIn("تم تسجيل طلبك", reply)
        self.assertEqual(agent.session(chat_id)["qty"], 2)
        self.assertEqual(agent.support_store.tickets(), [])

    def test_negative_staff_request_does_not_open_ticket(self):
        for i, text in enumerate(("ما بدي موظف", "ما بدي موظف لطلب متابعة",
                                  "لا أريد موظف لطلب متابعة", "ما بدي طلب موظف")):
            with self.subTest(text=text):
                agent.handle_message(f"negative-{i}", text, source="messenger")
        self.assertEqual(agent.support_store.tickets(), [])

    def test_full_staff_request_phrase_queues_followup_across_channels(self):
        phrases = ("موظف لطلب متابعة", "موظف لطلب متابعة.", "طلب موظف",
                   "موظف للمتابعة", "طلب متابعة من موظف")
        with mock.patch.object(agent, "gemini_reply") as gemini:
            for channel in ("telegram", "messenger", "botpress"):
                for i, text in enumerate(phrases):
                    with self.subTest(channel=channel, text=text):
                        chat_id = f"full-request-{channel}-{i}"
                        reply = agent.handle_message(chat_id, text, source=channel)
                        self.assertIn("طلبك محفوظ للمتابعة من موظف", reply)
                        ticket = agent.support_store.ticket(agent.session(chat_id)["support_ticket_id"])
                        self.assertEqual(ticket["messages"][0]["text"], text)
        gemini.assert_not_called()
        self.assertEqual(len(agent.support_store.tickets()), len(phrases) * 3)

    def test_demo_accepts_full_staff_request_phrase_and_resumes(self):
        demo_app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        client = demo_app.test_client()
        with mock.patch.object(agent, "GEMINI_API_KEY", ""), \
                mock.patch.object(agent.support_store, "open_ticket") as open_ticket:
            fallback = client.post("/api/message", json={"message": "سؤال غير موجود في الديمو"}).get_json()["reply"]
            self.assertIn("موظف", fallback)
            handoff = client.post("/api/message", json={"message": "موظف لطلب متابعة"}).get_json()["reply"]
            self.assertIn("لا يُحفظ طلب حقيقي", handoff)
            resumed = client.post("/api/message", json={"message": "ارجع للبوت"}).get_json()["reply"]
            self.assertIn("رجعنا للمساعد", resumed)
            price = client.post("/api/message", json={"message": "كم سعر الجهاز؟"}).get_json()["reply"]
            self.assertIn("30$", price)
        open_ticket.assert_not_called()
        self.assertEqual(agent.support_store.tickets(), [])

    def test_demo_uses_fictional_answers_and_never_writes_support_data(self):
        demo_app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        client = demo_app.test_client()
        before = agent.support_store.metrics()
        with mock.patch.object(agent.support_store, "open_ticket") as open_ticket:
            faq = client.post("/api/message", json={"message": "شو سياسة الضمان؟"}).get_json()["reply"]
            handoff = client.post("/api/message", json={"message": "موظف"}).get_json()["reply"]
            client.post("/api/message", json={"message": "هذه تفاصيل تجريبية"})
            client.post("/api/message", json={"message": "ارجع للبوت"})
        self.assertIn("بيانات وهمية", faq)
        self.assertIn("لا يُحفظ طلب حقيقي", handoff)
        open_ticket.assert_not_called()
        self.assertEqual(before, agent.support_store.metrics())

    def test_mounted_dashboard_requires_login_and_csrf_and_escapes_content(self):
        response = self.client.get("/dashboard/support")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].startswith("/dashboard/login"))
        login = self.client.get("/dashboard/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', login).group(1)
        self.assertEqual(self.client.post("/dashboard/login", data={"password": "test-admin-key", "csrf_token": token}).status_code, 302)
        support_page = self.client.get("/dashboard/support")
        self.assertEqual(support_page.status_code, 200)
        self.assertEqual(self.client.post("/dashboard/support/faqs", data={}).status_code, 400)
        token = re.search(r'name="csrf_token" value="([^"]+)"', support_page.get_data(as_text=True)).group(1)
        form = {"question": "سؤال", "answer": "جواب", "source_title": "<script>alert(1)</script>",
                "source_url": "", "aliases": "صيغة أخرى", "approved": "on", "csrf_token": token}
        self.assertEqual(self.client.post("/dashboard/support/faqs", data=form).status_code, 302)
        page = self.client.get("/dashboard/support").get_data(as_text=True)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertNotIn("<script>alert(1)</script>", page)


if __name__ == "__main__":
    unittest.main()
