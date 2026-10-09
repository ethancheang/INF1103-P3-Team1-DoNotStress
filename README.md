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

## Evidence questionnaire v2

The questionnaire follows section 2 of `donotstress_question_evidence.docx` (9 October 2026).
`survey.py` owns question wording, options, chapter explanations and deterministic scoring.
The browser receives the same definitions from Flask. Required answers start unselected.

1. **Your month:** Student ID (seven ASCII digits beginning with 2), then all four PSS-4 items, 0–4 frequency, recall last month.
2. **Rest and recovery:** typical actual sleep in the past week, 0–14 hours in 0.5 steps; sleep quality 0 (very good) to 3 (very bad).
3. **Study demands:** PAS workload item, 1–5 agreement; optional catch-up item. Direction is adapted.
4. **Money pressures:** IFDFW item 8, 1 (overwhelming stress) to 10 (no stress). Higher means LESS distress. Intermediate original anchor placements are approximate.
5. **Your support:** MSPSS friends and family items, 1–7 agreement; optional special-person item.
6. **Reflection:** optional text, up to 2,000 characters; not scored, sent to Gemini, or saved.

Ten core questions, two optional contextual items, plus optional reflection. ID is not scored.

### Scoring and interpretation

- PSS-4 = `pss_1 + (4 - pss_2) + (4 - pss_3) + pss_4`, range 0–16.
- Team guidance bands: 0–7 Low, 8–11 Moderate, 12–16 High. These are NOT official PSS cut-offs or a diagnosis.
- Context flags: sleep <6 hours OR quality >=2; workload >=4; finance <=4; mean of answered support items <3.
- At least two context flags lift Low to Moderate. They never produce High by themselves and never reduce an existing band.
- Optional catch-up adds context only. Optional special-person answer contributes to the support mean if answered; missing optional responses are never replaced with zero.
- A basic local crisis-language check highlights “Please reach out” and support contacts without changing PSS total. It can miss language or produce false positives; it is not a safety assessment and no person monitors reflections.
- `risk_score` is retained for backend compatibility as PSS total /16, NOT a probability. AI cannot replace the computed band. Tips combine relevant context suggestions with validated AI tip IDs.

Sleep items are adapted; PAS and MSPSS are selected items, not complete scales. The combined questionnaire and its guidance bands have not been clinically validated. Each result explains its factors and the project rules.

### Sources and permissions

- PSS-4: Cohen, Kamarck & Mermelstein (1983), https://doi.org/10.2307/2136404. Reverse coding verified at https://www.cmu.edu/dietrich/psychology/stress-immunity-disease-lab/scales/html/pssscoring.html.
- Sleep: adapted from PSQI, Buysse et al. (1989), https://doi.org/10.1016/0165-1781(89)90047-4; recall shortened to one week. This is not a PSQI score.
- PAS: Bedewy & Gabriel (2015), https://doi.org/10.1177/2055102915596714, CC BY-NC 3.0; response direction adapted to increasing agreement.
- IFDFW: Prawitz et al. (2006), https://www.afcpe.org/wp-content/uploads/2018/10/vol1714.pdf.
- MSPSS: Zimet et al. (1988), https://doi.org/10.1207/s15327752jpa5201_2.

The supplied brief identifies permissions to resolve before distribution: PSS permission through Mapi/ePROVIDE and the copyrighted IFDFW wording. PSQI educational/research use is non-commercial; adaptations and commercial use need appropriate review. Attribution does not itself grant permission. No permission request has been sent by this implementation.

Support contacts are always available, including without an AI result: SIT Counselling, SOS **1767**, national mindline **1771**. The latter two are 24-hour services, verified 9 October 2026 at https://www.sos.org.sg/contact-us/ and https://www.moh.gov.sg/newsroom/national-mindline-1771-to-provide--round-the-clock-support-for-mental-health/.

## Flow and storage

`main.py` validates with `io_manager`, runs `ai_manager.analyse_student`, then `logic_manager.apply_logic`. Student-facing results and tips use the I/O formatters. Support contacts come from the existing I/O module. Assessment is AI-assisted wellbeing guidance, not a medical diagnosis.

The browser explains that numeric questionnaire answers and computed context are sent to Gemini before submission. Student ID and reflection are excluded. The server checks reflection text then discards it; only the boolean safety flag remains in a result. Request bodies must not be logged by a deployment proxy. Results are temporarily held in server memory for up to 30 minutes; expired entries are removed on the next request. Session cookies contain only opaque identifiers and a CSRF token, not answers. Restarting the server or starting fresh clears access to unsaved results. The garden is a session-level completion reward, not persistent account history.

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

## Saved check-ins and detailed results

The default is **Student view**. Students can complete a check-in, view their own current result and opt in to saving. They cannot open the saved-records table or fetch its data.

Use **Admin sign in** (or `/admin/login`) with the fixed coursework account:

- Username: `admin`
- Password: `DoNotStress2026!`

The credential check runs on the server; `main.py` contains a password hash. Credentials are not embedded in the login page, JavaScript or browser configuration. This shared, documented demo account is for the local prototype, not public deployment with real student records.

Successful sign-in opens **Saved records**. `/records` redirects unauthenticated users to sign-in, and `/api/records` returns 401 before loading any records. Admin access expires after 30 minutes. **Sign out** revokes the server-side admin token, clears the current browser session, and returns to Student view. Restarting the app revokes admin sessions. Five failed sign-in attempts within five minutes temporarily block further attempts from that address.

Admins can search any part of a Student ID and combine the Low/Moderate/High risk and cohort-year filters. Clear Filters restores the full list. Cohort year uses the first two ID digits (26 means 2026); dates display in Singapore time. Only records saved through opt-in are shown; unsaved results stay out of the table. Load errors are distinguished from an empty result. The history endpoint omits free-text concerns and AI reasoning.

Results include the PSS-4 total, an explanation of the computed guidance band, and four factor cards. Colours accompany Low/Moderate/High text. New records carry `survey_version: evidence-v2`; legacy records remain unchanged and are explicitly labelled with their old scales and finance direction. They are not converted to PSS scores or directly comparable with the revised questionnaire.
