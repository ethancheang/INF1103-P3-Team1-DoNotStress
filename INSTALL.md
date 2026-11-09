# Installing DoNotStress

These steps are for Windows, in the VS Code terminal, run from this folder (the one with `main.py`). You need Python 3.12, the version the Dockerfile and CI use.

## 1. Install the packages

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If `python` is not found, use `py -m venv .venv` for the first command.

## 2. Add your Gemini API key

```powershell
Copy-Item .env.example .env
notepad .env
```

Put your key after `GEMINI_API_KEY=` with no quotes, then save. Keys come from Google AI Studio (aistudio.google.com). Never commit `.env`, and never put it in the submission zip.

## 3. Run the web app

```powershell
.\.venv\Scripts\python.exe main.py
```

Open http://127.0.0.1:5000. The admin sign-in details are in `README.md`, under "Saved check-ins and detailed results". Stop the app with Ctrl+C.

The desktop version (advanced feature) runs with:

```powershell
.\.venv\Scripts\python.exe gui.py
```

## 4. Run the tests

Either runner works and runs the same 153 tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pytest -v
```

The tests use sample AI replies and test doubles, so they need no API key and no internet connection.

**`ModuleNotFoundError: No module named 'flask'` (or `'pytest'`)** means the packages are not installed in the Python you ran. Run the `pip install` command from step 1, and start the tests with `.\.venv\Scripts\python.exe`, not plain `python`.

## Docker (optional)

```powershell
docker build -t donotstress .
docker run --rm -p 5000:5000 --env-file .env -v donotstress-data:/app/data donotstress
docker run --rm donotstress python -m pytest -v
```

The second command runs the app and keeps saved check-ins in a Docker volume called `donotstress-data`. The third runs the tests inside the container. See `DOCKER.md` for more detail.
