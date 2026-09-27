import os
import unittest
from unittest import mock

import observability


class FakeSpan:

    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class ObservabilityTests(unittest.TestCase):

    def setUp(self):
        observability._langfuse_client = None
        observability._langfuse_unavailable = False

    def test_configuration_requires_all_connection_values(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(
                observability.langfuse_is_configured()
            )

        values = {
            "LANGFUSE_PUBLIC_KEY": "public",
            "LANGFUSE_SECRET_KEY": "secret",
            "LANGFUSE_BASE_URL": "https://example.invalid",
        }
        with mock.patch.dict(os.environ, values, clear=True):
            self.assertTrue(
                observability.langfuse_is_configured()
            )

    def test_base_url_is_normalized_without_scheme(self):
        values = {
            "LANGFUSE_BASE_URL": "us.cloud.langfuse.com",
        }
        with mock.patch.dict(os.environ, values, clear=True):
            self.assertEqual(
                observability._normalized_base_url(),
                "https://us.cloud.langfuse.com",
            )

    def test_base_url_accepts_copied_env_assignment(self):
        values = {
            "LANGFUSE_BASE_URL": (
                'LANGFUSE_BASE_URL="https://us.cloud.langfuse.com"'
            ),
        }
        with mock.patch.dict(os.environ, values, clear=True):
            self.assertEqual(
                observability._normalized_base_url(),
                "https://us.cloud.langfuse.com",
            )

    def test_base_url_rejects_unofficial_hosts(self):
        values = {
            "LANGFUSE_BASE_URL": "https://example.invalid",
        }
        with mock.patch.dict(os.environ, values, clear=True):
            with self.assertRaises(ValueError):
                observability._normalized_base_url()

    def test_content_is_redacted_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            payload = observability._content_payload(
                "هاتف 0999999999",
                "message",
            )

        self.assertTrue(payload["content_redacted"])
        self.assertNotIn("message", payload)
        self.assertEqual(
            payload["character_count"],
            len("هاتف 0999999999"),
        )

    def test_content_capture_requires_explicit_opt_in(self):
        with mock.patch.dict(
            os.environ,
            {"LANGFUSE_CAPTURE_CONTENT": "true"},
            clear=True,
        ):
            payload = observability._content_payload(
                "رسالة تجريبية",
                "message",
            )

        self.assertEqual(
            payload,
            {"message": "رسالة تجريبية"},
        )

    def test_session_identifier_is_private_and_channel_scoped(self):
        values = {"LANGFUSE_SECRET_KEY": "test-secret"}
        with mock.patch.dict(os.environ, values, clear=True):
            first = observability._anonymous_session_id(
                "123456",
                "telegram",
            )
            repeated = observability._anonymous_session_id(
                "123456",
                "telegram",
            )
            other_channel = observability._anonymous_session_id(
                "123456",
                "messenger",
            )

        self.assertEqual(first, repeated)
        self.assertNotEqual(first, other_channel)
        self.assertNotIn("123456", first)
        self.assertEqual(len(first), 24)

    def test_finish_records_progress_without_customer_content(self):
        span = FakeSpan()
        state = {
            "buying": True,
            "awaiting_confirmation": True,
            "done": False,
            "order_id": None,
        }

        with mock.patch.dict(os.environ, {}, clear=True):
            observability.finish_customer_message(
                span,
                "رد يحتوي بيانات عميل",
                state,
            )

        self.assertEqual(len(span.updates), 1)
        update = span.updates[0]
        self.assertTrue(
            update["output"]["content_redacted"]
        )
        self.assertNotIn(
            "رد يحتوي بيانات عميل",
            str(update),
        )
        self.assertTrue(update["metadata"]["buying"])
        self.assertTrue(
            update["metadata"]["awaiting_confirmation"]
        )
        self.assertFalse(update["metadata"]["done"])
        self.assertFalse(
            update["metadata"]["order_created"]
        )

    def test_disabled_context_is_a_no_op(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with observability.customer_message_span(
                "123",
                "hello",
                "test",
                version="test",
            ) as span:
                self.assertIsNone(span)

    def test_smoke_delivery_reads_actual_project_and_both_spans(self):
        project_response = mock.Mock(status_code=200)
        project_response.json.return_value = {
            "data": [{
                "id": "project-123",
                "name": "My Project",
                "organization": {"name": "My Organization"},
            }],
        }
        observations_response = mock.Mock(status_code=200)
        observations_response.json.return_value = {
            "data": [
                {"name": "customer-message", "metadata": {
                    "source": "smoke-test-run-1",
                    "sales_stage": "browsing",
                }},
                {"name": "customer-message", "metadata": {
                    "source": "smoke-test-run-1",
                    "sales_stage": "order_created",
                }},
                {"name": "customer-message", "metadata": {
                    "source": "another-run",
                    "sales_stage": "order_created",
                }},
            ],
        }
        env = {
            "LANGFUSE_BASE_URL": "https://us.cloud.langfuse.com",
            "LANGFUSE_PUBLIC_KEY": "public",
            "LANGFUSE_SECRET_KEY": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                observability.requests,
                "get",
                side_effect=[project_response, observations_response],
            ) as get:
                result = observability.inspect_langfuse_smoke_delivery(
                    "smoke-test-run-1", "2026-09-27T22:00:00Z"
                )

        self.assertEqual(result["project_name"], "My Project")
        self.assertEqual(result["project_id"], "project-123")
        self.assertTrue(result["normal_seen"])
        self.assertTrue(result["purchase_seen"])
        self.assertEqual(get.call_args_list[0].kwargs["auth"],
                         ("public", "secret"))
        self.assertEqual(get.call_args_list[1].kwargs["params"]["name"],
                         "customer-message")

    def test_smoke_delivery_does_not_count_unrelated_spans(self):
        project_response = mock.Mock(status_code=200)
        project_response.json.return_value = {"data": [{
            "id": "project-123",
            "name": "My Project",
            "organization": {"name": "My Organization"},
        }]}
        observations_response = mock.Mock(status_code=200)
        observations_response.json.return_value = {"data": [{
            "name": "customer-message", "metadata": {
                "source": "previous-run",
                "sales_stage": "order_created",
            },
        }]}
        env = {
            "LANGFUSE_BASE_URL": "https://us.cloud.langfuse.com",
            "LANGFUSE_PUBLIC_KEY": "public",
            "LANGFUSE_SECRET_KEY": "secret",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(
                observability.requests,
                "get",
                side_effect=[project_response, observations_response],
            ):
                result = observability.inspect_langfuse_smoke_delivery(
                    "this-run", "2026-09-27T22:00:00Z"
                )

        self.assertFalse(result["normal_seen"])
        self.assertFalse(result["purchase_seen"])


if __name__ == "__main__":
    unittest.main()
