"""DoNotStress campus UI. Validated check-ins, illustrative results, no storage."""

import os
import secrets

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import io_manager


FORM_FIELDS = io_manager.RECORD_FIELD_ORDER
VALIDATORS = {name: getattr(io_manager, 'validate_' + name) for name in FORM_FIELDS}


def validate_form(values):
    """Return field errors using the project's canonical input validators."""
    errors = {}
    for name, validator in VALIDATORS.items():
        ok, value = validator(values.get(name, ''))
        if not ok:
            errors[name] = value
    return errors


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    if test_config:
        app.config.update(test_config)

    def render_campus(page='home'):
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_urlsafe(32)
        return render_template(
            'checkin.html',
            boot={
                'page': page,
                'completed': bool(session.get('frontend_demo_ready')),
                'csrfToken': session['csrf_token'],
                'submitUrl': url_for('submit_checkin'),
            },
        )

    @app.get('/')
    def checkin():
        return render_campus()

    @app.post('/')
    def submit_checkin():
        token = request.headers.get('X-CSRF-Token', '')
        expected = session.get('csrf_token', '')
        if not expected or not secrets.compare_digest(token, expected):
            return jsonify(message='This page has expired. Reload before checking in again.'), 403
        values = request.get_json(silent=True) if request.is_json else request.form
        if not isinstance(values, dict) and not hasattr(values, 'get'):
            return jsonify(message='Please submit a check-in form.'), 400
        errors = validate_form(values)
        if errors:
            return jsonify(errors=errors), 400
        # Only a completion flag is retained. Never put student answers in cookies.
        # Connect assessment here only after ai_manager's field contract is aligned.
        session['frontend_demo_ready'] = True
        return jsonify(ok=True, demo=True)

    @app.get('/result')
    def result():
        if not session.get('frontend_demo_ready'):
            return redirect(url_for('checkin'))
        return render_campus('result')

    @app.get('/new')
    def new_checkin():
        session.pop('frontend_demo_ready', None)
        return redirect(url_for('checkin'))

    @app.after_request
    def prevent_answer_caching(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '5000')))
