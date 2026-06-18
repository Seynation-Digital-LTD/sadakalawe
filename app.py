import os
import logging
import traceback
from datetime import timedelta, datetime
from flask import Flask, redirect, url_for, session, render_template
from flask_login import LoginManager, current_user
from database import close_db, init_db
from models import User

login_manager = LoginManager()


def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get(
        'SECRET_KEY', 'sadakalawe-2026-change-in-production-xK9mP2qR')
    app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), 'data', 'sadakalawe.db')
    app.config['BACKUP_DIR'] = os.path.join(os.path.dirname(__file__), 'backups')
    app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=30)
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB

    # Mail settings from environment
    import config as _cfg
    app.config['MAIL_SERVER']   = _cfg.MAIL_SERVER
    app.config['MAIL_PORT']     = _cfg.MAIL_PORT
    app.config['MAIL_USERNAME'] = _cfg.MAIL_USERNAME
    app.config['MAIL_PASSWORD'] = _cfg.MAIL_PASSWORD
    app.config['MAIL_FROM']     = _cfg.MAIL_FROM

    os.makedirs(os.path.dirname(app.config['DATABASE']), exist_ok=True)
    os.makedirs(app.config['BACKUP_DIR'], exist_ok=True)

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to continue.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        user = User.get_by_id(user_id)
        if user is None:
            return None
        # Single-session: reject if session token doesn't match DB
        if user.session_token and session.get('session_token') != user.session_token:
            return None
        return user

    @app.before_request
    def enforce_password_change():
        """Force must_change_password users to the profile page before anything else."""
        if not current_user.is_authenticated:
            return
        if not current_user.must_change_password:
            return
        # Allow the profile page, logout, and static files through
        from flask import request as req
        if req.endpoint in ('auth.profile', 'auth.logout', 'static'):
            return
        flash('Please change your password before continuing.', 'warning')
        return redirect(url_for('auth.profile'))

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    from routes.auth import bp as auth_bp
    from routes.customers import bp as customers_bp
    from routes.products import bp as products_bp
    from routes.documents import bp as documents_bp
    from routes.reports import bp as reports_bp
    from routes.backup_routes import bp as backup_bp
    from routes.credits import bp as credits_bp
    from routes.stock import bp as stock_bp
    from routes.expenses import bp as expenses_bp
    from routes.financing import bp as financing_bp
    from routes.tradeins import bp as tradeins_bp
    from routes.import_data import bp as import_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(customers_bp)
    app.register_blueprint(products_bp)
    app.register_blueprint(documents_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(credits_bp)
    app.register_blueprint(stock_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(financing_bp)
    app.register_blueprint(tradeins_bp)
    app.register_blueprint(import_bp)

    @app.template_filter('dt')
    def format_dt(value):
        if not value:
            return ''
        s = str(value).strip()
        try:
            d = datetime.fromisoformat(s[:19])
            if len(s) <= 10:
                return d.strftime('%d %b %Y')
            return d.strftime('%d %b %Y, %H:%M')
        except Exception:
            return s[:16]

    @app.route('/')
    def index():
        return redirect(url_for('reports.dashboard'))

    # ── Error handlers ─────────────────────────────────────────
    def _err(code, title, message, detail=None):
        try:
            return render_template('errors/error.html',
                                   code=code, title=title,
                                   message=message, detail=detail), code
        except Exception:
            # Last-resort fallback if the template itself fails
            return (f'<h2>{code} – {title}</h2><p>{message}</p>'
                    f'<a href="/">Go to Dashboard</a>'), code

    @app.errorhandler(400)
    def bad_request(e):
        return _err(400, 'Bad Request',
                    'The request could not be understood. Please go back and try again.')

    @app.errorhandler(403)
    def forbidden(e):
        return _err(403, 'Access Denied',
                    "You don't have permission to do that. "
                    "Contact your administrator if you think this is a mistake.")

    @app.errorhandler(404)
    def not_found(e):
        return _err(404, 'Page Not Found',
                    "We couldn't find that page or record. "
                    "It may have been deleted or the link might be wrong.")

    @app.errorhandler(413)
    def too_large(e):
        return _err(413, 'File Too Large',
                    'The file you uploaded is too large. '
                    'Maximum allowed size is 16 MB. Please use a smaller file.')

    @app.errorhandler(500)
    def server_error(e):
        logging.exception('Unhandled 500 error')
        return _err(500, 'Something Went Wrong',
                    'An unexpected error occurred. Please try again. '
                    'If the problem keeps happening, let the system administrator know.')

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        # Log the full traceback to the console for debugging
        logging.exception('Unhandled exception: %s', e)
        # In debug mode, let Flask show its interactive debugger
        if app.debug:
            raise e
        return _err(500, 'Something Went Wrong',
                    'An unexpected error occurred. Please try again. '
                    'If this keeps happening, restart the application.',
                    detail=str(e) if app.config.get('SHOW_ERROR_DETAIL') else None)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='127.0.0.1', port=8080)
