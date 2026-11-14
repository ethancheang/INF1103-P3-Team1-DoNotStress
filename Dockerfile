# DoNotStress — Phase 2 (19-Class OOP Architecture)
# Matches the Python version used in GitHub Actions CI (.github/workflows/tests.yml)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=5000 \
    GEMINI_API_KEY=""

WORKDIR /app

# Install pinned dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check --root-user-action=ignore -r requirements.txt

# Copy the application source code (.dockerignore excludes .env, .venv, saved records, and caches)
COPY . .

# Run as a non-root user and prepare /app/data for persisted JSON records
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app/data
USER appuser

EXPOSE 5000

# Verify the Flask web server responds on port 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request as r; r.build_opener(r.ProxyHandler({})).open('http://127.0.0.1:5000/', timeout=4)"]

# Start the application via the single OOP entry point (reads HOST=0.0.0.0 and PORT=5000)
CMD ["python", "main.py"]
