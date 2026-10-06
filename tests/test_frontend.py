"""Server contract tests: run python -m unittest discover -s tests."""
import unittest

from app import create_app


class CampusTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only'})
        self.client = self.app.test_client()
        self.client.get('/')
        with self.client.session_transaction() as session:
            self.token = session['csrf_token']
        self.values = dict(student_id='2605581', sleep_hours='6.75', stress_level='7',
                           submission_rate='83.5', cca_count='2', financial_stress='yes',
                           consecutive_absences='1', free_text_concern='Example concern')

    def post(self, values):
        return self.client.post('/', json=values, headers={'X-CSRF-Token': self.token})

    def test_valid_record_and_no_student_data_in_session(self):
        self.assertEqual(self.post(self.values).status_code, 200)
        with self.client.session_transaction() as session:
            self.assertEqual(set(session), {'csrf_token', 'frontend_demo_ready'})
        self.assertEqual(self.client.get('/result').status_code, 200)

    def test_each_invalid_field_is_rejected(self):
        for field, value in [('student_id', '2200000'), ('sleep_hours', 'nan'),
                             ('stress_level', '11'), ('submission_rate', '101'),
                             ('cca_count', '1.5'), ('financial_stress', 'true'),
                             ('consecutive_absences', '-1')]:
            with self.subTest(field=field):
                response = self.post({**self.values, field: value})
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json['errors'])

    def test_optional_concern_and_boundaries(self):
        self.assertEqual(self.post({**self.values, 'free_text_concern': '',
                                   'sleep_hours': '24', 'stress_level': '1',
                                   'submission_rate': '0', 'cca_count': '0',
                                   'financial_stress': 'no'}).status_code, 200)

    def test_missing_token_and_malformed_payload(self):
        self.assertEqual(self.client.post('/', json=self.values).status_code, 403)
        self.assertEqual(self.post([]).status_code, 400)

    def test_result_gate_and_reset(self):
        self.assertEqual(self.client.get('/result').status_code, 302)
        self.post(self.values)
        self.client.get('/new')
        self.assertEqual(self.client.get('/result').status_code, 302)


if __name__ == '__main__':
    unittest.main()
