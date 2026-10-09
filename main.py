"""DoNotStress entry point: campus UI → I/O → Gemini → Logic → opt-in storage."""

import logging
import os
import secrets
import time
from threading import RLock

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash

import ai_manager
import data_manager
import io_manager
import logic_manager
import survey

load_dotenv()
logger = logging.getLogger(__name__)

# Fixed coursework/demo account. Only the hash lives in server code; never
# include credentials in templates, JavaScript or the browser boot payload.
ADMIN_USERNAME = 'admin'
ADMIN_PASSWORD_HASH = 'scrypt:32768:8:1$zoikUrXAJEAJCQlR$83ec3b2a32cedeb5721031e22f7fedc19ed5eea40c5995aa11d2c2ea1cc40845b393de85d68cda54706b5714293fc49ec360a477913186f00b46be7a6c31e8c1'


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
        'insights': {
            'risk_category': record.get('risk_category', 'Unknown'),
            'explanation': str(record.get('reasoning', '')).split(' Logic adjusted:')[0],
            'stressors': record.get('primary_stressors', []),
            'survey_version': record.get('survey_version', 'legacy'),
            'pss_total': record.get('pss_total'),
            'support_mean': record.get('support_mean'),
            'context_flags': record.get('context_flags', {}),
            'factors': record.get('factor_insights', []),
            'safety_flag': record.get('safety_flag', False),
            'snapshot': {key: record.get(key) for key in (
                'sleep_hours', 'stress_level', 'academic_workload',
                'financial_stress', 'social_support', *survey.QUESTION_MAP)},
        },
    }


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
        DATA_PATH=os.environ.get('DONOTSTRESS_DATA_PATH') or None,
        AI_GENERATE_FN=None, AI_MAX_ATTEMPTS=3, AI_RETRY_DELAY_SEC=0.5,
        PENDING_TTL_SECONDS=1800, MAX_CONTENT_LENGTH=64 * 1024,
        ADMIN_SESSION_SECONDS=1800, ADMIN_LOGIN_MAX_ATTEMPTS=5,
        ADMIN_LOGIN_WINDOW_SECONDS=300,
    )
    if test_config:
        app.config.update(test_config)
    # Single-process local app: retain records temporarily in server memory,
    # never inside Flask's client-readable signed session cookie.
    pending = {}
    lock = RLock()
    app.extensions['pending_checkins'] = pending
    # Server-side tokens make logout/expiry revoke access even if a previous
    # signed session cookie is replayed. No role is trusted from client input.
    admin_sessions = {}
    login_attempts = {}
    app.extensions['admin_sessions'] = admin_sessions

    def is_admin():
        token = session.get('admin_token')
        with lock:
            expires = admin_sessions.get(token, 0)
            if expires > time.monotonic():
                return True
            admin_sessions.pop(token, None)
        session.pop('admin_token', None)
        return False

    def revoke_admin():
        with lock:
            admin_sessions.pop(session.pop('admin_token', None), None)

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
            now = time.monotonic()
            for key in [key for key, expiry in admin_sessions.items() if expiry <= now]:
                del admin_sessions[key]
            for key in list(login_attempts):
                login_attempts[key] = [stamp for stamp in login_attempts[key]
                                       if stamp > now - app.config['ADMIN_LOGIN_WINDOW_SECONDS']]
                if not login_attempts[key]:
                    del login_attempts[key]
        if request.method == 'POST':
            expected = session.get('csrf_token', '')
            provided = request.headers.get('X-CSRF-Token', '')
            if not provided and not request.is_json:
                provided = request.form.get('csrf_token', '')
            if not expected or not secrets.compare_digest(provided.encode('utf-8'), expected.encode('utf-8')):
                return jsonify(message='This page has expired. Reload and try again.'), 403

    def render_campus(page='home'):
        session.setdefault('csrf_token', secrets.token_urlsafe(32))
        entry = current_entry()
        return render_template('checkin.html', boot={
            'page': page, 'completed': bool(entry), 'survey': survey.public_config(),
            'isAdmin': is_admin(), 'adminLoginUrl': url_for('admin_login'),
            'result': result_view(entry['record'], entry['saved']) if entry else None,
            'csrfToken': session['csrf_token'],
            'submitUrl': url_for('submit_checkin'), 'saveUrl': url_for('save_checkin'),
            'newUrl': url_for('new_checkin'),
            'recordsUrl': url_for('saved_records'),
        })

    @app.get('/')
    def checkin():
        return render_campus()

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        if is_admin():
            return redirect(url_for('records_page'))
        session.setdefault('csrf_token', secrets.token_urlsafe(32))
        error, status = None, 200
        if request.method == 'POST':
            values = request.get_json(silent=True) if request.is_json else request.form
            values = values if isinstance(values, dict) or hasattr(values, 'get') else {}
            username, password = values.get('username', ''), values.get('password', '')
            address = request.remote_addr or 'local'
            with lock:
                attempts = login_attempts.setdefault(address, [])
                if len(attempts) >= app.config['ADMIN_LOGIN_MAX_ATTEMPTS']:
                    error, status = 'Too many sign-in attempts. Please try again in five minutes.', 429
                else:
                    attempts.append(time.monotonic())
            if not error:
                valid_password = isinstance(password, str) and len(password) <= 256 and check_password_hash(ADMIN_PASSWORD_HASH, password)
                if username == ADMIN_USERNAME and valid_password:
                    revoke_admin()
                    token = secrets.token_urlsafe(32)
                    with lock:
                        admin_sessions[token] = time.monotonic() + app.config['ADMIN_SESSION_SECONDS']
                        login_attempts.pop(address, None)
                    session['admin_token'] = token
                    session['csrf_token'] = secrets.token_urlsafe(32)
                    return redirect(url_for('records_page'))
                error, status = 'Incorrect username or password.', 401
        return render_template('admin_login.html', error=error, csrf_token=session['csrf_token']), status

    @app.post('/admin/logout')
    def admin_logout():
        revoke_admin()
        clear_pending()
        session.clear()
        return redirect(url_for('checkin'))

    @app.post('/')
    def submit_checkin():
        values = request.get_json(silent=True) if request.is_json else request.form
        if not hasattr(values, 'get'):
            return jsonify(message='Please submit a check-in form.'), 400
        safety = survey.safety_check(values.get('feelings_text', ''))
        ok, record = io_manager.validate_student_form(values)
        if not ok:
            return jsonify(errors=record, safety_flag=safety,
                           advisor=io_manager.format_speak_to_advisor_panel('high') if safety else None), 400
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
                error_code=outcome, safety_flag=safety, advisor=copy['speak_to_advisor'],
            ), 503
        token = secrets.token_urlsafe(32)
        with lock:
            pending[token] = {'record': outcome, 'saved': False, 'created': time.monotonic()}
        session['checkin_token'] = token
        return jsonify(ok=True, result=result_view(outcome))

    @app.get('/records')
    def records_page():
        if not is_admin():
            return redirect(url_for('admin_login'))
        return render_campus('records')

    @app.get('/api/records')
    def saved_records():
        """Read only explicitly saved check-ins; never expose free text or keys."""
        if not is_admin():
            return jsonify(message='Admin sign-in is required to view saved records.'), 401
        try:
            with lock:
                loaded = data_manager.load_all_records(app.config['DATA_PATH'])
        except Exception:
            loaded = {'ok': False}
        if not loaded.get('ok') or loaded.get('error'):
            return jsonify(message='Saved records could not be loaded. Please try again.'), 500
        records = [item for item in loaded.get('records', []) if isinstance(item, dict)]
        cohorts = sorted({str(item.get('student_id', ''))[:2] for item in records
                          if len(str(item.get('student_id', ''))) >= 2
                          and str(item.get('student_id', ''))[:2].isascii()
                          and str(item.get('student_id', ''))[:2].isdigit()}, reverse=True)
        query = request.args.get('student_id', '').strip()
        risk = request.args.get('risk_category', '').strip()
        cohort = request.args.get('cohort_year', '').strip()
        if risk and risk not in {'Low', 'Moderate', 'High'}:
            return jsonify(message='Choose Low, Moderate, or High risk.'), 400
        if cohort and (len(cohort) not in (2, 4) or not cohort.isascii() or not cohort.isdigit()):
            return jsonify(message='Choose a valid cohort year.'), 400
        filtered = data_manager.filter_records(records, **{
            key: value for key, value in {'risk_category': risk, 'cohort_year': cohort}.items() if value
        })
        filtered = [item for item in filtered if query in str(item.get('student_id', ''))]
        columns = ('student_id', 'sleep_hours', 'stress_level', 'academic_workload',
                   'financial_stress', 'social_support', 'risk_category', 'saved_at',
                   'survey_version', 'pss_total', 'sleep_hours_avg', 'sleep_quality',
                   'pas_workload', 'pas_catchup', 'fin_stress', 'mspss_friends',
                   'mspss_family', 'mspss_so', 'support_mean')
        rows = []
        for item in filtered:
            row = {key: item.get(key) for key in columns}
            failed = item.get('ai_ok') is False or item.get('ok') is False
            processed = item.get('ai_ok') is True or str(item.get('source', '')).lower() in {
                'gemini', 'ai', 'ai_manager', 'gemini+logic', 'ai_logic'}
            row['ai_status'] = 'Failed' if failed else 'Processed' if processed else 'Unknown'
            rows.append(row)
        rows.sort(key=lambda row: str(row.get('saved_at') or ''), reverse=True)
        return jsonify(records=rows, total=len(records), matching=len(rows), cohorts=cohorts)

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
