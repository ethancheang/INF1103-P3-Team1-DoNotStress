"""Behavior of the I/O form model and its handoff to other managers."""
import unittest
from types import SimpleNamespace

import io_manager as io
import survey


class FormObjectTests(unittest.TestCase):
    def test_result_owns_record_and_exports_defensive_copies(self):
        source = {'student_id': '2605581', 'nested': {'value': 1},
                  'feelings_text': 'private reflection'}
        result = io.FormValidationResult(record=source)
        source['nested']['value'] = 2
        exported = result.to_record()
        self.assertEqual(exported['nested']['value'], 1)
        self.assertNotIn('feelings_text', exported)
        exported['nested']['value'] = 3
        self.assertEqual(result.to_record()['nested']['value'], 1)
        self.assertEqual(result.errors, {})

    def test_failed_result_cannot_enter_record_pipeline(self):
        errors = {'student_id': 'Invalid ID'}
        result = io.FormValidationResult(errors=errors)
        errors.clear()
        result.errors.clear()
        self.assertFalse(result.is_valid)
        self.assertEqual(result.errors, {'student_id': 'Invalid ID'})
        with self.assertRaises(ValueError):
            result.to_record()

    def test_result_rejects_ambiguous_outcomes(self):
        for kwargs in ({}, {'record': {}, 'errors': {'id': 'bad'}}, {'errors': {}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                io.FormValidationResult(**kwargs)

    def test_form_field_reuses_an_independent_validator(self):
        policy = io.StudentIdValidator()
        field = io.FormField('student_id', policy)
        self.assertEqual(field.validate_from({'student_id': ' 2605581 '}), (True, '2605581'))
        self.assertFalse(field.validate_from(None)[0])
        self.assertTrue(policy.validate('2605581')[0])
        with self.assertRaises(AttributeError):
            field.key = 'different'

    def test_form_schema_snapshot_is_consistent_after_source_changes(self):
        definition = SimpleNamespace(
            QUESTIONS=[dict(survey.QUESTIONS[0])], VERSION='test',
            validate_question=survey.validate_question, safety_check=lambda text: False,
        )
        validator = io.InputValidator(definition)
        definition.QUESTIONS[0]['key'] = 'changed'
        result = validator.validate_form({'student_id': '2605581', 'pss_1': '3'})
        self.assertTrue(result.is_valid)
        self.assertEqual(result.to_record()['pss_1'], 3)
        self.assertEqual(validator.questions[0]['key'], 'pss_1')

    def test_result_and_legacy_api_agree_and_do_not_leak_between_submissions(self):
        validator = io.InputValidator()
        values = {'student_id': '2605581', **{q['key']: '3' for q in survey.QUESTIONS},
                  'feelings_text': 'private'}
        result = validator.validate_form(values)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.as_legacy_tuple(), validator.validate_student_form(values))
        self.assertNotIn('feelings_text', result.to_record())
        failed = validator.validate_form({})
        self.assertFalse(failed.is_valid)
        self.assertEqual(failed.as_legacy_tuple(), validator.validate_student_form({}))
        self.assertTrue(result.is_valid)


if __name__ == '__main__':
    unittest.main()
