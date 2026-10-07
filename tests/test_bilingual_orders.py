"""End-to-end regression coverage for local Arabic and English conversations."""

import copy
import json
import os
import tempfile
import unittest
from unittest import mock

_TEST_DIR = tempfile.TemporaryDirectory()
os.environ.setdefault("DB_PATH", os.path.join(_TEST_DIR.name, "bilingual.db"))
os.environ.pop("DATABASE_URL", None)

import app as agent
from demo_app import demo_app


class BilingualOrderTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for name, value in (
            ("DB_PATH", os.path.join(directory.name, "orders.db")),
            ("DATABASE_URL", ""),
            ("PRODUCTS", copy.deepcopy(agent.DEFAULT_PRODUCTS)),
            ("DELIVERY", copy.deepcopy(agent.DEFAULT_DELIVERY)),
        ):
            patcher = mock.patch.object(agent, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        agent.SESSIONS.clear()
        self.addCleanup(agent.SESSIONS.clear)
        agent.init_db()
        ai_patcher = mock.patch.object(agent, "gemini_reply", return_value=None)
        self.ai = ai_patcher.start()
        self.addCleanup(ai_patcher.stop)

    def send(self, message, chat="customer", source="messenger"):
        return agent.handle_message(chat, message, source=source)

    def rows(self):
        conn = agent.db_connect()
        try:
            return conn.execute(
                "SELECT customer_name,customer_phone,product_name,color,quantity,city FROM orders"
            ).fetchall()
        finally:
            conn.close()

    def review(self, language="en", chat="customer", source="messenger"):
        messages = (
            ("I would like 2 white devices", "John Smith", "+44 7700 900123", "Damascus")
            if language == "en" else
            ("بدي جهازين لون أبيض", "أحمد خالد", "0933123456", "دمشق")
        )
        for text in messages:
            reply = self.send(text, chat, source)
        self.assertTrue(agent.session(chat)["awaiting_confirmation"])
        self.assertEqual(self.rows(), [])
        return reply

    def test_both_languages_review_save_and_repeated_confirmation_across_channels(self):
        for language in ("ar", "en"):
            for source in ("telegram", "messenger", "botpress"):
                with self.subTest(language=language, source=source):
                    # Each iteration gets an independent database and conversation.
                    conn = agent.db_connect()
                    conn.execute("DELETE FROM order_status_events")
                    conn.execute("DELETE FROM orders")
                    conn.commit()
                    conn.close()
                    chat = f"{language}-{source}"
                    reply = self.review(language, chat, source)
                    self.assertIn("راجع طلبك" if language == "ar" else "Review your order", reply)
                    self.assertIn("60$", reply)
                    confirm = "تأكيد" if language == "ar" else "confirm"
                    saved = self.send(confirm, chat, source)
                    self.assertIn("تم تسجيل طلبك" if language == "ar" else "saved successfully", saved)
                    agent.SESSIONS.clear()
                    repeated = self.send(confirm, chat, source)
                    self.assertIn("مسجل مسبقاً" if language == "ar" else "already saved", repeated)
                    row = self.rows()[0]
                    self.assertEqual(row[2:], ("الجهاز", "أبيض", 2, "دمشق"))
                    self.assertEqual(len(self.rows()), 1)
        self.ai.assert_not_called()

    def test_english_collects_every_step_and_rejects_invalid_inputs(self):
        self.assertIn("Which product", self.send("I want to order"))
        self.assertIn("Choose a color", self.send("Device"))
        self.assertIn("available color", self.send("purple"))
        self.assertIsNone(agent.session("customer")["color"])
        self.assertIn("How many", self.send("black"))
        for invalid in ("zero", "0", "-2", "1000001", "hello"):
            with self.subTest(invalid=invalid):
                self.assertIn("quantity between", self.send(invalid))
                self.assertFalse(agent.session("customer")["quantity_set"])
        self.assertIn("your name", self.send("three"))
        self.assertIn("phone number", self.send("Mary Jane Smith Jones"))
        self.assertIn("phone number", self.send("12345"))
        self.assertIn("Which city", self.send("+1 202 555 0123"))
        self.assertIn("Which city", self.send("Unknown city"))
        review = self.send("Aleppo")
        self.assertIn("Quantity: 3", review)
        self.assertIn("Color: Black", review)
        self.assertIn("City: Aleppo", review)
        self.assertEqual(self.rows(), [])

    def test_confirmation_before_details_does_not_save_or_become_name(self):
        self.send("I want to buy 2 white devices")
        self.assertIn("your name", self.send("confirm"))
        self.assertIsNone(agent.session("customer")["name"])
        self.assertEqual(self.rows(), [])

    def test_english_optional_color_can_be_skipped(self):
        self.send("I want 2 devices")
        self.assertIn("your name", self.send("skip"))
        self.send("John Smith")
        self.send("+447700900123")
        self.assertNotIn("Color:", self.send("Damascus"))
        self.send("yes")
        self.assertIsNone(self.rows()[0][3])

    def test_english_edits_all_fields_and_product_change_revalidates_color(self):
        self.review()
        self.assertIn("Send the new details", self.send("edit"))
        for message, expected in (
            ("name: Sarah O'Neil", "Name: Sarah O'Neil"),
            ("phone: +12025550123", "Phone: +12025550123"),
            ("city Aleppo", "City: Aleppo"),
            ("quantity three", "Quantity: 3"),
            ("color black", "Color: Black"),
        ):
            with self.subTest(message=message):
                self.assertIn(expected, self.send(message))
                self.assertEqual(self.rows(), [])
        self.assertIn("Product: Demo product", self.send("product Demo product"))
        self.send("confirm my order")
        self.assertEqual(self.rows(), [("Sarah O'Neil", "+12025550123", "منتج تجريبي", "أسود", 3, "حلب")])

    def test_invalid_quantity_edit_keeps_review_and_does_not_save(self):
        self.review()
        before = dict(agent.session("customer"))
        self.assertIn("quantity between", self.send("quantity -2"))
        self.assertEqual(agent.session("customer"), before)
        self.assertEqual(self.rows(), [])

    def test_unknown_color_edit_does_not_overwrite_selected_color(self):
        self.review()
        self.assertIn("available color", self.send("color purple"))
        self.assertEqual(agent.session("customer")["color"], "أبيض")
        self.assertEqual(self.rows(), [])

    def test_new_product_requires_new_valid_color(self):
        self.review()
        reply = self.send("product Demo product")
        self.assertIn("Choose a color: Black", reply)
        self.assertFalse(agent.session("customer")["awaiting_confirmation"])
        self.assertIsNone(agent.session("customer")["color"])
        self.assertIn("Review your order", self.send("black"))
        self.send("confirm")
        self.assertEqual(self.rows()[0][2:4], ("منتج تجريبي", "أسود"))

    def test_cancellation_resets_pending_order_in_both_languages(self):
        for language, command in (("en", "cancel order"), ("ar", "إلغاء الطلب")):
            with self.subTest(language=language):
                self.review(language, language)
                reply = self.send(command, language)
                self.assertIn("cancelled" if language == "en" else "لغيت", reply)
                self.assertFalse(agent.session(language)["buying"])
                self.assertEqual(self.rows(), [])
        self.assertIn("Which product", self.send("order", "en"))

    def test_declining_purchase_does_not_start_order(self):
        for i, message in enumerate(("I don't want to order", "I do not want a device", "How do I place an order?", "I want to know the price of the device")):
            with self.subTest(message=message):
                self.send(message, str(i))
                self.assertFalse(agent.session(str(i))["buying"])
                self.assertEqual(self.rows(), [])

    def test_arabic_negation_and_purchase_questions_do_not_start_order(self):
        for i, message in enumerate((
            "ما بدي اشتري، بس بدي أعرف إذا بتشتغل على القمر؟",
            "لا أريد أن أشتري الجهاز", "مو بدي أطلب الجهاز",
            "كيف بدي أطلب بدون ما يتسجل شي؟", "هل بقدر أشتري؟",
            "بدي أعرف كيف أطلب الجهاز", "ما بدي الجهاز",
        )):
            with self.subTest(message=message):
                self.send(message, f"negation:{i}")
                self.assertFalse(agent.session(f"negation:{i}")["buying"])
                self.assertIsNone(agent.session(f"negation:{i}")["name"])
                self.assertEqual(self.rows(), [])

    def test_unusual_questions_cannot_become_names_or_edit_pending_order(self):
        for source in ("telegram", "messenger", "botpress", "demo"):
            with self.subTest(source=source):
                chat = f"question:{source}"
                self.send("بدي أطلب الجهاز", chat, source)
                before = dict(agent.session(chat))
                for question in ("هل يغني؟", "بتقدر تطير", "في آلة زمن"):
                    answer = self.send(question, chat, source)
                    self.assertIn("ما عندي إجابة مؤكدة", answer)
                    self.assertIn("شو اسمك", answer)
                    self.assertEqual(agent.session(chat), before)
                self.assertEqual(self.rows(), [])

    def test_compound_information_does_not_mutate_order_in_either_language(self):
        questions = {
            "en": "How much are two devices, what colors are available, and delivery to Aleppo? Is there a warranty? Is delivery free?",
            "ar": "كم سعر قطعتين من الجهاز، وشو الألوان المتوفرة، والتوصيل إلى حلب؟ هل في ضمان؟ وهل التوصيل مجاني؟",
        }
        for language, message in questions.items():
            with self.subTest(language=language):
                self.review(language, language)
                before = dict(agent.session(language))
                reply = self.send(message, language)
                for expected in ("60$", "White" if language == "en" else "أبيض", "2-3 days" if language == "en" else "2-3 أيام", "Warranty" if language == "en" else "الضمان", "Delivery fees" if language == "en" else "رسوم التوصيل"):
                    self.assertIn(expected, reply)
                self.assertIn("still ready" if language == "en" else "ما زال جاهزاً", reply)
                self.assertEqual(agent.session(language), before)
                self.assertEqual(self.rows(), [])

    def test_purchase_and_questions_in_one_message_both_work(self):
        for language, message in (
            ("en", "I want 2 white devices; what is the price and delivery to Aleppo?"),
            ("ar", "بدي جهازين لون أبيض؛ كم السعر والتوصيل إلى حلب؟"),
        ):
            with self.subTest(language=language):
                reply = self.send(message, language)
                self.assertIn("30$", reply)
                self.assertIn("your name" if language == "en" else "شو اسمك", reply)
                state = agent.session(language)
                self.assertEqual((state["product"], state["color"], state["qty"]), ("الجهاز", "أبيض", 2))
                self.assertEqual(self.rows(), [])

    def test_policy_years_and_phone_do_not_become_item_quantity(self):
        reply = self.send("What is the price of the device with a 2 year warranty?")
        self.assertIn("30$", reply)
        self.assertNotIn("60$", reply)
        self.send("I want 2 white devices; my name is John Smith, phone +447700900123, city Damascus")
        self.assertEqual(agent.session("customer")["qty"], 2)
        self.assertEqual(self.rows(), [])

    def test_unknown_question_during_name_step_never_becomes_name(self):
        self.send("I want 2 black devices")
        before = dict(agent.session("customer"))
        reply = self.send("Where is my parcel?")
        self.assertIn("your name", reply)
        self.assertEqual(agent.session("customer"), before)
        self.assertIsNone(agent.session("customer")["name"])

    def test_english_labels_custom_catalog_and_configured_city_keep_canonical_storage(self):
        catalog = {"قميص": {"price": 12, "currency": "$", "name_en": "Shirt",
                            "aliases": ["shirts"], "colors": ["كحلي"],
                            "labels_en": {"كحلي": "Navy"}}}
        with mock.patch.object(agent, "PRODUCTS", catalog), mock.patch.object(agent, "DELIVERY", {"London": "2-3 days"}):
            self.assertIn("Current products", self.send("show products"))
            self.send("I want 3 navy shirts")
            self.send("John Smith")
            self.send("+447700900123")
            self.assertIn("City: London", self.send("London"))
            self.send("confirm")
        self.assertEqual(self.rows()[0][2:], ("قميص", "كحلي", 3, "London"))

    def test_invalid_english_catalog_labels_are_rejected(self):
        valid = {"Item": {"price": 1, "currency": "$"}}
        for invalid in ({"name_en": ""}, {"name_en": 7}, {"labels_en": []}, {"labels_en": {"Blue": ""}}):
            with self.subTest(invalid=invalid):
                catalog = copy.deepcopy(valid)
                catalog["Item"].update(invalid)
                self.assertFalse(agent._valid_products(catalog))

    def test_unavailable_product_cannot_be_confirmed(self):
        agent.PRODUCTS["الجهاز"]["available"] = False
        self.assertIn("unavailable", self.send("I want 2 black devices"))
        self.send("name: John Smith")
        self.send("+447700900123")
        self.send("Damascus")
        self.assertIn("unavailable", self.send("confirm"))
        self.assertEqual(self.rows(), [])

    def test_english_word_boundaries_do_not_confuse_names_with_hi_or_quantities(self):
        self.send("I want 2 black devices")
        self.assertIn("phone number", self.send("Whitney Stone"))
        self.assertEqual(agent.session("customer")["name"], "Whitney Stone")
        self.assertEqual(agent.session("customer")["qty"], 2)

    def test_language_and_numeric_steps_survive_restart(self):
        self.send("I want 2 black devices")
        self.send("John Smith")
        agent.SESSIONS.clear()
        self.assertIn("Which city", self.send("+447700900123"))
        agent.SESSIONS.clear()
        reply = self.send("Damascus")
        self.assertIn("Review your order", reply)
        self.assertEqual(agent.session("customer")["language"], "en")

    def test_legacy_arabic_session_without_language_fields_still_confirms(self):
        self.review("ar")
        state = dict(agent.session("customer"))
        for key in ("language", "order_step", "quantity_set", "color_skipped"):
            state.pop(key)
        conn = agent.db_connect()
        conn.execute("UPDATE sessions SET state_json=? WHERE chat_id=?", (json.dumps(state), "customer"))
        conn.commit()
        conn.close()
        agent.SESSIONS.clear()
        self.assertIn("تم تسجيل طلبك", self.send("تأكيد"))
        self.assertEqual(len(self.rows()), 1)

    def test_explicit_language_switch_keeps_review_details(self):
        self.review("ar")
        self.assertIn("Review your order", self.send("English"))
        self.assertIn("راجع طلبك", self.send("العربية"))
        self.send("تأكيد")
        self.assertEqual(self.rows()[0][2:], ("الجهاز", "أبيض", 2, "دمشق"))

    def test_handoff_and_return_preserve_review_and_block_confirmation_in_both_languages(self):
        for language, human, back, confirm in (
            ("en", "talk to a human", "back to bot", "confirm"),
            ("ar", "موظف", "ارجع للبوت", "تأكيد"),
        ):
            with self.subTest(language=language):
                # Clear saved orders from the previous iteration.
                conn = agent.db_connect()
                conn.execute("DELETE FROM order_status_events")
                conn.execute("DELETE FROM orders")
                conn.commit()
                conn.close()
                self.review(language, language)
                self.send(human, language)
                agent.SESSIONS.clear()
                reply = self.send(confirm, language)
                self.assertIn("queued for staff" if language == "en" else "محفوظ للمتابعة", reply)
                self.assertEqual(self.rows(), [])
                ticket = agent.support_store.tickets()[0]
                self.assertEqual(ticket["context"]["qty"], 2)
                self.assertIn("Review your order" if language == "en" else "راجع طلبك", self.send(back, language))
                self.assertEqual(agent.support_store.tickets(), [])
                self.send(confirm, language)
                self.assertEqual(len(self.rows()), 1)

    def test_compound_english_question_can_cite_approved_warranty(self):
        agent.support_store.save_faq({"question": "Is there a warranty?", "answer": "A one-year warranty.",
                                      "source_title": "Approved merchant policy", "approved": True})
        reply = self.send("How much is the device? Is there a warranty?")
        self.assertIn("30$", reply)
        self.assertIn("A one-year warranty.", reply)
        self.assertIn("Source: Approved merchant policy", reply)

    def test_english_demo_orders_and_handoffs_never_persist(self):
        client = demo_app.test_client()
        with mock.patch.object(agent, "create_order") as create, mock.patch.object(agent, "save_session") as save:
            for text in ("I want 2 white devices", "John Smith", "+447700900123", "Damascus", "talk to a human", "confirm", "back to bot", "confirm"):
                response = client.post("/api/message", json={"message": text})
                self.assertEqual(response.status_code, 200)
            reply = response.get_json()["reply"]
        self.assertIn("DEMO-", reply)
        self.assertIn("saved successfully", reply)
        create.assert_not_called()
        save.assert_not_called()
        self.assertEqual(self.rows(), [])
        self.assertEqual(agent.support_store.tickets(), [])

    def test_public_demo_interface_and_example_messages_support_both_languages(self):
        client = demo_app.test_client()
        for url, language, direction, title, example in (
            ("/", "ar", "rtl", "وكيل العملاء V6", "بدي جهازين لون أسود"),
            ("/?lang=en", "en", "ltr", "Customer Agent V6", "I want 2 black devices"),
        ):
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn(f'lang="{language}" dir="{direction}"', html)
                self.assertIn(title, html)
                self.assertIn(example, html)

    def test_polite_english_cancel_commands_cancel_only_the_draft(self):
        for i, command in enumerate(("cancel", "please cancel my order", "I want to cancel the order", "start over")):
            with self.subTest(command=command):
                self.review(chat=str(i))
                self.assertIn("cancelled", self.send(command, str(i)))
                self.assertEqual(self.rows(), [])

    def test_contact_numbers_never_replace_arabic_item_quantity(self):
        self.send("بدي الجهاز؛ اسمي أحمد خالد، رقمي 0933123456، المدينة دمشق")
        self.assertEqual(agent.session("customer")["qty"], 1)
        self.assertEqual(self.rows(), [])

    def test_question_about_color_availability_keeps_chosen_color(self):
        self.review()
        before = dict(agent.session("customer"))
        self.assertIn("Black", self.send("Is black available?"))
        self.assertEqual(agent.session("customer"), before)

    def test_demo_language_toggle_changes_prompts_without_resetting_order(self):
        client = demo_app.test_client()
        for text in ("بدي جهازين", "أحمد خالد", "0933123456", "دمشق"):
            client.post("/api/message", json={"message": text, "language": "ar"})
        reply = client.post("/api/message", json={"message": "edit", "language": "en"}).get_json()["reply"]
        self.assertIn("Send the new details", reply)
        reply = client.post("/api/message", json={"message": "quantity 3", "language": "en"}).get_json()["reply"]
        self.assertIn("Quantity: 3", reply)
        self.assertIn("أحمد خالد", reply)
        self.assertEqual(self.rows(), [])

    def test_all_english_order_fields_in_one_message_require_explicit_confirmation(self):
        reply = self.send("I want 2 white devices; my name is John Smith, phone +447700900123, city Damascus")
        for field in ("Review your order", "Name: John Smith", "Color: White", "Quantity: 2", "Phone: +447700900123", "City: Damascus"):
            self.assertIn(field, reply)
        self.assertEqual(self.rows(), [])
        self.send("confirm")
        self.assertEqual(self.rows(), [("John Smith", "+447700900123", "الجهاز", "أبيض", 2, "دمشق")])

    def test_english_payment_question_preserves_review_and_local_confirmation(self):
        self.review(source="telegram")
        before = dict(agent.session("customer"))
        reply = self.send("How can I pay?", source="telegram")
        self.assertIn("Cash on delivery", reply)
        self.assertIn("still ready", reply)
        self.assertEqual(agent.session("customer"), before)
        self.send("confirm", source="telegram")
        self.assertEqual(len(self.rows()), 1)
        self.ai.assert_not_called()


if __name__ == "__main__":
    unittest.main()
