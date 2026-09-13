import unittest

import app as customer_agent
from demo_app import demo_app


class DemoAppTests(unittest.TestCase):

    def setUp(self):
        customer_agent.SESSIONS.clear()
        demo_app.config.update(
            TESTING=True,
            SESSION_COOKIE_SECURE=False,
        )
        self.client = demo_app.test_client()

    def send(self, message):
        return self.client.post(
            "/api/message",
            json={"message": message},
        )

    def test_demo_home_and_health(self):
        home = self.client.get("/")
        health = self.client.get("/health")

        self.assertEqual(home.status_code, 200)
        self.assertIn("وكيل العملاء V6", home.get_data(as_text=True))
        self.assertTrue(health.get_json()["ok"])
        self.assertFalse(health.get_json()["data_persistence"])

    def test_demo_uses_real_conversation_flow_without_saving_order(self):
        original_create_order = customer_agent.create_order

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("demo must not persist orders")

        customer_agent.create_order = fail_if_called
        try:
            self.assertIn("شو اسمك", self.send("بدي جهازين").get_json()["reply"])
            self.send("أحمد خالد")
            self.send("0999999999")
            review = self.send("دمشق").get_json()["reply"]
            confirmed = self.send("تأكيد").get_json()["reply"]
        finally:
            customer_agent.create_order = original_create_order

        self.assertIn("راجع طلبك", review)
        self.assertIn("تم تسجيل طلبك", confirmed)
        self.assertIn("DEMO-", confirmed)

    def test_demo_rejects_empty_messages(self):
        response = self.send("   ")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
