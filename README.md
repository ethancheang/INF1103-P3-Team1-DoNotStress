# INF1103-P3-Team1-DoNotStress

Repository for the INF1103 team project DoNotStress.

## Run the campus frontend

In the VS Code terminal, with this project folder open:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000. No API key is needed for this frontend demo.
If `python` is unavailable but the Python launcher is installed, use `py -m venv .venv` for the first command.

## What is implemented

- Responsive overview, four-chapter check-in, answer review, sample plan, and garden.
- Stress slider with whole-number values from 1 to 10.
- All eight input fields from `io_manager.py`; its validators are the server's source of truth.
- Sleep and submission-rate sliders plus exact numeric entry. Counts accept nonnegative whole numbers; financial stress is yes/no; free text is optional.
- Completion grows a plant regardless of the answers. No streak penalties or stress-based rewards.
- Submission errors preserve answers in the open page and allow retrying.

## Demo boundary

Results and next steps are illustrative, not calculated assessments. `ai_manager.py` currently uses a different field contract and is deliberately not called by this frontend demo. Align that contract and add assessment handling in `submit_checkin` before enabling real results.

Answers are sent to Flask for validation and are not saved to a database, file, or session cookie. The browser holds the current answers in memory until reload. The signed session cookie contains only a CSRF token and completion flag. Garden progress and chosen next steps are demo UI states, not a persistent account. No external fonts, analytics, or AI requests are used.

Support contacts are placeholders with no outgoing calls or messages. Configure verified campus details before launch. This is a local development app; use an appropriate deployment server and set a stable `FLASK_SECRET_KEY` before deployment.

## Files

- `app.py`: Flask routes and canonical field validation.
- `templates/base.html`, `templates/checkin.html`: page shell and initial configuration.
- `static/style.css`, `static/campus.js`: approved design and interactive journey.
- The old result/error templates are retained but are not used by the new flow; the result screen renders through the shared campus UI.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests cover input validation, boundaries, optional text, CSRF protection, result access, and exclusion of student answers from session data.
