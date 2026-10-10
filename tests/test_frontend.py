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

    def test_student_result_and_records_routes(self):
        denied = self.client.get('/records')
        self.assertEqual(denied.status_code, 302)
        self.assertTrue(denied.location.endswith('/admin/login'))
        self.assertEqual(self.client.get('/result').status_code, 302)
        self.assertEqual(self.post().status_code, 200)
        result = self.client.get('/result')
        self.assertEqual(result.status_code, 200)
        body = result.get_data(as_text=True)
        self.assertIn('"page": "result"', body)
        self.assertNotIn('"page": "records"', body)
        self.assertIn('"resultUrl": "/result"', body)
        self.assertIn('"recordsPageUrl": "/records"', body)
        still_denied = self.client.get('/records')
        self.assertEqual(still_denied.status_code, 302)
        self.assertTrue(still_denied.location.endswith('/admin/login'))
        from test_admin_access import login_admin
        login_admin(self.client)
        records = self.client.get('/records')
        self.assertEqual(records.status_code, 200)
        records_body = records.get_data(as_text=True)
        self.assertIn('"page": "records"', records_body)
        self.assertNotIn('"page": "result"', records_body)
        js = Path(__file__).resolve().parents[1].joinpath('static', 'campus.js').read_text(encoding='utf-8')
        self.assertIn('boot.resultUrl', js)
        self.assertIn('boot.recordsPageUrl', js)
        self.assertIn('history.pushState', js)
        self.assertIn("page='result'", js)

    def test_retired_page_shows_home(self):
        path = '/' + 'gar' + 'den'
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith('/'))
        page = self.client.get(path, follow_redirects=True)
        text = page.get_data(as_text=True)
        self.assertIn('>Home<', text)
        self.assertIn('Student view', text)
        self.assertNotIn('My ' + 'gar' + 'den', text)
        self.assertNotIn('data-nav="' + 'gar' + 'den' + '"', text)
        login = self.client.get('/admin/login').get_data(as_text=True)
        self.assertNotIn('My ' + 'gar' + 'den', login)

    def test_success_uses_backend_result_and_keeps_answers_out_of_cookie(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['result']['soft']['heading'], 'Worth a check-in')
        with self.client.session_transaction() as session:
            self.assertEqual(set(session), {'csrf_token', 'checkin_token'})
        record = next(iter(self.app.extensions['pending_checkins'].values()))['record']
        self.assertEqual(record['source'], 'ai_logic')
        stored = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(stored), 1)
        self.assertNotIn('feelings_text', stored[0])
        self.assertEqual(self.client.get('/result').status_code, 200)
        self.assertEqual(len(json.loads(self.path.read_text(encoding='utf-8'))), 1)

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

    def test_save_is_automatic_and_refresh_does_not_duplicate(self):
        self.post()
        self.assertEqual(len(json.loads(self.path.read_text(encoding='utf-8'))), 1)
        self.assertEqual(self.client.get('/result').status_code, 200)
        self.assertEqual(self.post({'opt_in':True}, '/save').status_code, 200)
        self.assertEqual(self.post({}, '/save').status_code, 200)
        records = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(records), 1)

    def test_submit_saves_record_for_admin_without_reflection(self):
        self.values['feelings_text'] = 'PRIVATE REFLECTION that must not be stored'
        response = self.post()
        self.assertEqual(response.status_code, 200)
        stored = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]['student_id'], '2605581')
        self.assertEqual(stored[0]['pss_1'], 3)
        self.assertEqual(stored[0]['sleep_hours_avg'], 6.5)
        self.assertNotIn('feelings_text', stored[0])
        self.assertNotIn('PRIVATE REFLECTION', self.path.read_text(encoding='utf-8'))
        self.assertEqual(self.client.get('/result').status_code, 200)
        self.assertEqual(len(json.loads(self.path.read_text(encoding='utf-8'))), 1)
        self.assertEqual(self.client.get('/api/records').status_code, 401)
        from test_admin_access import login_admin
        login_admin(self.client)
        records_page = self.client.get('/records')
        self.assertEqual(records_page.status_code, 200)
        self.assertIn('"page": "records"', records_page.get_data(as_text=True))
        payload = self.client.get('/api/records').json
        self.assertEqual(payload['matching'], 1)
        row = payload['records'][0]
        self.assertEqual(row['student_id'], '2605581')
        self.assertEqual(row['status'], 'Evaluated')
        self.assertNotIn('feelings_text', row)
        self.assertNotIn('reflection', row)
        self.assertNotIn('PRIVATE REFLECTION', json.dumps(payload))

    def test_ai_down_saves_pending_record_without_reflection(self):
        self.values['feelings_text'] = 'PRIVATE REFLECTION that must not be stored'
        self.app.config['AI_GENERATE_FN'] = lambda *args: '{}'
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('result', response.json)
        self.assertFalse(self.app.extensions['pending_checkins'])
        stored = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]['status'], 'pending')
        self.assertEqual(stored[0]['student_id'], '2605581')
        self.assertEqual(stored[0]['sleep_hours_avg'], 6.5)
        self.assertIs(stored[0]['ai_ok'], False)
        self.assertNotIn('feelings_text', stored[0])
        self.assertNotIn('PRIVATE REFLECTION', self.path.read_text(encoding='utf-8'))
        from test_admin_access import login_admin
        login_admin(self.client)
        row = self.client.get('/api/records').json['records'][0]
        self.assertEqual(row['student_id'], '2605581')
        self.assertEqual(row['status'], 'Pending')
        self.assertNotIn('feelings_text', row)
        self.assertNotIn('PRIVATE REFLECTION', json.dumps(row))

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
        with patch('main.data_manager.save_record', return_value={'ok':False}):
            self.assertEqual(self.post().status_code, 500)
        self.assertFalse(self.path.exists())
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(len(json.loads(self.path.read_text(encoding='utf-8'))), 1)


if __name__ == '__main__':
    unittest.main()
