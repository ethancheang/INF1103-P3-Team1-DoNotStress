"""DoNotStress web app entry point.

All wiring lives in CampusApp; this file only loads the local .env file,
builds the app and starts it.

    python main.py                                  # local development server
    python -m flask --app main:app run              # Flask CLI (used by the Dockerfile)
"""

from dotenv import load_dotenv

from campus_app import CampusApp

load_dotenv()
campus = CampusApp()
app = campus.flask_app

if __name__ == "__main__":
    campus.run()
