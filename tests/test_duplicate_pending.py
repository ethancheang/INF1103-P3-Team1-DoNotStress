"""Repeated submits of one check-in must not duplicate a pending row.

Gemini is stubbed. These tests do not call the network.
"""
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from test_admin_access import login_admin
from test_frontend import fake_generate
from main import create_app

CALM = (
    'We could not complete your check-in right now. '
    'Your answers are still here; please try again.'
)


class DuplicatePendingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'records.json'
        self.app = create_app({
            'TESTING': True, 'SECRET_KEY': 'test-only',
            'AI_GENERATE_FN': lambda *args: '{}',
            'AI_MAX_ATTEMPTS': 1, 'AI_RETRY_DELAY_SEC': 0,
            'DATA_PATH': str(self.path),
        })
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.token = session['csrf_token']
        self.values = dict(
            student_id='2603050', pss_1=1, pss_2=4, pss_3=4, pss_4=3,
            sleep_hours_avg=7, sleep_quality=3, pas_workload=4, pas_catchup=3,
            fin_stress=4, mspss_friends=4, mspss_family=3,
            feelings_text='PRIVATE note that must not be stored',
        )

    def post(self, values=None, client=None):
        client = self.client if client is None else client
        return client.post('/', json=self.values if values is None else values,
                            headers={'X-CSRF-Token': self.token})

    def stored(self):
        self.assertTrue(self.path.exists())
        return json.loads(self.path.read_text(encoding='utf-8'))

    def test_repeated_failures_then_success_keep_one_record(self):
        for _ in range(5):
            response = self.post()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json['message'], CALM)
            self.assertNotIn('result', response.json)
        # Feelings are not part of the submission fingerprint.
        self.values['feelings_text'] = 'A different private note'
        self.assertEqual(self.post().status_code, 503)
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'pending')
        self.assertIs(rows[0]['ai_ok'], False)
        self.assertEqual(rows[0]['student_id'], '2603050')
        self.assertEqual(rows[0]['pss_1'], 1)
        self.assertEqual(rows[0]['sleep_hours_avg'], 7)
        self.assertRegex(rows[0]['record_id'], r'^[0-9a-f]{32}$')
        self.assertNotIn('feelings_text', rows[0])
        self.assertNotIn('PRIVATE', self.path.read_text(encoding='utf-8'))
        record_id = rows[0]['record_id']
        with self.client.session_transaction() as session:
            self.assertEqual(session['pending_record_id'], record_id)
            self.assertEqual(len(session['pending_fingerprint']), 64)

        self.app.config['AI_GENERATE_FN'] = fake_generate
        response = self.post()
        self.assertEqual(response.status_code, 200)
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['record_id'], record_id)
        self.assertNotEqual(rows[0].get('status'), 'pending')
        self.assertIs(rows[0]['ai_ok'], True)
        self.assertEqual(rows[0]['pss_1'], 1)
        self.assertEqual(rows[0]['student_id'], '2603050')
        self.assertNotIn('feelings_text', rows[0])

        changed = {**self.values, 'pss_1': 5, 'feelings_text': 'Still private'}
        response = self.post(changed)
        self.assertEqual(response.status_code, 200)
        rows = self.stored()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['record_id'], record_id)
        self.assertEqual(rows[0]['pss_1'], 1)
        self.assertEqual(rows[1]['pss_1'], 5)
        self.assertRegex(rows[1]['record_id'], r'^[0-9a-f]{32}$')
        self.assertNotEqual(rows[1]['record_id'], record_id)
        self.assertIs(rows[1]['ai_ok'], True)
        self.assertNotIn('Still private', self.path.read_text(encoding='utf-8'))

        login_admin(self.client)
        payload = self.client.get('/api/records').json
        self.assertEqual(payload['matching'], 2)
        self.assertEqual({row['status'] for row in payload['records']}, {'Evaluated'})
        self.assertNotIn('PRIVATE', json.dumps(payload))

    def test_rapid_posts_keep_one_pending_record(self):
        self.assertEqual(self.post().status_code, 503)
        self.assertEqual(self.post().status_code, 503)
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'pending')
        self.assertEqual(rows[0]['student_id'], '2603050')

    def test_concurrent_posts_keep_one_pending_record(self):
        cookie = self.client.get_cookie('session')
        barrier = threading.Barrier(2)
        statuses = []
        gate = threading.Lock()

        def worker():
            client = self.app.test_client()
            client.set_cookie('session', cookie.value)
            barrier.wait(timeout=5)
            response = self.post(client=client)
            with gate:
                statuses.append(response.status_code)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertEqual(sorted(statuses), [503, 503])
        rows = self.stored()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'pending')

    def test_different_answers_save_a_second_pending_row(self):
        self.assertEqual(self.post().status_code, 503)
        changed = {**self.values, 'sleep_quality': 5}
        self.assertEqual(self.post(changed).status_code, 503)
        rows = self.stored()
        self.assertEqual(len(rows), 2)
        self.assertEqual({row['status'] for row in rows}, {'pending'})
        self.assertEqual({row['sleep_quality'] for row in rows}, {3, 5})
        self.assertNotEqual(rows[0]['record_id'], rows[1]['record_id'])

    def test_pending_write_uses_atomic_replace(self):
        with patch('data_manager.os.replace', wraps=os.replace) as replaced:
            self.assertEqual(self.post().status_code, 503)
        self.assertTrue(replaced.called)
        self.assertEqual(Path(replaced.call_args.args[1]), self.path)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])
        self.assertEqual(len(self.stored()), 1)

    def test_submit_button_ignores_repeat_clicks(self):
        js = (Path(__file__).resolve().parents[1] / 'static' / 'campus.js').read_text(encoding='utf-8')
        self.assertIn('let assessment = boot.result || null, busy = false, submitting = false;', js)
        self.assertIn('if(!button||busy||submitting)return;', js)
        self.assertIn("button.disabled=true;await submit();", js)
        self.assertIn('if(submitting)return;', js)
        self.assertIn(CALM, js)


if __name__ == '__main__':
    unittest.main()
