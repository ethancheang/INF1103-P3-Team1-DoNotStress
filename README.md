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
| 8 | `GeminiProvider` | `ai/gemini_provider.py` | Live Gemini implementation with ordered `MODEL_CHAIN` fallback. |
| 9 | `LogicManager` | `logic_manager.py` | Scoring, `instructions()`, `verify()` (tier, scored_items, 0.01 tolerance), rules, trend. |
| 10 | `BusinessRule` | `logic/business_rule.py` | Abstract class (`ABC`): `name`, `applies`, `apply`, plus shared concrete `run()`. |
| 11 | `SafetyOverrideRule` | `logic/safety_override_rule.py` | Safety flag forces High / "Please reach out" and leads with "talk to someone". |
| 12 | `SupportPriorityRule` | `logic/support_priority_rule.py` | High tier and low social support puts talking first. |
| 13 | `ContextFlagRule` | `logic/context_flag_rule.py` | Sleep, workload, money and support flags each suggest a tip. |
| 14 | `Decision` | `logic/decision.py` | Encapsulated outcome. Strips the reflection. Rules use `raise_tier()` / `mark_support_priority()` / `lead_with()` / `suggest()`; `finalise_tips()` caps at four. |
| 15 | `DataManager` | `data_manager.py` | Saves (`save_checkin`, `save_pending`) and queries records. Constructs and owns `JSONStorage`. |
| 16 | `Record` | `records/record.py` | Abstract saved row. Reflection is never stored; `problem()` enforces shared checks (`student_id`, `survey_version`). |
| 17 | `CheckInRecord` | `records/check_in_record.py` | A finished, AI-processed check-in. `problem()` validates parent checks plus AI fields and `stress_score`. |
| 18 | `PendingRecord` | `records/pending_record.py` | Answers kept when Gemini fails or the score is rejected. No score. |
| 19 | `JSONStorage` | `json_storage.py` | Thread-safe JSON read/write with one `RLock`, write-time corrupt-file backup and atomic replace. |

## OOP concept map

| Concept | Where it is evidenced |
|---|---|
| Encapsulation | Private attributes (`__`) and properties on every manager, on `Decision` (read-only properties; intent methods `raise_tier()` / `mark_support_priority()`, `finalise_tips()`), on `Record` (reflection stripped, deep-copied reads), and on `Questionnaire` (callers get copies of question dicts). |
| Abstract class (ABC) | `BaseManager` (shared parent of the four managers), `BusinessRule` (shared `run()` around abstract `applies`/`apply`), and `Record` (shared `problem()` contract). All use solid inheritance arrows. |
| Inheritance | `IOManager`, `AIManager`, `LogicManager`, `DataManager` inherit `BaseManager`. `SafetyOverrideRule`, `SupportPriorityRule`, `ContextFlagRule` inherit `BusinessRule`. `CheckInRecord` and `PendingRecord` inherit `Record`. |
| Interface | `AIProvider` (`GeminiProvider` implements it; `FakeProvider` in `tests/` is a second implementor). |
| Composition | `App` creates and owns the four managers. `DataManager(path)` constructs `JSONStorage`. `LogicManager` creates its three `BusinessRule` instances. |
| Aggregation | `IOManager` and `AIManager` are each handed the same `Questionnaire` instance, which can exist on its own. `AIManager` is handed an `AIProvider`. |
| Association | `WebController` owns `Flask` and uses `App` through use-case methods only (`validate_form`, `submit_checkin`, `job_status`, `student_history`, `admin_records`, …). `LogicManager` and each `BusinessRule` use `Decision`. `DataManager` uses `Record`. |
| Polymorphism | `LogicManager.evaluate()` loops over a list of `BusinessRule`. `DataManager` saves and loads `Record` subclasses the same way. `AIManager` calls any `AIProvider`. |
| SRP | `WebController` is the HTTP boundary (requests, sessions, cookies); `App` is the use-case coordinator and composition root; each manager owns one layer (I/O, AI, Logic, Data). Wording tables and scoring constants are module-level data, not extra classes. |
| OCP | A new policy is a new `BusinessRule` subclass; `evaluate()` does not change (and `lead_with()` keeps the first rule's lead slot so safety cannot be displaced). A new provider is a new `AIProvider`; `AIManager` does not change. |
| LSP | `PendingRecord.score` is always `None` and `PendingRecord.problem()` inherits `Record`'s shared identity/version checks, while `CheckInRecord.problem()` adds AI field validation. Both go through `DataManager.save()`. |

## Requirements

- Python 3.12 or newer
- Dependencies in `requirements.txt`
- A `GEMINI_API_KEY` for live Gemini calls

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

## Admin sign-in configuration

Admin sign-in is disabled unless `ADMIN_PASSWORD_HASH` is set in the environment
(e.g., via `werkzeug.security.generate_password_hash(...)`). Never hardcode or
commit password hashes in source control.

## Configuration

- `GEMINI_API_KEY`: live provider credential. Never commit it.
- `ADMIN_PASSWORD_HASH`: Werkzeug password hash for admin login at `/admin/login`.
- `FLASK_SECRET_KEY`: stable Flask session signing secret. If it is unset the
  app still starts, with a random key and a logged warning. Every restart then
  signs everyone out and resets each device's history access, because the
  history cookie is signed with this key. Set it for any real deployment.
- `GEMINI_MODEL`: optional model to try first. If it fails, the app falls back
  through its model chain.
- `GEMINI_MODEL_CHAIN`: optional comma-separated model list replacing the
  default fallback chain.
- `SESSION_COOKIE_SECURE`: set to `1` behind HTTPS.
- `DONOTSTRESS_DATA_PATH`: optional JSON storage path.
- `HOST`: Flask bind address, default `127.0.0.1`. Use `0.0.0.0` in Docker.
- `PORT`: local Flask port, default `5000`.
- `FLASK_DEBUG`: enable Flask debug mode only for local development.

## Runtime safeguards

- The application sends a constructed string prompt to `AIManager`. The
  prompt includes Logic's `instructions()`, and each reply is checked
  with Logic's `verify()` (tier, scored_items, 0.01 tolerance) inside
  the retry loop (bounded by an overall 45 s deadline).
- Check-ins run on a worker thread and the browser polls the job until
  completion (202, then the finished response). Job dicts hold a
  `threading.Event` used by long-poll waits (`?wait=...`) and test sync.
- Job IDs are bound to `session["owner_id"]` and cannot be polled from
  another session; each owner is capped at 2 concurrent running jobs.
- Duplicate active submissions from the same session and answer
  fingerprint reuse the existing job.
- `App.close()` cancels queued futures, waits for running workers, and
  is invoked automatically in a `finally:` block on server shutdown.
- Student history uses an HMAC-signed cookie holding record digests (up
  to 24 check-ins made on that browser), never raw student IDs. A
  browser sees only the check-ins made on it; anyone can still submit
  under any ID because IDs are not authenticated, and admins can inspect
  all records. `history_for()` loads the file and filters in memory.
- `App` keeps a save lock around matching a pending row and saving, so
  a retry upgrades the same row in place.
- Start the app with `python main.py`. The `if __name__ == "__main__":`
  block builds `WebController(App())` and reads `HOST` from the
  environment (default `127.0.0.1`). `App` never imports `Flask`.

## New user feature and advanced feature

- New user feature: the student history and trend page (`/history`,
  `/api/history`), unlocked per record by a signed cookie after a
  check-in on this browser.
- Advanced feature: `App.submit_checkin()` runs Gemini on a worker
  thread; the request returns 202 and the browser polls
  `/checkin/status/<job_id>`.

## Live model check

The default model chain lives on `GeminiProvider.MODEL_CHAIN` in
`ai/gemini_provider.py`. Verify it against the installed Google GenAI
SDK and the account before deployment.
