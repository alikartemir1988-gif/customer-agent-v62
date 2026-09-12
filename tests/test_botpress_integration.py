import os
import sqlite3
import tempfile
import unittest
from unittest import mock


TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = os.path.join(TEST_DIR.name, "botpress-integration.db")
os.environ["BOTPRESS_INTEGRATION_SECRET"] = "test-botpress-secret"

import app as customer_agent


class BotpressIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = customer_agent.app.test_client()
        customer_agent.BOTPRESS_INTEGRATION_SECRET = "test-botpress-secret"
        customer_agent.SESSIONS.clear()

        with sqlite3.connect(customer_agent.DB_PATH) as conn:
            conn.execute("DELETE FROM order_status_events")
            conn.execute("DELETE FROM orders")
            conn.execute("DELETE FROM integration_messages")
            conn.execute("DELETE FROM sessions")
            conn.commit()

    def post_message(
        self,
        text,
        message_id="message-1",
        conversation_id="conversation-1",
        secret="test-botpress-secret",
    ):
        return self.client.post(
            "/integrations/botpress/message",
            json={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "text": text,
            },
            headers={"X-Botpress-Secret": secret},
        )

    def order_count(self):
        with sqlite3.connect(customer_agent.DB_PATH) as conn:
            return conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

    def test_integration_requires_an_independent_secret(self):
        with mock.patch.object(customer_agent, "BOTPRESS_INTEGRATION_SECRET", ""):
            unavailable = self.post_message("مرحبا")

        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(
            self.post_message("مرحبا", secret="wrong-secret").status_code,
            403,
        )

    def test_message_schema_is_validated(self):
        headers = {"X-Botpress-Secret": "test-botpress-secret"}

        self.assertEqual(
            self.client.post(
                "/integrations/botpress/message",
                data="not-json",
                headers=headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.post(
                "/integrations/botpress/message",
                json={
                    "conversation_id": "conversation-1",
                    "message_id": 123,
                    "text": "مرحبا",
                },
                headers=headers,
            ).status_code,
            400,
        )
        self.assertEqual(
            self.post_message("x" * 4001).status_code,
            400,
        )

    def test_reply_comes_from_the_existing_core_without_exposing_customer_data(self):
        response = self.post_message("مرحبا")
        payload = response.get_json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["duplicate"])
        self.assertIn("أهلاً وسهلاً", payload["reply"])
        self.assertEqual(payload["core_version"], customer_agent.APP_VERSION)
        self.assertEqual(
            payload["progress"],
            {
                "buying": False,
                "awaiting_confirmation": False,
                "done": False,
                "order_id": None,
            },
        )
        self.assertNotIn("name", payload)
        self.assertNotIn("phone", payload)

    def test_duplicate_message_returns_cached_reply_without_advancing_session(self):
        first = self.post_message("بدي جهازين")
        duplicate = self.post_message(
            "أحمد خالد",
            message_id="message-1",
        )

        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.get_json()["duplicate"])
        self.assertEqual(
            duplicate.get_json()["reply"],
            first.get_json()["reply"],
        )
        self.assertIsNone(
            customer_agent.session("botpress:conversation-1")["name"]
        )

        next_response = self.post_message(
            "أحمد خالد",
            message_id="message-2",
        )
        self.assertIn("رقم الهاتف", next_response.get_json()["reply"])

    def test_message_id_cannot_be_reused_across_conversations(self):
        self.post_message("مرحبا", message_id="shared-message")

        conflict = self.post_message(
            "مرحبا",
            message_id="shared-message",
            conversation_id="another-conversation",
        )

        self.assertEqual(conflict.status_code, 409)

    def test_an_in_flight_duplicate_does_not_advance_the_session(self):
        with sqlite3.connect(customer_agent.DB_PATH) as conn:
            conn.execute(
                """
                INSERT INTO integration_messages(
                    source, message_id, conversation_id,
                    response_text, processed_at
                ) VALUES(?,?,?,?,?)
                """,
                (
                    "botpress",
                    "in-flight-message",
                    "conversation-1",
                    "",
                    "2026-09-12T12:00:00",
                ),
            )
            conn.commit()

        response = self.post_message(
            "بدي جهازين",
            message_id="in-flight-message",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.headers["Retry-After"], "1")
        self.assertNotIn(
            "botpress:conversation-1",
            customer_agent.SESSIONS,
        )

    def test_complete_order_is_saved_once_and_audited_as_botpress(self):
        messages = (
            "بدي جهازين",
            "أحمد خالد",
            "0933123456",
            "دمشق",
            "تأكيد",
        )

        response = None
        for index, text in enumerate(messages, start=1):
            response = self.post_message(
                text,
                message_id=f"order-message-{index}",
                conversation_id="order-conversation",
            )

        self.assertIsNotNone(response)
        payload = response.get_json()
        self.assertIn("تم تسجيل طلبك", payload["reply"])
        self.assertTrue(payload["progress"]["done"])
        self.assertEqual(self.order_count(), 1)

        customer_agent.SESSIONS.clear()
        repeated = self.post_message(
            "تأكيد",
            message_id="order-message-5",
            conversation_id="order-conversation",
        )

        self.assertTrue(repeated.get_json()["duplicate"])
        self.assertEqual(repeated.get_json()["reply"], payload["reply"])
        self.assertEqual(self.order_count(), 1)

        with sqlite3.connect(customer_agent.DB_PATH) as conn:
            source = conn.execute(
                "SELECT source FROM order_status_events"
            ).fetchone()[0]

        self.assertEqual(source, "botpress")

    def test_botpress_and_existing_channels_have_separate_sessions(self):
        customer_agent.handle_message(
            "same-id",
            "بدي الجهاز",
            source="telegram",
        )
        response = self.post_message(
            "مرحبا",
            conversation_id="same-id",
        )

        self.assertTrue(customer_agent.session("same-id")["buying"])
        self.assertFalse(
            customer_agent.session("botpress:same-id")["buying"]
        )
        self.assertIn("أهلاً وسهلاً", response.get_json()["reply"])


if __name__ == "__main__":
    unittest.main()
