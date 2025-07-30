# 2. shrambandhu/extensions.py (Added Flask-Bcrypt and Flask-Mail)
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt # For password hashing
from flask_wtf.csrf import CSRFProtect # For form security
from flask_mail import Mail # For email sending

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
bcrypt = Bcrypt()
csrf = CSRFProtect()
mail = Mail()

# Configure LoginManager
login_manager.login_view = 'auth.login' # Route to redirect to if user is not logged in
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'info' # Flash message category

@login_manager.user_loader
def load_user(user_id):
    """Required user loader function for Flask-Login."""
    from .models import User # Local import to avoid circular dependency
    return User.query.get(int(user_id))