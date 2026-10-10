"""Boundary, direction, privacy and integration tests for the revised survey."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_manager
import io_manager
import logic_manager
import survey
import test_frontend as frontend
from test_admin_access import login_admin

fake_generate = frontend.fake_generate


def raw(**changes):
    return dict(student_id='2605581', pss_1=1, pss_2=5, pss_3=5, pss_4=1,
                sleep_hours_avg=8, sleep_quality=1, pas_workload=1, pas_catchup=1, fin_stress=1,
                mspss_friends=5, mspss_family=5, **changes)

MAX_STRESS = dict(pss_1=5, pss_2=1, pss_3=1, pss_4=5, sleep_hours_avg=4, sleep_quality=5,
                  pas_workload=5, pas_catchup=5, fin_stress=5, mspss_friends=1, mspss_family=1)


def record(**changes):
    values=raw()
    values.update(changes)
    ok, result=io_manager.validate_student_form(values)
    assert ok, result
    return result


class ScoringTests(unittest.TestCase):
    def test_reverse_coding_extremes(self):
        self.assertEqual(record()['stress_score'],1.0)
        self.assertEqual(record(**MAX_STRESS)['stress_score'],5.0)
        self.assertEqual(record(pss_2=1)['stress_score'],round(15/11,2))  # reversed: 6-1 = 5
        self.assertEqual(record(pss_1=5)['stress_score'],round(15/11,2))  # not reversed
        self.assertEqual(survey.REVERSED_KEYS,('pss_2','pss_3','mspss_friends','mspss_family'))

    def test_average_and_band_boundaries(self):
        # 11 integer scores cannot land on 2.5 or 3.5 exactly. 27/11 is just below 2.5; 28/11 just above.
        low=dict(pss_1=5,pss_4=5,sleep_hours_avg=4.5,sleep_quality=5)  # sum 27
        moderate=dict(low,pas_workload=2)  # sum 28
        self.assertEqual((record(**low)['stress_score'],record(**low)['risk_category']),(round(27/11,2),'Low'))
        crossed=record(**moderate)
        self.assertEqual((crossed['stress_score'],crossed['risk_category']),(round(28/11,2),'Moderate'))
        self.assertEqual(crossed['soft_label'],'Worth a check-in')
        high=dict(pss_1=5,pss_4=5,sleep_hours_avg=4.5,sleep_quality=5,pas_workload=5,pas_catchup=5)
        for fin, total, band in [(4,38,'Moderate'),(5,39,'High')]:
            r=record(**high,fin_stress=fin)
            self.assertEqual((r['stress_score'],r['risk_category']),(round(total/11,2),band))
            self.assertEqual(r['soft_label'],{'Moderate':'Worth a check-in','High':'Please reach out'}[band])
        self.assertEqual(record()['soft_label'],"You're doing ok")

    def test_every_single_answer_on_every_question(self):
        for q in survey.QUESTIONS:
            if q['key']=='sleep_hours_avg':
                continue
            for value in range(1,6):
                r=record(**{q['key']:value})
                scored=6-value if q.get('reverse') else value
                self.assertEqual(r['stress_score'],round((10+scored)/11,2),q['key'])
                self.assertEqual(r['scored_item_count'],11)

    def test_sleep_hours_stay_hours_and_score_as_stress(self):
        bands=[(14,1),(8.5,1),(8,1),(7.5,2),(7,2),(6.5,3),(6,3),(5.5,4),(5,4),(4.5,5),(0,5)]
        for hours, scored in bands:
            r=record(sleep_hours_avg=hours)
            self.assertEqual(r['sleep_hours_avg'],hours)
            self.assertEqual(r['stress_score'],round((10+scored)/11,2),hours)
        self.assertFalse(io_manager.validate_student_form({**raw(),'sleep_hours_avg':6.75})[0])
        q=survey.QUESTION_MAP['sleep_hours_avg']
        self.assertEqual((q['kind'],q['min'],q['max'],q['step']),('slider',0,14,0.5))
        fin=survey.QUESTION_MAP['fin_stress']
        self.assertEqual((fin['kind'],fin['min'],fin['max'],fin['step'],fin['low'],fin['high']),
                         ('slider',1,5,1,'No stress at all','Overwhelming stress'))
        self.assertEqual(q['prompt'],'On average, how many hours of sleep have you gotten each night this week?')
        js=(Path(__file__).resolve().parents[1]/'static'/'campus.js').read_text(encoding='utf-8')
        self.assertNotIn('sleep_exact',js)
        self.assertNotIn('Or enter hours directly',js)
        self.assertNotIn('Use half-hour steps',js)
        self.assertNotIn('Skip / clear this answer',js)
        self.assertNotIn('ds-optional',js)
        self.assertIn('ds-q-title',js)
        self.assertNotIn('data-confirm',js)
        self.assertNotIn('Answer selected',js)
        self.assertNotIn('Move the slider or confirm the displayed position.',js)
        self.assertIn('Higher numbers mean more financial stress.',js)
        self.assertIn('Your student ID stays private.',js)
        self.assertIn("This space is just for you.",js)
        self.assertIn("This check-in isn't a diagnosis",js)
        self.assertIn('>Your check-in<',js)
        self.assertNotIn('stressBadge',js)
        self.assertNotIn('not sent to the AI provider',js)
        self.assertNotIn('Not sent to Gemini',js)
        self.assertNotIn('project guidance',js)
        self.assertNotIn('project heuristics',js)
        self.assertNotIn('documented project rules',js)
        self.assertNotIn('not a validated combined screening instrument',js)
        self.assertNotIn('Legacy /10',js)
        self.assertNotIn('Risk category',js)
        self.assertNotIn('AI Status',js)
        self.assertIn('Stress score (/5)',js)
        self.assertIn("You're doing ok",js)
        self.assertIn('SIT Counselling 24-hour helpline',js)
        self.assertIn('href="tel:65922030"',js)
        self.assertIn('href="tel:1767"',js)
        self.assertIn('href="tel:1771"',js)

    def test_prompts_and_pss_sentences(self):
        prompts={
            'pss_1':"In the past month, how often have you felt you couldn't control the important things in your life?",
            'pss_2':'In the past month, how often have you felt confident handling your personal problems?',
            'pss_3':'In the past month, how often have you felt things were going well for you?',
            'pss_4':'In the past month, how often have you felt problems were piling up too much to handle?',
        }
        self.assertEqual(survey.QUESTION_MAP['pss_1']['label'],'Losing control')
        self.assertEqual(survey.SECTIONS[0]['heading'],'Start with the bigger picture.')
        self.assertTrue(all('source' not in section for section in survey.SECTIONS))
        self.assertTrue(all('card' not in item for item in survey.QUESTIONS))
        page=(Path(__file__).resolve().parents[1]/'static'/'campus.js').read_text(encoding='utf-8')
        self.assertIn('Backed by research', page)
        self.assertNotIn('ds-source', page)
        self.assertNotIn('cardText', page)
        self.assertNotIn('team wording', page)
        for key, prompt in prompts.items():
            self.assertEqual(survey.QUESTION_MAP[key]['prompt'], prompt)
        self.assertEqual(survey.QUESTION_MAP['pas_workload']['prompt'],'I feel my coursework is too much to handle.')
        self.assertEqual(survey.QUESTION_MAP['pas_catchup']['prompt'],'When I fall behind on my work, I find it hard to catch up.')
        self.assertEqual(survey.QUESTION_MAP['mspss_family']['prompt'],'I get the emotional help and support I need from my family.')
        for item in survey.QUESTIONS:
            if item['key'].startswith('pss_') or item['key'] in ('sleep_hours_avg','sleep_quality','fin_stress'):
                self.assertTrue(item['prompt'].endswith('?'),item['key'])
            else:
                self.assertTrue(item['prompt'].endswith('.'),item['key'])

    def test_one_based_labels(self):
        r=record(sleep_hours_avg=7.5,sleep_quality=5,fin_stress=1)
        factors={item['title']:item['value'] for item in survey.factor_insights(r,r)}
        self.assertEqual(factors['Rest & recovery'],'7.5 hours · Very bad quality')
        self.assertEqual(factors['Money pressures'],'1/5 · No stress at all')
        shown={field['key']:field['value'] for field in io_manager.format_student_record(r)['fields']}
        self.assertEqual(shown['sleep_hours_avg'],'7.5')
        self.assertEqual(shown['sleep_quality'],'5 · Very bad')
        self.assertEqual(shown['fin_stress'],'1 · No stress at all')
        self.assertEqual(shown['pss_1'],'1 · Never')

    def test_sleep_boundary_and_quality(self):
        self.assertFalse(record(sleep_hours_avg=6,sleep_quality=3)['context_flags']['sleep'])
        self.assertTrue(record(sleep_hours_avg=5.5)['context_flags']['sleep'])
        self.assertTrue(record(sleep_quality=4)['context_flags']['sleep'])

    def test_finance_direction_and_flags_only_steer_tips(self):
        self.assertFalse(record(fin_stress=3)['context_flags']['finances'])
        self.assertTrue(record(fin_stress=4)['context_flags']['finances'])
        r=record(fin_stress=5,pas_workload=5)  # 19/11: flags no longer lift the band
        self.assertEqual(r['risk_category'],'Low')
        self.assertTrue(r['context_flags']['finances'] and r['context_flags']['workload'])

    def test_support_mean_and_required_fields(self):
        r=record(mspss_friends=1,mspss_family=3)
        self.assertEqual(r['support_mean'],2)
        self.assertEqual(r['support_item_count'],2)
        self.assertEqual(r['scored_item_count'],11)
        self.assertTrue(r['context_flags']['support'])
        self.assertFalse(record(mspss_friends=3,mspss_family=2)['context_flags']['support'])
        self.assertFalse(record(pas_catchup=5)['context_flags']['workload'])
        self.assertNotIn('mspss_so',survey.QUESTION_MAP)
        self.assertEqual(len(survey.QUESTIONS),11)
        self.assertTrue(all(not q.get('optional') for q in survey.QUESTIONS))
        for key in ('pas_catchup','mspss_friends','mspss_family'):
            values=raw();values.pop(key)
            self.assertIn(key,io_manager.validate_student_form(values)[1])

    def test_required_and_invalid_answers(self):
        for q in survey.QUESTIONS:
            for bad in (True, False, [], {}, float('nan'), float('inf'), q['min']-1, q['max']+1, 1.25):
                values=raw(); values[q['key']]=bad
                self.assertIn(q['key'],io_manager.validate_student_form(values)[1])
            values=raw();values.pop(q['key'],None)
            self.assertFalse(io_manager.validate_student_form(values)[0],q['key'])

    def test_reflection_not_scored_or_sent(self):
        r=record(feelings_text='PRIVATE REFLECTION: I feel sad and depressed')
        self.assertEqual(r['risk_category'],'Low')
        self.assertNotIn('feelings_text',r)
        prompt=ai_manager.build_prompt(r)
        self.assertNotIn('PRIVATE REFLECTION',prompt)
        self.assertNotIn('2605581',prompt)
        for key in survey.QUESTION_MAP:self.assertIn(key,prompt)
        self.assertIn(survey.QUESTION_MAP['pss_1']['prompt'],prompt)
        self.assertIn("In the past month, how often have you felt you couldn't control the important things in your life?",prompt)
        self.assertNotIn('mspss_so',prompt)
        self.assertNotIn('special person',prompt.lower())

    def test_safety_override_keeps_pss_unchanged(self):
        for text in ('I want to kill myself','I feel suicidal','I want to die','I might self-harm','I can’t keep myself safe'):
            r=record(feelings_text=text)
            self.assertTrue(r['safety_flag'],text)
            self.assertEqual(r['risk_category'],'High')
            self.assertEqual(r['stress_score'],1.0)

    def test_no_client_score_or_flag_trusted(self):
        r=record(stress_score=5,survey_version='fake',safety_flag=True,risk_category='High')
        self.assertEqual(r['stress_score'],1.0)
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
        self.values.update(feelings_text='SENSITIVE NOTE that must not be retained',pas_catchup=4,mspss_so=5)
        self.assertEqual(self.post().status_code,200)
        self.assertEqual(self.post({'opt_in':True},'/save').status_code,200)
        stored=json.loads(self.path.read_text(encoding='utf-8'))[0]
        self.assertNotIn('feelings_text',stored)
        self.assertNotIn('SENSITIVE NOTE',self.path.read_text(encoding='utf-8'))
        self.assertNotIn('mspss_so',stored)
        self.assertEqual(stored['sleep_hours_avg'],6.5)  # hours are stored, not a 1-5 band
        self.assertEqual(stored['pas_catchup'],4)
        self.assertEqual(stored['stress_score'],round(34/11,2))  # 10 answers at 3, catch-up 4
        self.assertEqual(self.client.get('/api/records').status_code,401)
        login_admin(self.client)
        row=self.client.get('/api/records').json['records'][0]
        self.assertEqual(row['survey_version'],survey.VERSION)
        self.assertEqual(row['fin_stress'],3)
        self.assertNotIn('mspss_so',row)
        self.assertNotIn('stress_level',row)
        self.assertEqual(row['status'],'Evaluated')

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
