"""Reject malformed transport input before it reaches orders or storage."""
import unittest
from unittest.mock import patch

import app as agent
from demo_app import demo_app


class TelegramInputTests(unittest.TestCase):
    def setUp(self):
        self.client = agent.app.test_client()
        self.secret = patch.object(agent, 'WEBHOOK_SECRET', '')
        self.secret.start()
        self.addCleanup(self.secret.stop)

    def test_bad_input_never_claims_an_update_or_changes_conversation(self):
        invalid = [None, [], ['bad'], 'bad', 12, {},
                   {'update_id': True}, {'update_id': '12'}, {'update_id': -1},
                   {'update_id': 12, 'message': []},
                   {'update_id': 12, 'message': {'text': 12}},
                   {'update_id': 12, 'message': {'text': 'yes', 'chat': []}},
                   {'update_id': 12, 'message': {'text': 'yes', 'chat': {'id': True}}},
                   {'update_id': 12, 'message': {'text': 'yes', 'chat': {'id': '12'}}},
                   {'update_id': 12, 'message': {'text': ' ', 'chat': {'id': 12}}},
                   {'update_id': 12, 'message': {'text': 'x' * 4097, 'chat': {'id': 12}}}]
        with patch.object(agent, 'claim_update') as claim, patch.object(agent, 'handle_message') as handle:
            for payload in invalid:
                with self.subTest(payload=payload):
                    response = self.client.post('/telegram', json=payload)
                    self.assertEqual(response.status_code, 400)
            claim.assert_not_called()
            handle.assert_not_called()

    def test_non_text_updates_are_acknowledged_without_storage(self):
        with patch.object(agent, 'claim_update') as claim:
            for payload in ({'update_id': 12}, {'update_id': 13, 'message': {'photo': []}}):
                self.assertEqual(self.client.post('/telegram', json=payload).status_code, 200)
            claim.assert_not_called()

    def test_valid_group_message_and_duplicate(self):
        payload = {'update_id': 12, 'message': {'text': 'hello', 'chat': {'id': -123}}}
        with patch.object(agent, 'claim_update', side_effect=[True, False]), \
             patch.object(agent, 'handle_message', return_value='Hello') as handle, \
             patch.object(agent, 'telegram_api') as send:
            self.assertEqual(self.client.post('/telegram', json=payload).status_code, 200)
            self.assertTrue(self.client.post('/telegram', json=payload).get_json()['duplicate'])
            handle.assert_called_once_with(-123, 'hello', source='telegram')
            send.assert_called_once()

    def test_database_and_cleanup_outage_remains_retryable(self):
        payload = {'update_id': 12, 'message': {'text': 'hello', 'chat': {'id': 123}}}
        with patch.object(agent, 'claim_update', side_effect=RuntimeError('storage down')), \
             patch.object(agent, 'release_update', side_effect=RuntimeError('storage down')), \
             patch.object(agent, 'handle_message') as handle:
            response = self.client.post('/telegram', json=payload)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()['error'], 'temporary failure')
            handle.assert_not_called()


    def test_send_and_cleanup_outage_remains_retryable(self):
        payload = {'update_id': 12, 'message': {'text': 'hello', 'chat': {'id': 123}}}
        with patch.object(agent, 'claim_update', return_value=True), \
             patch.object(agent, 'release_update', side_effect=RuntimeError('storage down')), \
             patch.object(agent, 'handle_message', return_value='Hello'), \
             patch.object(agent, 'telegram_api', side_effect=RuntimeError('send failed')):
            response = self.client.post('/telegram', json=payload)
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.get_json()['error'], 'temporary failure')


class DemoInputTests(unittest.TestCase):
    def test_non_text_values_do_not_consume_demo_quota(self):
        demo_app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
        client = demo_app.test_client()
        with patch.object(agent, 'handle_message') as handle:
            for payload in (None, [], [1], 'yes', 12, {}, {'message': True},
                            {'message': 123}, {'message': ['confirm']}, {'message': {}}):
                with self.subTest(payload=payload):
                    self.assertEqual(client.post('/api/message', json=payload).status_code, 400)
            handle.assert_not_called()
        with client.session_transaction() as session:
            self.assertNotIn('demo_message_count', session)
            self.assertNotIn('demo_conversation_id', session)
