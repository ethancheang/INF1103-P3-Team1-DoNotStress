"""DoNotStress entry point.

Composition root only. The four managers and the supporting services are
wired in CampusApp; this module just builds the Flask app and starts it.

    campus UI  →  StudentIO (I/O)
               →  GeminiAIManager (AI)
               →  LogicManager (Logic)
               →  JsonRecordRepository (Data)
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

from campus_app import CampusApp

load_dotenv()


def create_app(test_config=None):
    """Flask application factory. Used by `flask --app main` and the Dockerfile."""
    return CampusApp().create(test_config)


app = create_app()

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"},
    )
