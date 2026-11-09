# DoNotStress - Phase 2
# Same Python version as the CI workflow (.github/workflows/tests.yml).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTEST_ADDOPTS="-p no:cacheprovider"

WORKDIR /app

# Install the pinned dependencies first (cached layer). pytest is included,
# so the assessor can run the tests in the container without installing anything.
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore -r requirements.txt

# Copy the application code (.dockerignore keeps .env, .venv, saved records and caches out).
COPY . .

# Run as a normal user, and give it the folder for saved records
# (mount a volume at /app/data to keep records between runs).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data
USER appuser

# Settings come from the environment at run time (docker run --env-file .env), never from the image:
#   GEMINI_API_KEY         required for live AI analysis
#   FLASK_SECRET_KEY       optional; a random key is generated at start-up if it is not set
#   DONOTSTRESS_DATA_PATH  optional; default data/student_records.json (inside /app/data)

EXPOSE 5000

# Docker reports the container as "healthy" once the home page answers.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request as r; r.build_opener(r.ProxyHandler({})).open('http://127.0.0.1:5000/', timeout=4)"]

# Default: the web app on all interfaces so it is reachable from the host.
CMD ["python", "-m", "flask", "--app", "main:app", "run", "--host", "0.0.0.0", "--port", "5000"]
