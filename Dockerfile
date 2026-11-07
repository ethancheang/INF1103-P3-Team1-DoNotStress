# DoNotStress — Phase 2
# Python version matches the project's tested environment.
FROM python:3.12-slim

WORKDIR /app

# Install pinned dependencies (including pytest) so the assessor
# does not need to install anything on the host machine.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Folder for saved records (mount a volume here to persist data)
RUN mkdir -p /app/data

# No real API key is baked into the image.
# Pass GEMINI_API_KEY at run time with -e or --env-file.
ENV GEMINI_API_KEY=""
ENV FLASK_SECRET_KEY=""
ENV DONOTSTRESS_DATA_PATH=""

EXPOSE 5000

# Default: start the web app on all interfaces so it is reachable outside the container.
CMD ["python", "-m", "flask", "--app", "main:create_app", "run", "--host", "0.0.0.0", "--port", "5000"]
