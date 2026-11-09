# Running DoNotStress in Docker

The Dockerfile is in the project root. Building the image installs Python 3.12 and every package the app and the tests need (including pytest), so the machine running it needs only Docker. Python does not have to be installed.

Every command below is one line and works unchanged in Windows PowerShell and in a macOS or Linux terminal. On Windows, use PowerShell rather than the old Command Prompt.

## 1. Check that Docker is running

```
docker --version
docker info
```

If `docker info` reports `Cannot connect to the Docker daemon` or `error during connect`, start Docker Desktop, wait until it shows that Docker is running, then try again.

## 2. Go to the project folder

`cd` into the folder that contains the `Dockerfile`, then confirm you are in the right place:

```
ls Dockerfile
```

If you unzipped a download on Windows, "Extract All" may have put the project one folder deeper, inside a folder with the same name. `cd` into the inner folder.

## 3. Build the image

```
docker build -t donotstress .
```

The first build downloads Python 3.12 and the packages, so it needs an internet connection and takes a few minutes. Later builds reuse the cache. Rebuild whenever the code changes.

## 4. Run the tests in the container

```
docker run --rm donotstress python -m pytest -v
```

All 153 tests use sample AI replies and test doubles, so they need no Gemini API key and no network. CI (`.github/workflows/tests.yml`) runs the same tests on every push and pull request: once on Python 3.12 and once inside this image.

## 5. Create `.env` once

```
cp .env.example .env
```

Open `.env` in a text editor (on Windows: `notepad .env`), put your own key after `GEMINI_API_KEY=` with no quotes or spaces, and save. Keys come from Google AI Studio (aistudio.google.com). `.env` stays on your machine: it is never copied into the image, and it must never be committed, put in a zip or written into a document.

## 6. Run the web app

```
docker run --rm --name donotstress -p 5000:5000 --env-file .env -v donotstress-data:/app/data donotstress
```

Leave this window open. When the log shows `Running on`, open http://127.0.0.1:5000. In another window, `docker ps` shows the container as `(healthy)` once the app answers.

If port 5000 is already in use (on macOS, AirPlay Receiver uses it), publish the app on port 8080 instead:

```
docker run --rm --name donotstress -p 8080:5000 --env-file .env -v donotstress-data:/app/data donotstress
```

Then open http://127.0.0.1:8080. The log still says 5000, which is the port inside the container.

## 7. Use the app

- **Student check-in:** on the home page, enter a 7-digit student ID that starts with 2 (for example `2123456`), answer the questions and submit. The student ID is never sent to the AI.
- **Admin:** choose **Admin sign in** (or open `/admin/login`) and use the coursework account: username `admin`, password `DoNotStress2026!`. You land on **Saved records** (`/records`), which lists saved check-ins with the cohort summary.

## 8. Stop, and start again later

Press `Ctrl+C` in the window running the app, or run `docker stop donotstress` from another window. Saved check-ins stay in the Docker volume `donotstress-data`.

To start again later, `cd` into the project folder and run the step 6 command. Rebuild (step 3) only if the code changed.

To start with an empty records table, for example before a demo, stop the app and run:

```
docker volume rm donotstress-data
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes, for live AI | Gemini API key from Google AI Studio. Not needed for tests. |
| `FLASK_SECRET_KEY` | Recommended | Session secret. If empty, a random key is generated at each start, so sign-ins end when the container restarts. |
| `DONOTSTRESS_DATA_PATH` | No | Override path for the records file (default `data/student_records.json`, inside the `/app/data` volume). |

**Do not commit `.env` or any file containing a real API key, and do not put `.env` in the submission zip.**

## If something fails

| Problem | What to do |
|---------|------------|
| `Cannot connect to the Docker daemon` or `error during connect` | Start Docker Desktop and wait until it is running. |
| `failed to read dockerfile` | You are in the wrong folder. `cd` into the folder that contains `Dockerfile` (step 2). |
| An `open .env` error when starting the app | Create `.env` in the project folder (step 5). |
| `port is already allocated` or `ports are not available` | Use `-p 8080:5000` and open port 8080. |
| `The container name "/donotstress" is already in use` | An earlier copy is still running, often after its window was closed. Run `docker stop donotstress`, then start again. |
| Check-in says "We could not complete your check-in right now" | The answers are kept, but the AI could not be reached. Check that `.env` holds a valid `GEMINI_API_KEY` and that the machine is online, then stop and start the app. |
| Admin sign-in fails | Use the account in step 7. If the page has expired, reload it. After five failed attempts, wait five minutes. |
| Saved check-ins disappeared | Always start the app with `-v donotstress-data:/app/data`. |

## Notes

- Saved check-ins persist in the Docker volume `donotstress-data`, so they survive container restarts and image rebuilds.
- The app listens on `0.0.0.0:5000` inside the container and runs as a non-root user (`appuser`). Only `/app/data` is writable.
- `.dockerignore` keeps `.env`, the local `.venv`, saved records, caches, Git data and stray documents (PDFs, zips) out of the image.
- Run one container at a time: admin sign-ins and the student's current result are kept in that container's memory.
- The app is served by Flask's built-in server, so the log line `WARNING: This is a development server` is expected. That is fine for a demo or assessment. A public deployment would also need a production WSGI server, a fixed `FLASK_SECRET_KEY`, and a new admin password in place of the shared coursework account.
