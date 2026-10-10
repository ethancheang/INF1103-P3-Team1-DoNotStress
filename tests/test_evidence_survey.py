"""Boundary, direction, privacy and integration tests for the standardised 1.0-5.0 survey."""

import json
import unittest
from unittest.mock import patch

import ai_manager
import io_manager
import logic_manager
import test_frontend as frontend
from test_admin_access import login_admin

fake_generate = frontend.fake_generate


def raw(**changes):
    return dict(
        student_id='2605581',
        pss_1=1, pss_2=5, pss_3=5, pss_4=1,
        sleep_hours_avg=7, sleep_quality=0, pas_workload=1, fin_stress=10,
        mspss_friends=7, mspss_family=7, **changes
    )


def record(**changes):
    values = raw()
    values.update(changes)
    ok, result = io_manager.validate_student_form(values)
    assert ok, result
    return result


class ScoringTests(unittest.TestCase):
    def test_reverse_scoring_and_prepare_answers(self):
        # Raw 1-5 answers: items 2 and 3 reverse-score as 6 - answer
        prepared = io_manager.prepare_answers({'pss_1': 1, 'pss_2': 5, 'pss_3': 5, 'pss_4': 1})
        self.assertEqual(prepared['pss_1'], 1)
        self.assertEqual(prepared['pss_2'], 1)  # 6 - 5 = 1
        self.assertEqual(prepared['pss_3'], 1)  # 6 - 5 = 1
        self.assertEqual(prepared['pss_4'], 1)

        prepared_high = io_manager.prepare_answers({'pss_1': 5, 'pss_2': 1, 'pss_3': 1, 'pss_4': 5})
        self.assertEqual(prepared_high['pss_2'], 5)  # 6 - 1 = 5
        self.assertEqual(prepared_high['pss_3'], 5)  # 6 - 1 = 5

    def test_reference_score_and_tier_assignment(self):
        # All 1s -> 1.0 -> 'You're doing ok'
        ref_low = logic_manager.compute_reference_score({'pss_1': 1, 'pss_2': 1, 'pss_3': 1, 'pss_4': 1})
        self.assertEqual(ref_low, 1.0)
        self.assertEqual(logic_manager.assign_tier(ref_low), logic_manager.TIER_OK)

        # Average 3.0 -> 'Worth a check-in'
        ref_mid = logic_manager.compute_reference_score({'pss_1': 3, 'pss_2': 3, 'pss_3': 3, 'pss_4': 3})
        self.assertEqual(ref_mid, 3.0)
        self.assertEqual(logic_manager.assign_tier(ref_mid), logic_manager.TIER_CHECK_IN)

        # Average 4.0 -> 'Please reach out'
        ref_high = logic_manager.compute_reference_score({'pss_1': 4, 'pss_2': 4, 'pss_3': 4, 'pss_4': 4})
        self.assertEqual(ref_high, 4.0)
        self.assertEqual(logic_manager.assign_tier(ref_high), logic_manager.TIER_REACH_OUT)

    def test_sleep_boundary_and_quality(self):
        flags, _, _ = logic_manager.compute_context_flags(record(sleep_hours_avg=6, sleep_quality=1))
        self.assertFalse(flags['sleep'])

        flags_short, _, _ = logic_manager.compute_context_flags(record(sleep_hours_avg=5.5))
        self.assertTrue(flags_short['sleep'])

        flags_bad, _, _ = logic_manager.compute_context_flags(record(sleep_quality=2))
        self.assertTrue(flags_bad['sleep'])

    def test_finance_direction_and_no_tier_raising(self):
        flags_fin_off, _, _ = logic_manager.compute_context_flags(record(fin_stress=5))
        self.assertFalse(flags_fin_off['finances'])

        flags_fin_on, _, _ = logic_manager.compute_context_flags(record(fin_stress=4))
        self.assertTrue(flags_fin_on['finances'])

        # Context flags alone do NOT raise the tier from ok to check-in
        res = logic_manager.apply_logic({
            **record(fin_stress=1, pas_workload=5, sleep_hours_avg=4),
            'perceived_stress_score': 1.0,
            'explanation': 'You are finding things manageable right now.',
            'tips': ['sleep_routine', 'workload_chunks'],
        })
        self.assertEqual(res['soft_label'], logic_manager.TIER_OK)

    def test_optional_questions_and_mean(self):
        _, mean, count = logic_manager.compute_context_flags(record(mspss_friends=1, mspss_family=4))
        self.assertEqual(mean, 2.5)
        self.assertEqual(count, 2)

        _, mean2, count2 = logic_manager.compute_context_flags(record(mspss_friends=1, mspss_family=4, mspss_so=7))
        self.assertEqual(mean2, 4.0)
        self.assertEqual(count2, 3)

    def test_required_and_invalid_answers(self):
        for q in io_manager.QUESTIONS:
            for bad in (True, False, [], {}, float('nan'), float('inf'), q['min'] - 1, q['max'] + 1, 1.25):
                values = raw()
                values[q['key']] = bad
                self.assertIn(q['key'], io_manager.validate_student_form(values)[1])
            values = raw()
            values.pop(q['key'], None)
            self.assertEqual(io_manager.validate_student_form(values)[0], bool(q.get('optional')), q['key'])

    def test_reflection_not_scored_or_sent(self):
        r = record(feelings_text='PRIVATE REFLECTION: I feel sad and overwhelmed')
        self.assertNotIn('feelings_text', r)
        prompt = ai_manager.build_prompt(r)
        self.assertNotIn('PRIVATE REFLECTION', prompt)
        self.assertNotIn('2605581', prompt)
        self.assertNotIn('reference_score', prompt)

    def test_safety_override(self):
        for text in ('I want to kill myself', 'I feel suicidal', 'I want to die', 'I might self-harm', 'I can’t keep myself safe'):
            r = record(feelings_text=text)
            self.assertTrue(r['safety_flag'], text)
            res = logic_manager.apply_logic({
                **r,
                'perceived_stress_score': 1.0,
                'explanation': 'You are managing day to day routines.',
                'tips': ['talk_to_someone'],
            })
            self.assertEqual(res['soft_label'], logic_manager.TIER_REACH_OUT)

    def test_no_client_score_or_flag_trusted(self):
        r = record(perceived_stress_score=5.0, safety_flag=True, soft_label='Please reach out')
        self.assertFalse(r['safety_flag'])
        self.assertEqual(r['survey_version'], io_manager.VERSION)

    def test_cross_check_score_logic(self):
        # AI score differs by > 0.5: reference score is used and mismatch is logged
        res = logic_manager.apply_logic({
            **record(),  # reference score is 1.0
            'perceived_stress_score': 3.5,  # diff = 2.5 > 0.5
            'explanation': 'You are balancing coursework with your personal life.',
            'tips': ['short_breaks'],
        })
        self.assertEqual(res['score_source'], 'reference')
        self.assertTrue(res['score_mismatch'])
        self.assertEqual(res['perceived_stress_score'], 1.0)
        self.assertEqual(res['soft_label'], logic_manager.TIER_OK)


class RevisedPipelineTests(unittest.TestCase):
    setUp = frontend.CampusTests.setUp
    post = frontend.CampusTests.post

    def test_new_record_storage_and_history(self):
        self.values.update(feelings_text='SENSITIVE NOTE that must not be retained', mspss_so=7, pas_catchup=4)
        self.assertEqual(self.post().status_code, 200)
        self.assertEqual(self.post({'opt_in': True}, '/save').status_code, 200)
        stored = json.loads(self.path.read_text(encoding='utf-8'))[0]
        self.assertNotIn('feelings_text', stored)
        self.assertNotIn('SENSITIVE NOTE', self.path.read_text(encoding='utf-8'))
        self.assertEqual(self.client.get('/api/records').status_code, 401)
        login_admin(self.client)
        row = self.client.get('/api/records').json['records'][0]
        self.assertEqual(row['survey_version'], io_manager.VERSION)
        self.assertEqual(row['fin_stress'], 8)
        self.assertEqual(row['mspss_so'], 7)

    def test_safety_remains_visible_when_ai_fails(self):
        self.values['feelings_text'] = 'I want to end my life'
        self.app.config['AI_GENERATE_FN'] = lambda *args: '{}'
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.json['safety_flag'])
        self.assertIn('advisor', response.json)
        self.assertFalse(self.app.extensions['pending_checkins'])

    def test_safety_even_with_invalid_answers(self):
        response = self.post({**self.values, 'pss_1': None, 'feelings_text': 'I want to die'})
        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.json['safety_flag'])


if __name__ == '__main__':
    unittest.main()
