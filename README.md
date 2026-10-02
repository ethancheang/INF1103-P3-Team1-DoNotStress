# INF1103-P3-Team1-DoNotStress

Local Flask check-in for **students**. You answer a short form, Gemini analyses it, and the result page shows that analysis plus SIT Counselling contacts.

This checkout is the **I/O + AI** step. `logic_manager.py` and `data_manager.py` are not here yet, on purpose, so the repo history can add Logic and then Data later. Until then the result page shows the Gemini record directly, and saving is hidden.

Gemini is **required**. There is no stand-in result when the API key is missing or Gemini fails.

The web app (`app.py`) is the primary entry point. `main.py` only prints these run steps and does not import the later layers.

## Setup (Windows PowerShell)

From the project root:

```powershell
pip install -r requirements.txt
$env:GEMINI_API_KEY="your-key-here"
python app.py
```

Then open [http://127.0.0.1:5000](http://127.0.0.1:5000).

Create a key in [Google AI Studio](https://aistudio.google.com/apikey). `python app.py` stops at startup if `GEMINI_API_KEY` is missing or blank. If Gemini fails during a check-in, the app shows an AI-required error page (with official counselling contacts). It does not invent `soft_label` or tips from the form numbers alone.

macOS / Linux equivalent:

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your-key-here"
python app.py
```

Optional:

- `FLASK_SECRET_KEY` — cookie signing key (a default is used for local dev)
- `PORT` — defaults to 5000
- `FLASK_DEBUG` — defaults to on; set to `0` to turn the reloader off
- `DONOTSTRESS_DATA_PATH` — unused until `data_manager.py` is added

## What happens after submit

1. `io_manager.validate_student_form(...)` checks the form.
2. Gemini must succeed via `ai_manager.analyse_student(...)` (`google.genai` client, model `gemini-3.6-flash`). Timeouts and HTTP 429 are retried with backoff.
3. On AI failure, `io_manager.format_ai_error(...)` builds the error page.
4. On AI success, the result page uses `format_soft_label`, `format_tips`, and `format_speak_to_advisor_panel` on the Gemini record.
5. Saving stays hidden until the Data layer is added.

## What to add later

`app.py` already guards both imports. When the modules are in the tree, it calls them; you do not have to rewire the routes.

**Logic** — add `logic_manager.py` (and `tests/test_logic_manager.py`) with `apply_logic(record)` (alias `finalize_outcome` is fine). After a successful Gemini call, `app.py` will pass the enriched record in. On success return a dict with `ok=True`, `source="ai_logic"`, `ai_ok=True`, plus `soft_label`, `tips`, and `speak_prominence`. On failure return `ok=False` and do not invent an outcome from the form numbers. A missing or failed AI call must not reach Logic.

**Data** — add `data_manager.py` (and `tests/test_data_manager.py`) with `save_record(record, data_path=None, *, opt_in=False)`. When that import works, the result page shows the opt-in checkbox. `POST /save` calls `save_record(..., opt_in=True)` only if the box is ticked, and only for a successful AI-processed record. Also add `data/.gitkeep`; keep `data/student_records.json` gitignored (already listed in `.gitignore`).

## Support contacts

The Speak to advisor panel uses these official contacts only:

- Email: [SITCounselling@SingaporeTech.edu.sg](mailto:SITCounselling@SingaporeTech.edu.sg)
- Helpline: 6592 2030

## Tests

```powershell
pytest
```

Tests stub Gemini. A live API call is not required.
