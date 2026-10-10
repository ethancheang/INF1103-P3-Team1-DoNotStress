"""Saved history and student-ID contract tests using synthetic records only."""
import json
import tempfile
import unittest
from pathlib import Path

import io_manager
from main import create_app, result_view
from test_admin_access import login_admin


class RecordsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'records.json'
        self.app = create_app({'TESTING': True, 'SECRET_KEY':'tests', 'DATA_PATH':str(self.path)})
        self.client = self.app.test_client()
        login_admin(self.client)
        self.rows = [dict(student_id=sid, sleep_hours=7.5, stress_level=stress,
                          academic_workload=6, financial_stress=4, social_support=7,
                          risk_category=risk, ai_ok=True, source='ai_logic', saved_at=date,
                          feelings_text='Private response that must not appear in history', reasoning='Private explanation')
                     for sid, stress, risk, date in [
                         ('2603503',5,'Moderate','2026-10-09T01:00:00+00:00'),
                         ('2703504',8,'High','2026-10-09T02:00:00+00:00'),
                         ('2000123',2,'Low','2026-10-09T03:00:00+00:00')]]

    def write(self, rows=None):
        self.path.write_text(json.dumps(self.rows if rows is None else rows), encoding='utf-8')

    def test_seven_digits_starting_with_two(self):
        for sid in ('2000000','2200000','2703504','2999999',' 2603503 '):
            self.assertTrue(io_manager.validate_student_id(sid)[0],sid)
        for sid in ('1200000','3000000','260350','26035030','2abc503','2１２３４５６',''):
            self.assertFalse(io_manager.validate_student_id(sid)[0],sid)

    def test_missing_file_is_empty(self):
        response=self.client.get('/api/records')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['records'],[])

    def test_all_records_columns_and_privacy(self):
        self.write()
        response=self.client.get('/api/records')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json['total'],3)
        self.assertEqual(response.json['records'][0]['student_id'],'2000123')
        self.assertEqual(set(response.json['records'][0]),{'student_id','sleep_hours','stress_level',
                         'academic_workload','financial_stress','social_support','risk_category','ai_status','saved_at',
                         'survey_version','stress_score','sleep_hours_avg','sleep_quality','pas_workload','pas_catchup',
                         'fin_stress','mspss_friends','mspss_family','support_mean'})
        self.assertNotIn('Private',response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_partial_id_and_combined_filters(self):
        self.write()
        self.assertEqual(self.client.get('/api/records?student_id=035').json['matching'],2)
        result=self.client.get('/api/records?student_id=035&risk_category=High&cohort_year=2027').json
        self.assertEqual(result['matching'],1)
        self.assertEqual(result['records'][0]['student_id'],'2703504')
        self.assertEqual(result['cohorts'],['27','26','20'])
        self.assertEqual(self.client.get('/api/records?risk_category=Low&cohort_year=26').json['records'],[])
        self.assertEqual(self.client.get('/api/records').json['matching'],3)

    def test_risk_filters(self):
        self.write()
        for risk in ('Low','Moderate','High'):
            rows=self.client.get('/api/records',query_string={'risk_category':risk}).json['records']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['risk_category'],risk)

    def test_errors_are_not_empty_history(self):
        self.path.write_text('invalid json',encoding='utf-8')
        self.assertEqual(self.client.get('/api/records').status_code,500)
        self.write()
        self.assertEqual(self.client.get('/api/records?risk_category=Critical').status_code,400)
        self.assertEqual(self.client.get('/api/records?cohort_year=abc').status_code,400)

    def test_legacy_status_and_missing_values(self):
        self.write([{'student_id':'2600000'}, {'student_id':'2700000','ai_ok':False}])
        statuses={r['student_id']:r['ai_status'] for r in self.client.get('/api/records').json['records']}
        self.assertEqual(statuses,{'2600000':'Unknown','2700000':'Failed'})

    def test_insights_use_assessment_and_inputs(self):
        view=result_view({**self.rows[0], 'soft_label':'Worth a check-in',
                          'tips':['short_breaks'], 'speak_prominence':'medium',
                          'primary_stressors':['academic_overload'],
                          'reasoning':'Workload contributes. Logic adjusted: internal_rule.'})
        self.assertEqual(view['insights']['risk_category'],'Moderate')
        self.assertEqual(view['insights']['explanation'],'Workload contributes.')
        self.assertEqual(view['insights']['snapshot']['stress_level'],5)

    def test_records_page(self):
        response=self.client.get('/records')
        self.assertEqual(response.status_code,200)
        self.assertIn('"page": "records"',response.get_data(as_text=True))


if __name__=='__main__':
    unittest.main()
