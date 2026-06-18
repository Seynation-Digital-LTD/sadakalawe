import os
from datetime import timedelta
from flask import Flask, redirect, url_for, session
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

    @app.route('/')
    def index():
        return redirect(url_for('reports.dashboard'))

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='127.0.0.1', port=8080)
