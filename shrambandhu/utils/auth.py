from functools import wraps
from flask import redirect, url_for, session

def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return redirect(url_for('auth.login'))
            
            # Optional role checking
            if role:
                user = User.query.get(session['user_id'])
                if user.role != role:
                    return redirect(url_for('auth.login'))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator