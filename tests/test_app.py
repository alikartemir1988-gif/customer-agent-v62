import os
import tempfile
import unittest
from unittest import mock


_TEST_DIR = tempfile.TemporaryDirectory()
os.environ["DB_PATH"] = os.path.join(_TEST_DIR.name, "customer_agent_test.db")
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ.pop("TELEGRAM_BOT_TOKEN", None)
os.environ.pop("WEBHOOK_URL", None)

import app as customer_agent


class CustomerAgentTests(unittest.TestCase):
    def setUp(self):
        self.client = customer_agent.app.test_client()
        conn = customer_agent.db_connect()
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM order_status_events")
        conn.execute("DELETE FROM orders")
        conn.execute("DELETE FROM processed_updates")
        conn.commit()
        conn.close()

    def test_health_reports_database_ok(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["database"], "ok")
        self.assertEqual(payload["configuration"], "ok")
        self.assertEqual(payload["configuration_errors"], [])

    def test_health_rejects_invalid_merchant_configuration(self):
        with mock.patch.object(
            customer_agent,
            "CONFIGURATION_ERRORS",
            ["PRODUCTS_JSON must be valid JSON"],
        ):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 503)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["database"], "ok")
        self.assertEqual(payload["configuration"], "error")
        self.assertEqual(
            payload["configuration_errors"],
            ["PRODUCTS_JSON must be valid JSON"],
        )

    def test_invalid_json_configuration_falls_back_without_exposing_value(self):
        secret_value = '{"private":"must-not-appear"'
        errors_before = list(customer_agent.CONFIGURATION_ERRORS)
        customer_agent.CONFIGURATION_ERRORS.clear()

        try:
            with mock.patch.dict(
                os.environ,
                {"PRODUCTS_JSON": secret_value},
            ):
                loaded = customer_agent._json_env(
                    "PRODUCTS_JSON",
                    customer_agent.DEFAULT_PRODUCTS,
                )

            self.assertIs(loaded, customer_agent.DEFAULT_PRODUCTS)
            self.assertEqual(
                customer_agent.CONFIGURATION_ERRORS,
                ["PRODUCTS_JSON must be valid JSON"],
            )
            self.assertNotIn(
                secret_value,
                " ".join(customer_agent.CONFIGURATION_ERRORS),
            )
        finally:
            customer_agent.CONFIGURATION_ERRORS[:] = errors_before

    def test_invalid_product_schema_uses_safe_fallback(self):
        errors_before = list(customer_agent.CONFIGURATION_ERRORS)
        customer_agent.CONFIGURATION_ERRORS.clear()

        try:
            with mock.patch.dict(
                os.environ,
                {"PRODUCTS_JSON": '{"Broken":{"currency":"$"}}'},
            ):
                loaded = customer_agent._json_env(
                    "PRODUCTS_JSON",
                    customer_agent.DEFAULT_PRODUCTS,
                    customer_agent._valid_products,
                )

            self.assertIs(loaded, customer_agent.DEFAULT_PRODUCTS)
            self.assertEqual(
                customer_agent.CONFIGURATION_ERRORS,
                ["PRODUCTS_JSON has an invalid schema"],
            )
        finally:
            customer_agent.CONFIGURATION_ERRORS[:] = errors_before

    def test_invalid_delivery_schema_uses_safe_fallback(self):
        errors_before = list(customer_agent.CONFIGURATION_ERRORS)
        customer_agent.CONFIGURATION_ERRORS.clear()

        try:
            with mock.patch.dict(
                os.environ,
                {"DELIVERY_JSON": '{"دمشق":3}'},
            ):
                loaded = customer_agent._json_env(
                    "DELIVERY_JSON",
                    customer_agent.DEFAULT_DELIVERY,
                    customer_agent._valid_delivery,
                )

            self.assertIs(loaded, customer_agent.DEFAULT_DELIVERY)
            self.assertEqual(
                customer_agent.CONFIGURATION_ERRORS,
                ["DELIVERY_JSON has an invalid schema"],
            )
        finally:
            customer_agent.CONFIGURATION_ERRORS[:] = errors_before

    def test_admin_api_rejects_missing_key(self):
        response = self.client.get("/admin/stats")
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.get_json()["ok"])

    def test_admin_api_accepts_configured_key(self):
        response = self.client.get(
            "/admin/stats",
            headers={"X-Admin-Key": "test-admin-key"},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["total_orders"], 0)

    def test_admin_orders_rejects_non_integer_limit(self):
        response = self.client.get(
            "/admin/orders?limit=all",
            headers={"X-Admin-Key": "test-admin-key"},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "limit must be an integer")

    def test_admin_orders_rejects_unknown_status(self):
        response = self.client.get(
            "/admin/orders?status=unknown",
            headers={"X-Admin-Key": "test-admin-key"},
        )
        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "invalid status")

    def test_admin_orders_rejects_invalid_offset(self):
        for offset in ("next", "-1", "1000001"):
            with self.subTest(offset=offset):
                response = self.client.get(
                    f"/admin/orders?offset={offset}",
                    headers={"X-Admin-Key": "test-admin-key"},
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()["ok"])

    def test_admin_orders_returns_pagination_metadata(self):
        for chat_id, name, phone in (
            (2101, "أحمد علي", "0933000001"),
            (2102, "سارة حسن", "0933000002"),
            (2103, "نور خالد", "0933000003"),
        ):
            customer_agent.handle_message(chat_id, "بدي اشتري الجهاز")
            customer_agent.handle_message(chat_id, f"اسمي {name}")
            customer_agent.handle_message(chat_id, phone)
            customer_agent.handle_message(chat_id, "دمشق")

        response = self.client.get(
            "/admin/orders?limit=1&offset=1",
            headers={"X-Admin-Key": "test-admin-key"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["orders"]), 1)
        self.assertEqual(payload["pagination"], {
            "limit": 1,
            "offset": 1,
            "total": 3,
            "has_more": True,
        })

    def test_order_status_changes_have_protected_audit_history(self):
        chat_id = 2201
        customer_agent.handle_message(chat_id, "بدي اشتري الجهاز")
        customer_agent.handle_message(chat_id, "اسمي رامي علي")
        customer_agent.handle_message(chat_id, "0933555555")
        customer_agent.handle_message(chat_id, "دمشق")

        conn = customer_agent.db_connect()
        order_id = conn.execute(
            "SELECT id FROM orders WHERE chat_id=?", (str(chat_id),)
        ).fetchone()["id"]
        conn.close()

        changed = self.client.patch(
            f"/admin/orders/{order_id}/status",
            json={"status": "processing"},
            headers={"X-Admin-Key": "test-admin-key"},
        )
        history = self.client.get(
            f"/admin/orders/{order_id}/history",
            headers={"X-Admin-Key": "test-admin-key"},
        )

        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.get_json()["previous_status"], "new")
        self.assertEqual(history.status_code, 200)
        events = history.get_json()["events"]
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["new_status"], "new")
        self.assertEqual(events[0]["source"], "telegram")
        self.assertEqual(events[1]["old_status"], "new")
        self.assertEqual(events[1]["new_status"], "processing")
        self.assertEqual(events[1]["source"], "admin_api")

    def test_telegram_webhook_rejects_wrong_secret(self):
        response = self.client.post(
            "/telegram",
            json={"message": {"text": "مرحبا", "chat": {"id": 1}}},
            headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 401)

    def test_telegram_webhook_rejects_oversized_payload(self):
        headers = {
            "X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret",
            "Content-Type": "application/json",
        }

        with mock.patch.object(customer_agent, "telegram_api") as send_mock:
            response = self.client.post(
                "/telegram",
                data=b"x" * (customer_agent.MAX_REQUEST_BYTES + 1),
                headers=headers,
            )

        self.assertEqual(response.status_code, 413)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "request payload too large")
        self.assertEqual(payload["max_bytes"], customer_agent.MAX_REQUEST_BYTES)
        send_mock.assert_not_called()

    def test_duplicate_telegram_update_is_processed_once(self):
        payload = {
            "update_id": 12345,
            "message": {"text": "/start", "chat": {"id": 42}},
        }
        headers = {"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"}

        with mock.patch.object(customer_agent, "telegram_api") as send_mock:
            first = self.client.post("/telegram", json=payload, headers=headers)
            duplicate = self.client.post("/telegram", json=payload, headers=headers)

        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.get_json()["ok"])
        self.assertEqual(duplicate.status_code, 200)
        self.assertTrue(duplicate.get_json()["duplicate"])
        send_mock.assert_called_once()

    def test_failed_telegram_update_can_be_retried(self):
        payload = {
            "update_id": 12346,
            "message": {"text": "/start", "chat": {"id": 43}},
        }
        headers = {"X-Telegram-Bot-Api-Secret-Token": "test-webhook-secret"}

        with mock.patch.object(
            customer_agent,
            "telegram_api",
            side_effect=[RuntimeError("temporary failure"), {"ok": True}],
        ) as send_mock:
            failed = self.client.post("/telegram", json=payload, headers=headers)
            retried = self.client.post("/telegram", json=payload, headers=headers)

        self.assertEqual(failed.status_code, 200)
        self.assertFalse(failed.get_json()["ok"])
        self.assertEqual(retried.status_code, 200)
        self.assertTrue(retried.get_json()["ok"])
        self.assertNotIn("duplicate", retried.get_json())
        self.assertEqual(send_mock.call_count, 2)

    def test_webhook_info_does_not_expose_bot_token_on_failure(self):
        secret_token = "secret-token-that-must-not-leak"
        secret_api_url = f"https://api.telegram.org/bot{secret_token}"
        failure = RuntimeError(f"request failed for {secret_api_url}/getWebhookInfo")

        with (
            mock.patch.object(customer_agent, "BOT_TOKEN", secret_token),
            mock.patch.object(customer_agent, "API", secret_api_url),
            mock.patch.object(customer_agent.requests, "get", side_effect=failure),
            mock.patch("builtins.print") as print_mock,
        ):
            response = self.client.get("/webhook-info")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"], "telegram request failed")
        self.assertNotIn(secret_token, response.get_data(as_text=True))
        logged = " ".join(str(arg) for call in print_mock.call_args_list for arg in call.args)
        self.assertNotIn(secret_token, logged)

    def test_color_count_question_is_understood(self):
        response = customer_agent.handle_message(7001, "كم لون")

        self.assertIn("الألوان المتوفرة", response)
        self.assertIn("أسود", response)
        self.assertNotIn("فهمت عليك جزئياً", response)

    def test_combined_color_and_payment_question_answers_both(self):
        response = customer_agent.handle_message(
            7002,
            "ما هو لون الجهاز وما هي طرق الدفع",
        )

        self.assertIn("ألوان الجهاز", response)
        self.assertIn("أسود", response)
        self.assertIn("أبيض", response)
        self.assertIn("طرق الدفع", response)
        self.assertIn("الدفع عند الاستلام", response)
        self.assertNotIn("فهمت عليك جزئياً", response)

    def test_combined_price_and_delivery_question_answers_both(self):
        response = customer_agent.handle_message(
            7003,
            "كم سعر الجهاز ومدة التوصيل إلى دمشق؟",
        )

        self.assertIn("30$", response)
        self.assertIn("التوصيل إلى دمشق", response)
        self.assertIn("3-5 أيام", response)
        self.assertNotIn("فهمت عليك جزئياً", response)

    def test_known_intent_does_not_fall_back_for_unknown_tail(self):
        response = customer_agent.handle_message(
            7004,
            "ما هو لون الجهاز وعندي سؤال ثاني غير واضح",
        )

        self.assertIn("ألوان الجهاز", response)
        self.assertNotIn("فهمت عليك جزئياً", response)

    def test_purchase_message_can_include_information_questions(self):
        response = customer_agent.handle_message(
            7005,
            "مرحبا، بدي اشتري الجهاز، كم سعره وما هي طرق الدفع؟",
        )

        self.assertIn("30$", response)
        self.assertIn("الدفع عند الاستلام", response)
        self.assertIn("شو اسمك", response)
        self.assertNotIn("فهمت عليك جزئياً", response)

    def test_quantity_between_purchase_word_and_product_starts_order(self):
        chat_id = 7009

        response = customer_agent.handle_message(chat_id, "بدي 4 أجهزة")

        self.assertIn("شو اسمك", response)
        self.assertNotIn("فهمت عليك جزئياً", response)
        state = customer_agent.session(chat_id)
        self.assertTrue(state["buying"])
        self.assertEqual(state["product"], "الجهاز")
        self.assertEqual(state["qty"], 4)

        customer_agent.handle_message(chat_id, "اسمي أحمد علي")
        customer_agent.handle_message(chat_id, "0933555555")
        completed = customer_agent.handle_message(chat_id, "دمشق")
        self.assertIn("الكمية: 4", completed)
        self.assertIn("الإجمالي: 120$", completed)

    def test_information_request_with_purchase_word_does_not_start_order(self):
        chat_id = 7011

        response = customer_agent.handle_message(chat_id, "بدي أعرف سعر الجهاز")

        self.assertIn("30$", response)
        self.assertFalse(customer_agent.session(chat_id)["buying"])

    def test_colloquial_payment_questions_are_understood(self):
        for index, question in enumerate(
            ("كيف فيني ادفع", "متى لازم ادفع", "شلون أدفع"),
            start=1,
        ):
            with self.subTest(question=question):
                response = customer_agent.handle_message(7100 + index, question)
                self.assertIn("طرق الدفع", response)
                self.assertIn("الدفع عند الاستلام", response)
                self.assertNotIn("فهمت عليك جزئياً", response)

    def test_short_cancel_command_resets_active_order(self):
        chat_id = 7010
        customer_agent.handle_message(chat_id, "بدي 4 أجهزة")

        response = customer_agent.handle_message(chat_id, "إلغاء")

        self.assertIn("لغيت المحادثة الحالية", response)
        self.assertEqual(customer_agent.session(chat_id), customer_agent.DEFAULT_STATE)

    def test_single_price_and_delivery_questions_still_work(self):
        price = customer_agent.handle_message(7006, "كم سعر الجهاز؟")
        delivery = customer_agent.handle_message(7007, "التوصيل إلى حمص؟")

        self.assertIn("30$", price)
        self.assertIn("التوصيل إلى حمص", delivery)
        self.assertIn("2-4 أيام", delivery)

    def test_color_question_during_order_preserves_and_resumes_flow(self):
        chat_id = 7008

        started = customer_agent.handle_message(chat_id, "بدي اشتري الجهاز")
        self.assertIn("اسم", started)

        color_answer = customer_agent.handle_message(chat_id, "كم لون عندكم")
        self.assertIn("ألوان الجهاز", color_answer)
        self.assertIn("أسود", color_answer)
        self.assertIn("طلبك الحالي ما زال محفوظاً", color_answer)
        self.assertIn("شو اسمك", color_answer)
        self.assertNotIn("فهمت عليك جزئياً", color_answer)

        customer_agent.handle_message(chat_id, "اسمي أحمد علي")
        customer_agent.handle_message(chat_id, "+963 944 123 456")
        completed = customer_agent.handle_message(chat_id, "دمشق")
        self.assertIn("تم تسجيل طلبك", completed)

        after_completion = customer_agent.handle_message(chat_id, "كم لون عندكم")
        self.assertIn("ألوان الجهاز", after_completion)
        self.assertIn("طلبك مسجل مسبقاً", after_completion)

        conn = customer_agent.db_connect()
        count = conn.execute(
            "SELECT COUNT(*) AS c FROM orders WHERE chat_id=?",
            (str(chat_id),),
        ).fetchone()["c"]
        conn.close()
        self.assertEqual(count, 1)

    def test_order_flow_persists_one_order_and_blocks_duplicate(self):
        chat_id = 9001

        first = customer_agent.handle_message(chat_id, "بدي اشتري الجهاز")
        self.assertIn("اسم", first)

        second = customer_agent.handle_message(chat_id, "اسمي أحمد علي")
        self.assertIn("رقم الهاتف", second)

        third = customer_agent.handle_message(chat_id, "+963 944 123 456")
        self.assertIn("المدينة", third)

        fourth = customer_agent.handle_message(chat_id, "دمشق")
        self.assertIn("تم تسجيل طلبك", fourth)

        duplicate = customer_agent.handle_message(chat_id, "دمشق")
        self.assertIn("مسجل مسبقاً", duplicate)

        conn = customer_agent.db_connect()
        count = conn.execute("SELECT COUNT(*) AS c FROM orders").fetchone()["c"]
        row = conn.execute(
            "SELECT customer_name, product_name, quantity, city, status FROM orders"
        ).fetchone()
        conn.close()

        self.assertEqual(count, 1)
        self.assertEqual(row["customer_name"], "أحمد علي")
        self.assertEqual(row["product_name"], "الجهاز")
        self.assertEqual(row["quantity"], 1)
        self.assertEqual(row["city"], "دمشق")
        self.assertEqual(row["status"], "new")


if __name__ == "__main__":
    unittest.main()
