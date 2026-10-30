"""Direct object API tests; no network calls or saved student data."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

import io_manager
import survey


class InputValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = io_manager.InputValidator()

    def test_student_id_rules(self):
        self.assertEqual(self.validator.validate_student_id(' 2605581 '), (True, '2605581'))
        for value in ('1234567', '260558', '2１２３４５６', None):
            with self.subTest(value=value):
                self.assertFalse(self.validator.validate_student_id(value)[0])

    def test_reflection_limits(self):
        self.assertTrue(self.validator.validate_feelings_text('x' * 2000)[0])
        self.assertFalse(self.validator.validate_feelings_text('x' * 2001)[0])
        self.assertFalse(self.validator.validate_feelings_text(123)[0])

    def test_form_discards_reflection_and_does_not_retain_answers(self):
        values = {q['key']: '3' for q in survey.QUESTIONS}
        values.update(student_id='2605581', sleep_hours_avg='7.5', feelings_text='Private reflection')
        ok, record = self.validator.validate_student_form(values)
        self.assertTrue(ok, record)
        self.assertNotIn('feelings_text', record)
        self.assertEqual(record['survey_version'], survey.VERSION)
        self.assertFalse(self.validator.validate_student_form({})[0])
        self.assertEqual(set(vars(self.validator)), {'_survey'})

    def test_injected_survey_is_used(self):
        definition = SimpleNamespace(QUESTIONS=[], VERSION='test', safety_check=Mock(return_value=True))
        validator = io_manager.InputValidator(definition)
        ok, record = validator.validate_student_form({'student_id': '2605581', 'feelings_text': 'example'})
        self.assertTrue(ok)
        self.assertTrue(record['safety_flag'])
        self.assertEqual(record['survey_version'], 'test')
        definition.safety_check.assert_called_once_with('example')


class ResultFormatterTests(unittest.TestCase):
    def test_unknown_and_duplicate_tips(self):
        formatter = io_manager.ResultFormatter()
        result = formatter.format_tips(['short_breaks', 'unknown', 'short_breaks'])
        self.assertEqual([item['id'] for item in result['items']], ['short_breaks'])

    def test_error_detail_does_not_expose_secret(self):
        result = io_manager.ResultFormatter().format_ai_error('timeout', 'api_key=secret')
        self.assertIsNone(result['reason'])
        self.assertNotIn('api_key=secret', result['hint'])

    def test_legacy_wrapper_matches_object_api(self):
        formatter = io_manager.ResultFormatter()
        self.assertEqual(io_manager.format_ai_error('timeout'), formatter.format_ai_error('timeout'))
        self.assertEqual(io_manager.format_student_record({}), formatter.format_student_record({}))


class ConsoleIOTests(unittest.TestCase):
    def test_retry_uses_injected_input_output_and_validator(self):
        validator = Mock()
        validator.validate_student_id.side_effect = [(False, 'Invalid ID'), (True, '2605581')]
        read = Mock(side_effect=['bad', '2605581'])
        output = []
        console = io_manager.ConsoleIO(validator=validator, read=read, write=output.append)
        self.assertEqual(console.get_student_id(), '2605581')
        self.assertEqual(read.call_count, 2)
        self.assertEqual(output, ['Error: Invalid ID'])

    def test_display_delegates_to_injected_formatter(self):
        formatter = Mock()
        formatter.format_student_record.return_value = {
            'heading': 'Example', 'fields': [{'label': 'Sleep', 'value': '7.5'}]}
        output = []
        console = io_manager.ConsoleIO(formatter=formatter, write=output.append)
        record = {'sleep_hours_avg': 7.5}
        console.display_record(record)
        formatter.format_student_record.assert_called_once_with(record)
        self.assertEqual(output, ['Example', '  Sleep: 7.5'])


if __name__ == '__main__':
    unittest.main()
