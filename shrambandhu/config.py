# shrambandhu/config.py (Revised to use os.getenv)
import os
# from decouple import config # No longer using decouple

# Helper function for casting boolean env vars
def _get_bool_env(var_name, default=False):
    val = os.getenv(var_name, str(default)).lower()
    return val in ('true', '1', 't', 'y', 'yes')

# Helper function for casting integer env vars
def _get_int_env(var_name, default=0):
    try:
        return int(os.getenv(var_name, str(default)))
    except ValueError:
        return default

class Config:
    # Use os.urandom for default if SECRET_KEY is not in .env
    SECRET_KEY = os.getenv('SECRET_KEY', None) or os.urandom(24)
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///../instance/database.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Twilio Configuration
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', None)
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', None)
    TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER', None)
    TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER', None) or TWILIO_PHONE_NUMBER # Default to main number if not set
    TWILIO_TWIML_APP_SID = os.getenv('TWILIO_TWIML_APP_SID', None)
    TWILIO_API_KEY = os.getenv('TWILIO_API_KEY', None)
    TWILIO_API_SECRET = os.getenv('TWILIO_API_SECRET', None)

    # Google Cloud Credentials
    # Default path relative to this config file's directory
    _default_google_creds = os.path.join(os.path.dirname(__file__), '..', 'google-creds.json')
    GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS', _default_google_creds)

    # Razorpay Configuration
    RAZORPAY_KEY_ID = os.getenv('RAZORPAY_KEY_ID', None)
    RAZORPAY_KEY_SECRET = os.getenv('RAZORPAY_KEY_SECRET', None)

    # File Upload Configuration
    # Default path relative to this config file's directory, inside instance folder
    _default_upload_folder = os.path.join(os.path.dirname(__file__), '..', 'instance', 'uploads')
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', _default_upload_folder)
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'mp3', 'wav', 'ogg', 'opus', 'm4a'}
    MAX_CONTENT_LENGTH = _get_int_env('MAX_CONTENT_LENGTH', 16 * 1024 * 1024) # 16MB default

    # Google OAuth Configuration
    GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID', None)
    GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET', None)
    GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI', 'http://localhost:5000/auth/callback/google')

    # Security Headers
    SESSION_COOKIE_SECURE = _get_bool_env('SESSION_COOKIE_SECURE', False)
    SESSION_COOKIE_HTTPONLY = _get_bool_env('SESSION_COOKIE_HTTPONLY', True)
    SESSION_COOKIE_SAMESITE = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')

    # Mail Configuration
    MAIL_SERVER = os.getenv('MAIL_SERVER', 'smtp.sendgrid.net')
    MAIL_PORT = _get_int_env('MAIL_PORT', 587)
    MAIL_USE_TLS = _get_bool_env('MAIL_USE_TLS', True)
    MAIL_USERNAME = os.getenv('MAIL_USERNAME', 'apikey') # Usually 'apikey' for SendGrid
    MAIL_PASSWORD = os.getenv('SENDGRID_API_KEY', None) # Read SendGrid key directly
    MAIL_DEFAULT_SENDER = os.getenv('MAIL_DEFAULT_SENDER', 'noreply@shrambandhu.app')

    # Add Flask-WTF specific CSRF config if needed
    WTF_CSRF_ENABLED = _get_bool_env('WTF_CSRF_ENABLED', True)
    # SECRET_KEY is already used by default for CSRF


class DevelopmentConfig(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = _get_bool_env('SQLALCHEMY_ECHO', False)
    SESSION_COOKIE_SECURE = False # Override for local HTTP development


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True # Enforce HTTPS


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}

# --- Helper function to check essential config ---
def check_config(app_config):
    # Define required variables (can vary between dev/prod)
    required_vars = ['SECRET_KEY', 'SQLALCHEMY_DATABASE_URI']
    # Add provider keys only if you intend to use those features immediately
    # required_vars.extend(['TWILIO_ACCOUNT_SID', 'TWILIO_AUTH_TOKEN', 'TWILIO_PHONE_NUMBER'])
    # required_vars.extend(['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'])
    # required_vars.extend(['SENDGRID_API_KEY']) # Or MAIL_PASSWORD if using basic auth

    missing = []
    for key in required_vars:
        # Use hasattr for direct class attribute check or .get for dict-like access
        # Since app.config behaves like a dict after from_object:
        if not app_config.get(key):
            missing.append(key)

    if missing:
        print(f"WARNING: Missing critical configuration variables: {', '.join(missing)}")
        print("         Features requiring these variables may not work.")

    # Check if upload folder exists, create if not
    upload_folder = app_config.get('UPLOAD_FOLDER')
    if upload_folder and not os.path.exists(upload_folder):
        try:
            os.makedirs(upload_folder, exist_ok=True) # Use exist_ok=True
            print(f"Checked/Created upload folder: {upload_folder}")
        except OSError as e:
            print(f"ERROR: Could not create upload folder '{upload_folder}': {e}")
    elif not upload_folder:
         print("WARNING: UPLOAD_FOLDER configuration is not set.")


# --- Function to get Google OAuth config (uses loaded config) ---
def get_google_oauth_config(app_config):
    # Read directly from the Flask app config object
    client_id = app_config.get('GOOGLE_CLIENT_ID')
    client_secret = app_config.get('GOOGLE_CLIENT_SECRET')
    redirect_uri = app_config.get('GOOGLE_REDIRECT_URI')

    if not all([client_id, client_secret, redirect_uri]):
        # Log this warning
        # current_app.logger.warning("Google OAuth configuration incomplete.") # Can't use current_app here
        print("WARNING: Google OAuth configuration incomplete in config.")
        return None # Indicate incomplete config

    return {
        'client_id': client_id,
        'client_secret': client_secret,
        'authorize_url': 'https://accounts.google.com/o/oauth2/auth',
        'token_url': 'https://oauth2.googleapis.com/token',
        'userinfo_url': 'https://www.googleapis.com/oauth2/v3/userinfo',
        'scope': 'openid email profile',
        'redirect_uri': redirect_uri
    }