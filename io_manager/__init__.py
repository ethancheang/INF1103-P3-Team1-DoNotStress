"""DoNotStress I/O Manager (Phase 2, object-oriented).

Collects and validates user input and formats results, records, lists and
summaries. Terminal output stays separate from domain logic.

    StudentIO                 the I/O Manager: validation + student-facing wording
      '- StudentFormValidator student ID, reflection and the 11 answers
    ResultDisplay (interface) output channel for results, records, lists, summaries
      '- ConsoleResultDisplay terminal implementation

Question wording lives in the ``survey`` package. Each class lives in its own .py file.
"""

from .console_result_display import ConsoleResultDisplay
from .result_display import ResultDisplay
from .student_form_validator import StudentFormValidator
from .student_io import StudentIO

__all__ = ["ConsoleResultDisplay", "ResultDisplay", "StudentFormValidator", "StudentIO"]
