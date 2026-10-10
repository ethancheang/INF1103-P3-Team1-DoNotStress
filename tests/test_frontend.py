"""Test the real I/O → AI schema → Logic → save pipeline without network calls."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from main import create_app


def fake_generate(prompt, api_key, model_name):
    return json.dumps({
        'risk_score': 0.4, 'risk_category': 'Moderate',
        'primary_stressors': ['academic_overload'],
        'recommended_support': 'Speak to campus support.', 'confidence': 0.8,
        'reasoning': 'Test fixture, not a real assessment.',
        'soft_label': 'Worth a check-in', 'tips': ['workload_chunks', 'short_breaks'],
        'speak_prominence': 'medium',
    })


class CampusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'records.json'
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only',
                               'AI_GENERATE_FN': fake_generate, 'AI_MAX_ATTEMPTS': 1,
                               'AI_RETRY_DELAY_SEC': 0, 'DATA_PATH': str(self.path)})
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.token = session['csrf_token']
        self.values = dict(student_id='2605581', pss_1=3, pss_2=3, pss_3=3, pss_4=3,
                           sleep_hours_avg=6.5, sleep_quality=3, pas_workload=3, pas_catchup=3,
                           fin_stress=3, mspss_friends=3, mspss_family=3, feelings_text='Example concern')

    def post(self, values=None, url='/'):
        return self.client.post(url, json=self.values if values is None else values,
                                headers={'X-CSRF-Token': self.token})

    def test_success_uses_backend_result_and_keeps_answers_out_of_cookie(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['result']['soft']['heading'], 'Worth a check-in')
        with self.client.session_transaction() as session:
            self.assertEqual(set(session), {'csrf_token', 'checkin_token'})
        record = next(iter(self.app.extensions['pending_checkins'].values()))['record']
        self.assertEqual(record['source'], 'ai_logic')
        self.assertFalse(self.path.exists())
        self.assertEqual(self.client.get('/result').status_code, 200)

    def test_invalid_fields_prevent_ai_call(self):
        for field, value in [('student_id','1200000'), ('sleep_hours_avg','6.75'),
                             ('pss_1','6'), ('pas_workload','0'),
                             ('fin_stress','yes'), ('mspss_friends','1.5')]:
            with self.subTest(field=field), patch('main.ai_manager.analyse_student') as ai:
                response = self.post({**self.values, field:value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json['errors'])
                ai.assert_not_called()

    def test_optional_text(self):
        self.assertEqual(self.post({**self.values, 'feelings_text':''}).status_code, 200)

    def test_missing_key_returns_error_and_no_logic_fallback(self):
        self.app.config['AI_GENERATE_FN'] = None
        with patch.dict(os.environ, {'GEMINI_API_KEY':''}), patch('main.logic_manager.apply_logic') as logic:
            response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['error_code'], 'missing_api_key')
        self.assertNotIn('result', response.json)
        self.assertIn('advisor', response.json)
        logic.assert_not_called()

    def test_invalid_ai_response_never_becomes_result(self):
        self.app.config['AI_GENERATE_FN'] = lambda *args: '{}'
        self.assertEqual(self.post().status_code, 503)
        self.assertEqual(self.client.get('/result').status_code, 302)

    def test_failure_clears_previous_result(self):
        self.post()
        self.app.config['AI_GENERATE_FN'] = lambda *args: '{}'
        self.post()
        self.assertFalse(self.app.extensions['pending_checkins'])
        self.assertEqual(self.client.get('/result').status_code, 302)

    def test_save_requires_consent_and_is_idempotent(self):
        self.post()
        self.assertEqual(self.post({'opt_in':False}, '/save').status_code, 400)
        self.assertEqual(self.post({'opt_in':'no'}, '/save').status_code, 400)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.post({'opt_in':True}, '/save').status_code, 200)
        self.assertEqual(self.post({'opt_in':True}, '/save').status_code, 200)
        records = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(records), 1)

    def test_csrf_and_malformed_requests(self):
        self.assertEqual(self.client.post('/', json=self.values).status_code, 403)
        self.assertEqual(self.post([]).status_code, 400)
        self.assertEqual(self.client.post('/save', json={'opt_in':True}).status_code, 403)

    def test_new_and_expired_result(self):
        self.post()
        self.client.get('/new')
        self.assertFalse(self.app.extensions['pending_checkins'])
        self.assertEqual(self.client.get('/result').status_code, 302)
        self.post()
        self.app.config['PENDING_TTL_SECONDS'] = -1
        self.assertEqual(self.client.get('/result').status_code, 302)
        self.assertEqual(self.post({'opt_in':True}, '/save').status_code, 409)

    def test_save_failure_is_retryable(self):
        self.post()
        with patch('main.data_manager.save_record', return_value={'ok':False}):
            self.assertEqual(self.post({'opt_in':True}, '/save').status_code, 500)
        self.assertEqual(self.post({'opt_in':True}, '/save').status_code, 200)


if __name__ == '__main__':
    unittest.main()
