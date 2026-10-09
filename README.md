# INF1103-P3-Team1-DoNotStress

Student wellbeing app with a campus check-in UI and the team's AI/backend pipeline.

## Run locally

Open this project folder in the VS Code terminal:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

Open http://127.0.0.1:5000. If only the Python launcher is available, use `py -m venv .venv` for the first command.

`main.py` is the single entry point for the frontend and backend. For Flask CLI or WSGI tools, use `main:app`, for example:

```powershell
.\.venv\Scripts\python.exe -m flask --app main run
```

## AI configuration

Set `GEMINI_API_KEY` in your local environment or a local `.env` file before starting. A stable `FLASK_SECRET_KEY` is recommended; otherwise each restart generates a fresh key and expires sessions. `PORT` changes the default port. `DONOTSTRESS_DATA_PATH` optionally changes the save-file location.

Do not commit `.env`, API keys, saved student data, or Python cache files. No API key is embedded in the frontend.

The interface opens without a key, but assessment requires Gemini. Missing credentials, provider errors, or invalid responses show a retry message and support contacts; there is no fabricated sample result or Logic-only fallback.

## Current check-in fields

The UI follows `io_manager.FORM_FIELDS`:

- Student ID: seven digits, starting with 23, 24, 25, or 26.
- Sleep: 0–24 hours, in half-hour steps.
- Stress, academic workload, financial stress, social support: 1–10 sliders.
- Feelings text: optional.

The previous submission-rate, CCA-count, absence-count, and yes/no financial-stress fields are no longer collected because the merged I/O and AI modules use the contract above.

## Flow and storage

`main.py` validates with `io_manager`, runs `ai_manager.analyse_student`, then `logic_manager.apply_logic`. Student-facing results and tips use the I/O formatters. Support contacts come from the existing I/O module. Assessment is AI-assisted wellbeing guidance, not a medical diagnosis.

The browser explains that answers are sent to Gemini before submission. Results are temporarily held in server memory for up to 30 minutes; expired entries are removed on the next request. Session cookies contain only opaque identifiers and a CSRF token, not answers. Restarting the server or starting fresh clears access to unsaved results. The garden is a session-level completion reward, not persistent account history.

Saving is optional and requires the checkbox. `/save` calls `data_manager.save_record` only for an AI-processed result with explicit consent. The default file is `data/student_records.json`. Repeating Save for the same pending result does not create another copy.

This is a single-process local app. A production deployment needs a shared server-side session/record store, authentication and access controls appropriate to student records, and a production server.

## Files

- `main.py`: combined Flask entry point and orchestration.
- `io_manager.py`, `ai_manager.py`, `logic_manager.py`, `data_manager.py`: existing team layers.
- `templates/base.html`, `templates/checkin.html`: page shell.
- `static/style.css`, `static/campus.js`: campus UI, sliders, review, results, garden, and opt-in saving.
- Legacy result/error templates remain available; the current interface renders these states in the shared campus UI.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Tests inject a simulated Gemini response but run the real schema validator, Logic finalizer, I/O formatters, and data saver. They make no network calls and only save synthetic test data in a temporary directory.
