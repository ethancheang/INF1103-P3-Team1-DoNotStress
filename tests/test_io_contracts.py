"""OOP contracts, extensibility and privacy; no AI connection required."""
import unittest
from types import SimpleNamespace

import io_manager as io
import survey


class IOContractTests(unittest.TestCase):
    def test_abstract_contract_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            io.FieldValidator()

    def test_all_field_implementations_obey_shared_contract(self):
        cases = [
            (io.StudentIdValidator(), '2605581', 'wrong'),
            (io.ReflectionValidator(), 'hello', 123),
            (io.SurveyQuestionValidator(survey.QUESTIONS[0]), '3', 'wrong'),
        ]
        for validator, valid, invalid in cases:
            with self.subTest(validator=type(validator).__name__):
                self.assertIsInstance(validator, io.FieldValidator)
                self.assertIs(validator.validate(valid)[0], True)
                ok, error = validator.validate(invalid)
                self.assertIs(ok, False)
                self.assertIsInstance(error, str)

    def test_injected_policy_extends_form_without_changing_coordinator(self):
        class VisitingStudentId(io.FieldValidator):
            def validate(self, raw):
                return (True, raw) if raw == 'VISITOR' else (False, 'Invalid visitor ID')

        policy = VisitingStudentId()
        definition = SimpleNamespace(QUESTIONS=[], VERSION='test', safety_check=lambda text: False)
        validator = io.InputValidator(definition, student_id_validator=policy)
        self.assertEqual(validator.validate_student_form({'student_id': 'VISITOR'}),
                         (True, {'student_id': 'VISITOR', 'safety_flag': False, 'survey_version': 'test'}))
        self.assertFalse(validator.validate_student_form({'student_id': '2605581'})[0])
        self.assertTrue(policy.validate('VISITOR')[0])

    def test_questions_are_defensively_copied(self):
        validator = io.InputValidator()
        questions = validator.questions
        questions[0]['options'][0] = 'Changed'
        questions.clear()
        self.assertEqual(validator.questions, survey.QUESTIONS)

    def test_formatter_uses_injected_question_definitions(self):
        definition = SimpleNamespace(QUESTIONS=[{
            'key': 'custom', 'prompt': 'Custom question', 'min': 1, 'options': ['A', 'B'],
        }])
        formatter = io.ResultFormatter(definition)
        definition.QUESTIONS[0]['options'][1] = 'Changed'
        self.assertEqual(formatter.format_student_record({'custom': 2})['fields'],
                         [{'key': 'custom', 'label': 'Custom question', 'value': '2 · B'}])

    def test_invalid_form_returns_all_errors_and_no_reflection(self):
        ok, errors = io.InputValidator().validate_student_form({
            'student_id': 'bad', 'feelings_text': 'private' * 400,
        })
        self.assertFalse(ok)
        self.assertEqual(set(errors), {'student_id', 'feelings_text', *survey.QUESTION_MAP})
        self.assertNotIn('private', str(errors))

    def test_console_collects_same_record_as_form(self):
        values = {'student_id': '2605581', **{q['key']: '3' for q in survey.QUESTIONS},
                  'feelings_text': 'Personal reflection'}
        answers = iter(['bad', values['student_id'], *(values[q['key']] for q in survey.QUESTIONS),
                        values['feelings_text']])
        output = []
        validator = io.InputValidator()
        console = io.ConsoleIO(validator, read=lambda prompt: next(answers), write=output.append)
        record = console.collect_student_record()
        self.assertEqual(record, validator.validate_student_form(values)[1])
        self.assertNotIn('feelings_text', record)
        self.assertTrue(output[0].startswith('Error:'))


if __name__ == '__main__':
    unittest.main()
