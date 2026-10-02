"""Pointer to the Flask check-in app.

The temporary terminal front end targeted an older advisor schema
(submission rate, CCA count, consecutive absences, intervention tiers).
This file does not import logic_manager or data_manager — those layers
are not in this checkout — so importing it cannot fail for that reason.

The web app is the primary entry point: form, then Gemini, then the result.
"""


def main() -> None:
    print("DoNotStress runs as a local web app. From this folder:")
    print()
    print("  pip install -r requirements.txt")
    print('  $env:GEMINI_API_KEY="your-key-here"')
    print("  python app.py")
    print()
    print("Then open http://127.0.0.1:5000")


if __name__ == "__main__":
    main()
