# DoNotStress trimmed 19-class app

A standalone Flask student check-in app. Nineteen production classes
cover every required OOP concept, under a cap of 20. The test double
`FakeProvider` lives in `tests/` and is not counted.

## The 19 classes

| # | Class | File | Responsibility |
|---|---|---|---|
| 1 | `App` | `main.py` | Composition root: creates and owns the four managers and wires them together. Does not import `WebController`. |
| 2 | `BaseManager` | `base_manager.py` | Abstract parent of the four managers: name, logger, `describe()`, `health()`. |
| 3 | `WebController` | `web_controller.py` | Flask routes only. Calls App use-case methods. Never builds a `CheckInRecord` or reaches into `app.io` / `app.jobs`. |
| 4 | `IOManager` | `io_manager.py` | Validates the student form and shapes every page. |
| 5 | `Questionnaire` | `questionnaire.py` | Questions, sections, `validate_answer()`, `option_label()`, and `safety_fired()`. Built with `from_survey()`. |
| 6 | `AIManager` | `ai_manager.py` | Prompt, provider call, parse, validate. Receives `instructions` and `verify` from Logic. |
| 7 | `AIProvider` | `ai/ai_provider.py` | Interface: `name`, `models`, `is_ready`, `generate`, `redact`. |
| 8 | `GeminiProvider` | `ai/gemini_provider.py` | Live Gemini implementation. The model chain is data in `ai/model_chain.py`. |
| 9 | `LogicManager` | `logic_manager.py` | Scoring, `instructions()`, `verify()` (tier, scored_items, 0.01 tolerance), rules, trend. |
| 10 | `BusinessRule` | `logic/business_rule.py` | Interface: `name`, `applies`, `apply`, plus a shared `run()`. |
| 11 | `SafetyOverrideRule` | `logic/safety_override_rule.py` | Safety flag forces High / "Please reach out" and leads with "talk to someone". |
| 12 | `SupportPriorityRule` | `logic/support_priority_rule.py` | High tier and low social support puts talking first. |
| 13 | `ContextFlagRule` | `logic/context_flag_rule.py` | Sleep, workload, money and support flags each suggest a tip. |
| 14 | `Decision` | `logic/decision.py` | Encapsulated outcome. Strips the reflection. Rules use `lead_with` / `suggest`; `finalise_tips()` caps at four. |
| 15 | `DataManager` | `data_manager.py` | Saves, loads and queries records. Constructs and owns `JSONStorage`. |
| 16 | `Record` | `records/record.py` | Abstract saved row. Reflection is never stored. |
| 17 | `CheckInRecord` | `records/check_in_record.py` | A finished, AI-processed check-in. `problem()` says whether it may be saved. |
| 18 | `PendingRecord` | `records/pending_record.py` | Answers kept when Gemini fails or the score is rejected. No score. |
| 19 | `JSONStorage` | `json_storage.py` | Thread-safe JSON read/write with one `RLock`, corrupt-file backup and atomic replace. |

## OOP concept map

| Concept | Where it is evidenced |
|---|---|
| Encapsulation | Private attributes (`__`) and properties on every manager, on `Decision` (no public `tips` setter; `finalise_tips()` is the only way the tip list is finished), on `Record` (reflection stripped), and on `Questionnaire` (callers get copies of question dicts). |
| Abstract class (ABC) | `BaseManager` (shared parent of the four managers) and `Record` (shared parent of the two record kinds). Both use a solid inheritance relationship. |
| Inheritance | `IOManager`, `AIManager`, `LogicManager`, `DataManager` inherit `BaseManager`. `CheckInRecord` and `PendingRecord` inherit `Record`. |
| Interface | `AIProvider` (`GeminiProvider` implements it; `FakeProvider` in `tests/` is a second implementor) and `BusinessRule` (three policy rules). |
| Composition | `App` creates and owns the four managers. `DataManager(path)` constructs `JSONStorage`. `LogicManager` creates its three `BusinessRule` instances. |
| Aggregation | `IOManager` and `AIManager` are each handed the same `Questionnaire` instance, which can exist on its own. `AIManager` is handed an `AIProvider`. |
| Association | `WebController` uses `App` through use-case methods only (`validate_form`, `submit_checkin`, `job_status`, `student_history`, `admin_records`, …). `LogicManager` and each `BusinessRule` use `Decision`. `DataManager` uses `Record`. |
| Polymorphism | `LogicManager.evaluate()` loops over a list of `BusinessRule`. `DataManager` saves and loads `Record` subclasses the same way. `AIManager` calls any `AIProvider`. |
| SRP | Each manager is one layer (I/O, AI, Logic, Data). Private methods are steps inside that layer. Wording tables and scoring constants are module-level data, not extra classes. |
| OCP | A new policy is a new `BusinessRule` subclass; `evaluate()` does not change. A new provider is a new `AIProvider`; `AIManager` does not change. |
| LSP | `PendingRecord.score` is always `None` and `problem()` is always `None`, which is what the `Record` contract promises for a row with no verified score. Both record kinds can be saved, listed and queried through the same `DataManager` methods. |

## Requirements

- Python 3.12 or newer
- Dependencies in `requirements.txt`
- A `GEMINI_API_KEY` for live Gemini calls
- Optional `GEMINI_MODEL_CHAIN`, as a comma-separated list of model names
  supported by the installed Google GenAI SDK and deployment account

## Run locally

From this folder:

```powershell
Copy-Item .env.example .env
# Edit .env and set GEMINI_API_KEY=<your_gemini_api_key>
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p "test_*.py" -v
python main.py
```

Open `http://127.0.0.1:5000`. The application uses top-level imports such as
`from main import App`, so run commands with this folder as the current working
directory. The folder is a standalone Flask application, not a dotted Python
package.

## Run with Docker (Build, Run, and Test)

The repository root includes a `Dockerfile` (`python:3.12-slim`) that runs the
application and automated test suite without installing Python dependencies on
the host machine.

### 1. Build the Docker image

```powershell
docker build -t donotstress .
```

### 2. Run the automated test suite inside the container (no live API key needed)

```powershell
docker run --rm -e GEMINI_API_KEY="" donotstress python -m unittest discover -s tests -p "test_*.py" -v
```

### 3. Run the web application in a container

Pass your `GEMINI_API_KEY` via `--env-file .env` or `-e GEMINI_API_KEY=...`
(never bake API keys into the image):

```powershell
docker run --rm -p 5000:5000 --env-file .env donotstress
```

Or with an explicit `-e` flag and a persistent volume for saved student records:

```powershell
docker run --rm -p 5000:5000 -e GEMINI_API_KEY="your_api_key_here" -v "${PWD}/data:/app/data" donotstress
```

Then open `http://127.0.0.1:5000` in your browser.

## Continuous Integration (CI)

GitHub Actions workflow `.github/workflows/tests.yml` runs automatically on
every `push` and `pull_request` to `main`:

1. **`test` job (`ubuntu-latest`, Python 3.12):** Installs `requirements.txt`
   and runs `python -m unittest discover -s tests -p "test_*.py" -v` offline
   (`GEMINI_API_KEY=""`) using `FakeProvider`.
2. **`docker` job (`ubuntu-latest`):** Builds the production `Dockerfile` image
   (`docker build -t donotstress .`) and executes the full automated test suite
   inside the container (`docker run --rm -e GEMINI_API_KEY="" donotstress python -m unittest discover -s tests -p "test_*.py" -v`).

## Admin demo credentials

To inspect saved check-ins at `/records` (or `/admin/login`), sign in with the
coursework demo account:

- **Username:** `admin`
- **Password:** `DoNotStress2026!`

## Configuration

- `GEMINI_API_KEY`: live provider credential. Never commit it.
- `GEMINI_MODEL_CHAIN`: optional comma-separated model fallback chain.
- `FLASK_SECRET_KEY`: stable Flask session signing secret for deployment.
- `DONOTSTRESS_DATA_PATH`: optional JSON storage path.
- `HOST`: Flask bind address, default `127.0.0.1`. Use `0.0.0.0` in Docker.
- `PORT`: local Flask port, default `5000`.
- `FLASK_DEBUG`: enable Flask debug mode only for local development.

## Runtime safeguards

- The application sends a constructed string prompt to `AIManager`. The
  prompt includes Logic's `instructions()`, and each reply is checked
  with Logic's `verify()` (tier, scored_items, 0.01 tolerance) inside
  the retry loop.
- Check-ins run on a worker thread and the browser polls the job until
  completion (202, then the finished response). Job dicts hold a
  `threading.Event`.
- Job IDs cannot be polled from another session.
- Duplicate active submissions from the same session and answer
  fingerprint reuse the existing job.
- `App.close()` closes the worker executor for tests, reloads, and
  graceful deployment shutdown.
- Student history uses an HMAC-signed cookie (digests, never the raw ID)
  and the protected `/api/history` endpoint. A student sees only their
  own rows. `history_for()` loads the file and filters in memory.
- `App` keeps a save lock around matching a pending row and saving, so
  a retry upgrades the same row in place.
- Start the app with `python main.py`. The `if __name__ == "__main__":`
  block builds `WebController(App(...))` and reads `HOST` from the
  environment (default `127.0.0.1`). Tests build the app the same way
  with the constructors. The module does not construct a live `App` at
  import time, and there is no leftover `create_app()` factory.

## New user feature and advanced feature

- New user feature: the student history and trend page (`/history`,
  `/api/history`), unlocked by a signed cookie after a check-in on this
  browser.
- Advanced feature: `App.submit_checkin()` runs Gemini on a worker
  thread; the request returns 202 and the browser polls
  `/checkin/status/<job_id>`.

## Live model check

The default model chain is a source configuration value in
`ai/model_chain.py`. Verify it against the installed Google GenAI SDK
and the account before deployment, or set `GEMINI_MODEL_CHAIN` to a
supported chain.
