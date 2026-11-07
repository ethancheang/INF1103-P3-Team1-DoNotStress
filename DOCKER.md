# Running DoNotStress in Docker

The Dockerfile is in the repository root. All Python dependencies (including pytest) are installed when the image is built, so the assessor does not need to install anything on their machine.

## Prerequisites

- Docker installed and running
- A Gemini API key (only required for live AI analysis; **tests do not need it**)

## 1. Build the image

From the repository root (the folder that contains the Dockerfile):

```bash
docker build -t donotstress .
```

## 2. Run the web application

```bash
docker run --rm -p 5000:5000 \
  -e GEMINI_API_KEY=your_key_here \
  -v donotstress-data:/app/data \
  donotstress
```

Then open http://127.0.0.1:5000

### Using an env file (recommended)

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY=...

docker run --rm -p 5000:5000 \
  --env-file .env \
  -v donotstress-data:/app/data \
  donotstress
```

Stop the container with `Ctrl+C`.

## 3. Run the automated tests

Tests use sample responses and mocks. They do **not** need a Gemini API key or network access.

```bash
docker run --rm donotstress python -m pytest tests/ -v
```

You can also run the original unittest suite:

```bash
docker run --rm donotstress python -m unittest discover -s tests -v
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes, for live AI | Gemini API key from Google AI Studio. Not needed for tests. |
| `FLASK_SECRET_KEY` | No | Session secret. A random key is used if empty. |
| `DONOTSTRESS_DATA_PATH` | No | Override path for the records file. |

**Do not commit `.env` or any file containing a real API key.**

## Notes

- Saved check-ins persist in the Docker volume `donotstress-data`.
- The image listens on `0.0.0.0:5000` so it is reachable from the host.
- Verify the build on your machine before submission:

  ```bash
  docker build -t donotstress .
  docker run --rm donotstress python -m pytest tests/ -v
  ```
