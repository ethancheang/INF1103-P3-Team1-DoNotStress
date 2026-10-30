# Object-oriented I/O layer

`io_manager.py` separates three responsibilities:

- `InputValidator` validates form values using an injected survey definition. Each submission stays local to the method; reflection is checked and discarded.
- `ResultFormatter` produces the existing presentation dictionaries for labels, tips, support panels, errors, and records. It does not calculate scores or access storage.
- `ConsoleIO` composes a validator and formatter. Optional `read` and `write` callables allow console workflows to be tested without interactive input.

## Calling the classes

```python
from io_manager import InputValidator, ResultFormatter, ConsoleIO

validator = InputValidator()
formatter = ResultFormatter()
console = ConsoleIO(validator, formatter)

ok, record_or_errors = validator.validate_student_form(form_values)
```

Existing module-level functions delegate to default instances, preserving the Phase 1 API while teammates migrate their callers. Constants remain available under their existing names. The objects do not retain individual submissions.

This design uses composition and encapsulation. The refactor itself is not the new stress-history feature. A future history formatter should receive the results calculated by `TrendAnalyzer`, rather than calculate trends itself.

## Validation

Run `python -m unittest discover -s tests -v` for all tests, or `python -m unittest discover -s tests -p test_io_classes.py -v` for the class tests. The new tests cover Student ID rules, reflection limits and privacy, injected survey definitions, tip filtering, error redaction, compatibility wrappers, and console dependency injection.
