"""Saved history and student-ID contract tests using synthetic records only."""
import json
import tempfile
import unittest
from pathlib import Path

import io_manager
import survey
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
        labels={'Low':"You're doing ok",'Moderate':'Worth a check-in','High':'Please reach out'}
        self.rows = [dict(student_id=sid, survey_version=survey.VERSION, stress_score=score,
                          stress_level=5, pss_1=2, pss_2=4, pss_3=3, pss_4=1,
                          sleep_hours_avg=7.5, sleep_quality=2, pas_workload=3,
                          pas_catchup=2, fin_stress=4, mspss_friends=4, mspss_family=5,
                          risk_category=risk, soft_label=labels[risk], ai_ok=True, source='ai_logic',
                          saved_at=date, feelings_text='Private response that must not appear in history',
                          reasoning='Private explanation')
                     for sid, score, risk, date in [
                         ('2603503',3.1,'Moderate','2026-10-09T01:00:00+00:00'),
                         ('2703504',4.2,'High','2026-10-09T02:00:00+00:00'),
                         ('2000123',1.4,'Low','2026-10-09T03:00:00+00:00')]]

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
        self.assertEqual(set(response.json['records'][0]),{'student_id','stress_score','risk_category','soft_label',
                         'pss_1','pss_2','pss_3','pss_4',
                         'sleep_hours_avg','sleep_quality','pas_workload','pas_catchup','fin_stress','mspss_friends',
                         'mspss_family','saved_at','survey_version','status'})
        self.assertEqual(response.json['records'][0]['pss_1'],2)
        self.assertEqual(response.json['records'][0]['sleep_hours_avg'],7.5)
        self.assertNotIn('stress_level',response.json['records'][0])
        self.assertNotIn('ai_status',response.json['records'][0])
        self.assertNotIn('Private',response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_partial_id_and_combined_filters(self):
        self.write()
        self.assertEqual(self.client.get('/api/records?student_id=035').json['matching'],2)
        result=self.client.get('/api/records?student_id=035&tier=Please reach out&cohort_year=2027').json
        self.assertEqual(result['matching'],1)
        self.assertEqual(result['records'][0]['student_id'],'2703504')
        self.assertEqual(result['cohorts'],['27','26','20'])
        self.assertEqual(self.client.get("/api/records?tier=You're doing ok&cohort_year=26").json['records'],[])
        self.assertEqual(self.client.get('/api/records').json['matching'],3)

    def test_tier_filters(self):
        self.write()
        for risk, tier in (('Low',"You're doing ok"),('Moderate','Worth a check-in'),('High','Please reach out')):
            rows=self.client.get('/api/records',query_string={'tier':tier}).json['records']
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['risk_category'],risk)
            self.assertEqual(rows[0]['soft_label'],tier)
            self.assertEqual(rows[0]['status'],'Evaluated')

    def test_errors_are_not_empty_history(self):
        self.path.write_text('invalid json',encoding='utf-8')
        self.assertEqual(self.client.get('/api/records').status_code,500)
        self.write()
        self.assertEqual(self.client.get('/api/records?tier=Critical').status_code,400)
        self.assertEqual(self.client.get('/api/records?cohort_year=abc').status_code,400)

    def test_legacy_records_are_ignored(self):
        self.write([
            {'student_id':'2600000','survey_version':'legacy','risk_category':'High'},
            {'student_id':'2700000','survey_version':'evidence-v2','ai_ok':False,'risk_category':'Low'},
            {'student_id':'2800000','survey_version':survey.VERSION,'status':'pending','risk_category':'Low'},
            {'student_id':'2900000','survey_version':survey.VERSION,'ai_ok':True,'source':'ai_logic','risk_category':'Moderate'},
            'not-a-record',
        ])
        payload=self.client.get('/api/records').json
        self.assertEqual(payload['total'],2)
        self.assertEqual(payload['cohorts'],['29','28'])
        statuses={row['student_id']:row['status'] for row in payload['records']}
        self.assertEqual(statuses,{'2800000':'Pending','2900000':'Evaluated'})
        pending=next(row for row in payload['records'] if row['student_id']=='2800000')
        self.assertEqual(pending['soft_label'],"You're doing ok")

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
        js=(Path(__file__).resolve().parents[1]/'static'/'campus.js').read_text(encoding='utf-8')
        css=(Path(__file__).resolve().parents[1]/'static'/'style.css').read_text(encoding='utf-8')
        for header in ('Control (pss_1)','Coping (pss_2)','Going well (pss_3)','Piling up (pss_4)',
                       'Sleep (hours)','Answers: 1 = lowest, 5 = highest · Sleep in hours'):
            self.assertIn(header,js)
        self.assertIn('title="${escape(title)}"',js)
        self.assertIn('overflow-x:auto',css)
        self.assertIn('max-width:75rem',css)


if __name__=='__main__':
    unittest.main()
