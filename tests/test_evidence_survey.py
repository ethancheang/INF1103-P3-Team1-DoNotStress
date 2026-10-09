"""Boundary, direction, privacy and integration tests for the revised survey."""
import json
import unittest
from unittest.mock import patch

import ai_manager
import io_manager
import logic_manager
import survey
import test_frontend as frontend
from test_admin_access import login_admin

fake_generate = frontend.fake_generate


def raw(**changes):
    return dict(student_id='2605581', pss_1=0, pss_2=4, pss_3=4, pss_4=0,
                sleep_hours_avg=7, sleep_quality=0, pas_workload=1, fin_stress=10,
                mspss_friends=7, mspss_family=7, **changes)


def record(**changes):
    values=raw()
    values.update(changes)
    ok, result=io_manager.validate_student_form(values)
    assert ok, result
    return result


class ScoringTests(unittest.TestCase):
    def test_reverse_coding_extremes(self):
        self.assertEqual(record()['pss_total'],0)
        self.assertEqual(record(pss_1=4,pss_2=0,pss_3=0,pss_4=4)['pss_total'],16)
        self.assertEqual(record(pss_1=1,pss_2=2,pss_3=3,pss_4=4)['pss_total'],8)

    def test_every_possible_pss_total_and_band_boundary(self):
        for a in range(5):
            for b in range(5):
                for c in range(5):
                    for d in range(5):
                        r=record(pss_1=a,pss_2=b,pss_3=c,pss_4=d)
                        total=a+4-b+4-c+d
                        self.assertEqual(r['pss_total'],total)
                        self.assertEqual(r['risk_category'],'High' if total>=12 else 'Moderate' if total>=8 else 'Low')

    def test_sleep_boundary_and_quality(self):
        self.assertFalse(record(sleep_hours_avg=6,sleep_quality=1)['context_flags']['sleep'])
        self.assertTrue(record(sleep_hours_avg=5.5)['context_flags']['sleep'])
        self.assertTrue(record(sleep_quality=2)['context_flags']['sleep'])

    def test_finance_direction_and_context_cap(self):
        self.assertFalse(record(fin_stress=5)['context_flags']['finances'])
        self.assertTrue(record(fin_stress=4)['context_flags']['finances'])
        self.assertEqual(record(fin_stress=1)['risk_category'],'Low')
        self.assertEqual(record(fin_stress=1,pas_workload=4)['risk_category'],'Moderate')
        self.assertEqual(record(fin_stress=1,pas_workload=5,sleep_hours_avg=0,mspss_friends=1,mspss_family=1)['risk_category'],'Moderate')

    def test_optional_questions_and_mean(self):
        r=record(mspss_friends=1,mspss_family=4)
        self.assertEqual(r['support_mean'],2.5)
        self.assertTrue(r['context_flags']['support'])
        r=record(mspss_friends=1,mspss_family=4,mspss_so=7,pas_catchup=5)
        self.assertEqual(r['support_mean'],4)
        self.assertEqual(r['support_item_count'],3)
        self.assertFalse(r['context_flags']['support'])
        self.assertFalse(r['context_flags']['workload'])
        self.assertFalse(record(mspss_friends=3,mspss_family=3)['context_flags']['support'])

    def test_required_and_invalid_answers(self):
        for q in survey.QUESTIONS:
            for bad in (True, False, [], {}, float('nan'), float('inf'), q['min']-1, q['max']+1, 1.25):
                values=raw(); values[q['key']]=bad
                self.assertIn(q['key'],io_manager.validate_student_form(values)[1])
            values=raw();values.pop(q['key'],None)
            self.assertEqual(io_manager.validate_student_form(values)[0],bool(q.get('optional')),q['key'])

    def test_reflection_not_scored_or_sent(self):
        r=record(feelings_text='PRIVATE REFLECTION: I feel sad and depressed')
        self.assertEqual(r['risk_category'],'Low')
        self.assertNotIn('feelings_text',r)
        prompt=ai_manager.build_prompt(r)
        self.assertNotIn('PRIVATE REFLECTION',prompt)
        self.assertNotIn('2605581',prompt)
        for key in survey.QUESTION_MAP:self.assertIn(key,prompt)

    def test_safety_override_keeps_pss_unchanged(self):
        for text in ('I want to kill myself','I feel suicidal','I want to die','I might self-harm','I can’t keep myself safe'):
            r=record(feelings_text=text)
            self.assertTrue(r['safety_flag'],text)
            self.assertEqual(r['risk_category'],'High')
            self.assertEqual(r['pss_total'],0)

    def test_no_client_score_or_flag_trusted(self):
        r=record(pss_total=16,survey_version='fake',safety_flag=True,risk_category='High')
        self.assertEqual(r['pss_total'],0)
        self.assertFalse(r['safety_flag'])
        self.assertEqual(r['survey_version'],survey.VERSION)

    def test_ai_cannot_override_documented_band(self):
        fields=json.loads(fake_generate(None,None,None))
        fields.update(risk_score=1,risk_category='High',soft_label='Please reach out')
        r=logic_manager.apply_logic({**record(),**fields})
        self.assertEqual(r['risk_category'],'Low')
        self.assertEqual(r['risk_score'],0)
        self.assertEqual(len(r['factor_insights']),4)
        self.assertIn('not clinical cut-offs',r['reasoning'])

    def test_nonfinite_ai_numbers_rejected(self):
        for field in ('risk_score','confidence'):
            values=json.loads(fake_generate(None,None,None));values[field]=float('nan')
            self.assertFalse(ai_manager.validate_ai_response(values)[0])


class RevisedPipelineTests(unittest.TestCase):
    setUp = frontend.CampusTests.setUp
    post = frontend.CampusTests.post
    def test_new_record_storage_and_history(self):
        self.values.update(feelings_text='SENSITIVE NOTE that must not be retained',mspss_so=7,pas_catchup=4)
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post({'opt_in':True},'/save').status_code,200)
        stored=json.loads(self.path.read_text(encoding='utf-8'))[0]
        self.assertNotIn('feelings_text',stored)
        self.assertNotIn('SENSITIVE NOTE',self.path.read_text(encoding='utf-8'))
        self.assertEqual(stored['pss_total'],8)
        self.assertEqual(self.client.get('/api/records').status_code,401)
        login_admin(self.client)
        row=self.client.get('/api/records').json['records'][0]
        self.assertEqual(row['survey_version'],survey.VERSION)
        self.assertEqual(row['fin_stress'],8)
        self.assertEqual(row['mspss_so'],7)
        self.assertIsNone(row['stress_level'])

    def test_safety_remains_visible_when_ai_fails(self):
        self.values['feelings_text']='I want to end my life'
        self.app.config['AI_GENERATE_FN']=lambda *args:'{}'
        response=self.post()
        self.assertEqual(response.status_code,503)
        self.assertTrue(response.json['safety_flag'])
        self.assertIn('advisor',response.json)
        self.assertFalse(self.app.extensions['pending_checkins'])

    def test_safety_even_with_invalid_answers(self):
        response=self.post({**self.values,'pss_1':None,'feelings_text':'I want to die'})
        self.assertEqual(response.status_code,400)
        self.assertTrue(response.json['safety_flag'])

    def test_old_questionnaire_cannot_be_submitted_as_new(self):
        response=self.post(dict(student_id='2605581',sleep_hours=7,stress_level=5,
                                academic_workload=5,financial_stress=5,social_support=5))
        self.assertEqual(response.status_code,400)
        self.assertIn('pss_1',response.json['errors'])
