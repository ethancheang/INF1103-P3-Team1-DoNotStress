"""DoNotStress entry point: campus UI → I/O → Gemini → Logic → opt-in storage."""

import logging
import os
import secrets
import time
from threading import RLock

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import ai_manager
import data_manager
import io_manager
import logic_manager

load_dotenv()
logger = logging.getLogger(__name__)


def process_checkin(record, *, generate_fn=None, max_attempts=3, retry_delay_sec=0.5):
    """AI must succeed before Logic may finalize an assessment."""
    ok, enriched, error = ai_manager.analyse_student(
        record, generate_fn=generate_fn, max_attempts=max_attempts,
        retry_delay_sec=retry_delay_sec,
    )
    if not ok or not isinstance(enriched, dict):
        code = error.get('error_code', 'unavailable') if isinstance(error, dict) else 'unavailable'
        logger.warning('Check-in could not complete: %s', code)
        return False, code
    finalized = logic_manager.apply_logic(enriched)
    if not isinstance(finalized, dict) or not finalized.get('ok'):
        return False, 'unavailable'
    return True, finalized


def result_view(record, saved=False):
    """Only send allow-listed, student-facing copy to the browser."""
    return {
        'soft': io_manager.format_soft_label(record['soft_label']),
        'tips': io_manager.format_tips(record['tips']),
        'advisor': io_manager.format_speak_to_advisor_panel(record['speak_prominence']),
        'saved': saved,
    }


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        DATA_PATH=os.environ.get('DONOTSTRESS_DATA_PATH') or None,
        AI_GENERATE_FN=None, AI_MAX_ATTEMPTS=3, AI_RETRY_DELAY_SEC=0.5,
        PENDING_TTL_SECONDS=1800, MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    # Single-process local app: retain records temporarily in server memory,
    # never inside Flask's client-readable signed session cookie.
    pending = {}
    lock = RLock()
    app.extensions['pending_checkins'] = pending

    def clear_pending():
        with lock:
            pending.pop(session.pop('checkin_token', None), None)

    def current_entry():
        with lock:
            return pending.get(session.get('checkin_token'))

    @app.before_request
    def expire_records_and_check_csrf():
        with lock:
            cutoff = time.monotonic() - app.config['PENDING_TTL_SECONDS']
            for key in [key for key, item in pending.items() if item['created'] < cutoff]:
                del pending[key]
        if request.method == 'POST':
            expected = session.get('csrf_token', '')
            provided = request.headers.get('X-CSRF-Token', '')
            if not expected or not secrets.compare_digest(provided, expected):
                return jsonify(message='This page has expired. Reload and try again.'), 403

    def render_campus(page='home'):
        session.setdefault('csrf_token', secrets.token_urlsafe(32))
        entry = current_entry()
        return render_template('checkin.html', boot={
            'page': page, 'completed': bool(entry),
            'result': result_view(entry['record'], entry['saved']) if entry else None,
            'csrfToken': session['csrf_token'],
            'submitUrl': url_for('submit_checkin'), 'saveUrl': url_for('save_checkin'),
            'newUrl': url_for('new_checkin'),
        })

    @app.get('/')
    def checkin():
        return render_campus()

    @app.post('/')
    def submit_checkin():
        values = request.get_json(silent=True) if request.is_json else request.form
        if not hasattr(values, 'get'):
            return jsonify(message='Please submit a check-in form.'), 400
        ok, record = io_manager.validate_student_form(values)
        if not ok:
            return jsonify(errors=record), 400
        clear_pending()
        try:
            ok, outcome = process_checkin(
                record, generate_fn=app.config['AI_GENERATE_FN'],
                max_attempts=app.config['AI_MAX_ATTEMPTS'],
                retry_delay_sec=app.config['AI_RETRY_DELAY_SEC'],
            )
        except Exception:
            logger.warning('Check-in pipeline could not complete')
            ok, outcome = False, 'unavailable'
        if not ok:
            copy = io_manager.format_ai_error(outcome)
            return jsonify(
                message='We could not complete your check-in right now. Your answers are still here; please try again.',
                error_code=outcome, advisor=copy['speak_to_advisor'],
            ), 503
        token = secrets.token_urlsafe(32)
        with lock:
            pending[token] = {'record': outcome, 'saved': False, 'created': time.monotonic()}
        session['checkin_token'] = token
        return jsonify(ok=True, result=result_view(outcome))

    @app.get('/result')
    def result():
        if not current_entry():
            return redirect(url_for('checkin'))
        return render_campus('result')

    @app.post('/save')
    def save_checkin():
        values = request.get_json(silent=True) if request.is_json else request.form
        if not hasattr(values, 'get') or values.get('opt_in') not in (True, 'yes', 'on'):
            return jsonify(message='Tick the consent box before saving.'), 400
        with lock:
            entry = current_entry()
            if not entry:
                return jsonify(message='Your result has expired. Please start a new check-in.'), 409
            if entry['saved']:
                return jsonify(ok=True, saved=True)
            try:
                saved = data_manager.save_record(entry['record'], data_path=app.config['DATA_PATH'], opt_in=True)
            except Exception:
                saved = {'ok': False}
            if not saved.get('ok'):
                return jsonify(message='Your check-in could not be saved. Please try again.'), 500
            entry['saved'] = True
        return jsonify(ok=True, saved=True)

    @app.get('/new')
    def new_checkin():
        clear_pending()
        return redirect(url_for('checkin'))

    @app.errorhandler(413)
    def oversized_request(error):
        return jsonify(message='Your response is too long. Please shorten it and try again.'), 413

    @app.after_request
    def prevent_answer_caching(response):
        if request.endpoint != 'static':
            response.headers['Cache-Control'] = 'no-store'
        return response

    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '5000')),
            debug=os.environ.get('FLASK_DEBUG', '0').lower() in {'1', 'true', 'yes'})
