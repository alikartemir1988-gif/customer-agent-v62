import os
import sqlite3
import tempfile
import unittest

TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = os.path.join(TEST_DIR.name, "orders.db")
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ.pop("WEBHOOK_URL", None)
os.environ.pop("TELEGRAM_WEBHOOK_SECRET", None)

import app as customer_agent


class OrderFlowTests(unittest.TestCase):

    def setUp(self):
        customer_agent.SESSIONS.clear()

        with sqlite3.connect(customer_agent.DB_PATH) as conn:
            conn.execute("DELETE FROM orders")
            conn.execute("DELETE FROM processed_updates")
            conn.execute("DELETE FROM processed_messages")
            conn.execute("DELETE FROM sessions")
            conn.commit()

    def order_count(self):
        with sqlite3.connect(customer_agent.DB_PATH) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM orders"
            ).fetchone()[0]

    def test_order_is_saved_only_after_confirmation(self):
        chat_id = 101

        self.assertIn(
            "شو اسمك",
            customer_agent.handle_message(
                chat_id,
                "بدي جهازين",
            ),
        )
        self.assertIn(
            "رقم الهاتف",
            customer_agent.handle_message(
                chat_id,
                "أحمد خالد",
            ),
        )
        self.assertIn(
            "المدينة",
            customer_agent.handle_message(
                chat_id,
                "0933123456",
            ),
        )

        review = customer_agent.handle_message(
            chat_id,
            "دمشق",
        )

        self.assertIn("راجع طلبك", review)
        self.assertIn("الكمية: 2", review)
        self.assertIn("الإجمالي: 60$", review)
        self.assertEqual(self.order_count(), 0)

        confirmed = customer_agent.handle_message(
            chat_id,
            "تأكيد",
        )

        self.assertIn(
            "تم تسجيل طلبك",
            confirmed,
        )
        self.assertEqual(self.order_count(), 1)

    def test_customer_can_edit_before_confirmation(self):
        chat_id = 102

        for message in (
            "بدي جهازين",
            "محمد علي",
            "0944123456",
            "دمشق",
        ):
            customer_agent.handle_message(
                chat_id,
                message,
            )

        quantity_review = (
            customer_agent.handle_message(
                chat_id,
                "الكمية 3",
            )
        )
        city_review = (
            customer_agent.handle_message(
                chat_id,
                "المدينة حلب",
            )
        )

        self.assertIn(
            "الكمية: 3",
            quantity_review,
        )
        self.assertIn(
            "الإجمالي: 90$",
            quantity_review,
        )
        self.assertIn(
            "المدينة: حلب",
            city_review,
        )

        customer_agent.handle_message(
            chat_id,
            "نعم",
        )

        with sqlite3.connect(
            customer_agent.DB_PATH
        ) as conn:
            row = conn.execute(
                """
                SELECT quantity, city
                FROM orders
                """
            ).fetchone()

        self.assertEqual(row, (3, "حلب"))

    def test_repeated_confirmation_does_not_duplicate_order(self):
        chat_id = 103

        for message in (
            "بدي الجهاز",
            "سارة أحمد",
            "0955123456",
            "حمص",
            "تأكيد",
        ):
            customer_agent.handle_message(
                chat_id,
                message,
            )

        customer_agent.SESSIONS.clear()

        repeated = customer_agent.handle_message(
            chat_id,
            "تأكيد",
        )

        self.assertIn(
            "مسجل مسبقاً",
            repeated,
        )
        self.assertEqual(self.order_count(), 1)

    def test_cancel_does_not_write_order(self):
        chat_id = 104

        for message in (
            "بدي الجهاز",
            "علي حسن",
            "0966123456",
            "حلب",
        ):
            customer_agent.handle_message(
                chat_id,
                message,
            )

        cancelled = customer_agent.handle_message(
            chat_id,
            "إلغاء الطلب",
        )

        self.assertIn("لغيت", cancelled)
        self.assertEqual(self.order_count(), 0)

    def test_order_progress_survives_memory_restart(self):
        chat_id = 105

        customer_agent.handle_message(
            chat_id,
            "بدي الجهاز",
        )
        customer_agent.handle_message(
            chat_id,
            "نور أحمد",
        )

        customer_agent.SESSIONS.clear()

        phone_reply = customer_agent.handle_message(
            chat_id,
            "0999123456",
        )

        self.assertIn("المدينة", phone_reply)

        customer_agent.SESSIONS.clear()

        review = customer_agent.handle_message(
            chat_id,
            "دمشق",
        )

        self.assertIn("الاسم: نور أحمد", review)
        self.assertIn("الهاتف: 0999123456", review)
        self.assertIn("المدينة: دمشق", review)

    def test_reset_deletes_saved_session(self):
        chat_id = 106

        customer_agent.handle_message(
            chat_id,
            "بدي الجهاز",
        )
        customer_agent.handle_message(
            chat_id,
            "كريم علي",
        )

        customer_agent.reset(chat_id)
        customer_agent.SESSIONS.clear()

        state = customer_agent.session(chat_id)

        self.assertIsNone(state["name"])
        self.assertFalse(state["buying"])

    def test_color_question_keeps_pending_order(self):
        chat_id = 107

        for message in (
            "بدي الجهاز",
            "ليلى أحمد",
            "0933123456",
            "الحسكة",
        ):
            customer_agent.handle_message(chat_id, message)

        for question in (
            "كم لون عندكم",
            "ما هي الألوان المتوفرة",
        ):
            reply = customer_agent.handle_message(chat_id, question)
            self.assertIn("ألوان الجهاز المتوفرة", reply)
            self.assertIn("أسود", reply)
            self.assertIn("أبيض", reply)
            self.assertIn("ما زال جاهزاً للتأكيد", reply)
            self.assertNotIn("فهمت عليك جزئياً", reply)
            self.assertNotIn("راجع طلبك", reply)

        confirmed = customer_agent.handle_message(chat_id, "تأكيد")

        self.assertIn("تم تسجيل طلبك", confirmed)
        self.assertEqual(self.order_count(), 1)

    def test_color_and_payment_questions_share_one_answer(self):
        chat_id = 108

        for message in (
            "بدي الجهاز",
            "سامر علي",
            "0944123456",
            "دمشق",
        ):
            customer_agent.handle_message(chat_id, message)

        reply = customer_agent.handle_message(
            chat_id,
            "ما هو لون الجهاز وما هي طرق الدفع",
        )

        self.assertIn("ألوان الجهاز المتوفرة", reply)
        self.assertIn("طرق الدفع لـالجهاز", reply)
        self.assertIn("الدفع عند الاستلام", reply)
        self.assertIn("ما زال جاهزاً للتأكيد", reply)
        self.assertNotIn("فهمت عليك جزئياً", reply)

    def test_color_and_payment_questions_work_without_order(self):
        chat_id = 109

        reply = customer_agent.handle_message(
            chat_id,
            "ما هو لون الجهاز وما هي طرق الدفع",
        )

        self.assertIn("أسود", reply)
        self.assertIn("أبيض", reply)
        self.assertIn("الدفع عند الاستلام", reply)
        self.assertNotIn("فهمت عليك جزئياً", reply)


class TelegramWebhookTests(unittest.TestCase):

    def setUp(self):
        customer_agent.SESSIONS.clear()

        with sqlite3.connect(customer_agent.DB_PATH) as conn:
            conn.execute("DELETE FROM processed_updates")
            conn.execute("DELETE FROM processed_messages")
            conn.execute("DELETE FROM sessions")
            conn.commit()

    def test_duplicate_update_is_ignored(self):
        customer_agent.remember_update(5001)

        self.assertTrue(
            customer_agent.update_was_processed(
                5001
            )
        )
        self.assertFalse(
            customer_agent.update_was_processed(
                5002
            )
        )

    def test_webhook_secret_is_enforced_when_configured(self):
        old_secret = customer_agent.WEBHOOK_SECRET
        customer_agent.WEBHOOK_SECRET = "test-secret"

        try:
            client = customer_agent.app.test_client()

            rejected = client.post(
                "/telegram",
                json={
                    "update_id": 6001,
                },
            )
            accepted = client.post(
                "/telegram",
                json={
                    "update_id": 6002,
                },
                headers={
                    "X-Telegram-Bot-Api-Secret-Token":
                    "test-secret",
                },
            )
        finally:
            customer_agent.WEBHOOK_SECRET = (
                old_secret
            )

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 200)


class MessengerWebhookTests(unittest.TestCase):

    def setUp(self):
        customer_agent.SESSIONS.clear()
        with sqlite3.connect(customer_agent.DB_PATH) as conn:
            conn.execute("DELETE FROM processed_messages")
            conn.execute("DELETE FROM sessions")
            conn.commit()

    def test_webhook_verification_requires_matching_token(self):
        old_token = customer_agent.META_VERIFY_TOKEN
        customer_agent.META_VERIFY_TOKEN = "verify-secret"
        try:
            client = customer_agent.app.test_client()
            rejected = client.get(
                "/messenger?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=123"
            )
            accepted = client.get(
                "/messenger?hub.mode=subscribe&hub.verify_token=verify-secret&hub.challenge=123"
            )
        finally:
            customer_agent.META_VERIFY_TOKEN = old_token

        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.get_data(as_text=True), "123")

    def test_post_rejects_invalid_signature(self):
        old_secret = customer_agent.META_APP_SECRET
        customer_agent.META_APP_SECRET = "app-secret"
        try:
            response = customer_agent.app.test_client().post(
                "/messenger",
                json={"object": "page", "entry": []},
                headers={"X-Hub-Signature-256": "sha256=wrong"},
            )
        finally:
            customer_agent.META_APP_SECRET = old_secret

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
