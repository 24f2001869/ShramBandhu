# 3. shrambandhu/__init__.py (Updated with new extensions and config check)
import os
from flask import Flask, render_template, redirect, url_for, flash
from flask_login import current_user
from datetime import datetime, timedelta
from shrambandhu.config import config, check_config # Import config check
from shrambandhu.extensions import db, login_manager, migrate, bcrypt, csrf, mail # Import new extensions

def create_app(config_name=None):
    if config_name is None:
        config_name = os.getenv('FLASK_CONFIG', 'default')

    app = Flask(__name__, instance_relative_config=True) # Use instance folder for sensitive configs if needed
    app.config.from_object(config[config_name])

    # Create instance folder if it doesn't exist
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # Load instance config if it exists (e.g., instance/config.py)
    # app.config.from_pyfile('config.py', silent=True)

    # Check essential configuration
    check_config(app.config)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    csrf.init_app(app) # Initialize CSRF protection
    mail.init_app(app) # Initialize Mail

    # --- Jinja Filters ---
    @app.template_filter('time_ago')
    def time_ago_filter(dt):
        # (Keep your existing time_ago logic here)
        if dt is None: return "recently"
        now = datetime.utcnow()
        diff = now - dt
        if diff.days > 365: return f"{diff.days // 365} year{'s' if diff.days // 365 > 1 else ''} ago"
        if diff.days > 30: return f"{diff.days // 30} month{'s' if diff.days // 30 > 1 else ''} ago"
        if diff.days > 0: return f"{diff.days} day{'s' if diff.days > 1 else ''} ago"
        if diff.seconds > 3600: return f"{diff.seconds // 3600} hour{'s' if diff.seconds // 3600 > 1 else ''} ago"
        if diff.seconds > 60: return f"{diff.seconds // 60} minute{'s' if diff.seconds // 60 > 1 else ''} ago"
        return "just now"
    
    @app.context_processor
    def inject_now():
        from datetime import datetime
        return {'now': datetime.utcnow}
    
    from .auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from .worker import worker_bp
    app.register_blueprint(worker_bp, url_prefix='/worker')

    from .employer import employer_bp
    app.register_blueprint(employer_bp, url_prefix='/employer')

    from .admin import admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')
    
    from .ivr import ivr_bp
    app.register_blueprint(ivr_bp) 
    # (Keep chat blueprint if needed)
    # from .chat import chat_bp
    # app.register_blueprint(chat_bp, url_prefix='/chat')

    # --- Main Routes ---
    @app.route('/')
    def index():
        # Redirect authenticated users to their respective dashboards
        if current_user.is_authenticated:
            if current_user.role == 'worker':
                return redirect(url_for('worker.dashboard'))
            elif current_user.role == 'employer':
                return redirect(url_for('employer.dashboard'))
            elif current_user.role == 'admin':
                return redirect(url_for('admin.dashboard'))
        # Show landing page for anonymous users
        return render_template('index.html')

    # --- Error Handlers ---
    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template('errors/403.html'), 403 # Create this template

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template('errors/404.html'), 404

    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback() # Rollback the session in case of DB errors
        # Log the error properly in production
        app.logger.error(f'Server Error: {error}', exc_info=True)
        return render_template('errors/500.html'), 500 # Create this template

    return app