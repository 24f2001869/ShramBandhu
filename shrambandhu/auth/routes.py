# shrambandhu/auth/routes.py (Updated)

from flask import Blueprint, request, redirect, url_for, flash, session, render_template, current_app
from flask_login import login_user, logout_user, login_required, current_user
from shrambandhu.extensions import db, bcrypt, mail # Import necessary extensions
from shrambandhu.models import User 
from shrambandhu.utils.twilio_client import send_sms # Keep for OTP
from shrambandhu.utils.email import send_verification_email, send_password_reset_email # Import email functions
from .forms import RegistrationForm, LoginForm, OTPLoginForm, VerifyOTPForm, RequestPasswordResetForm, ResetPasswordForm , PhoneRegistrationForm # Import forms
from datetime import datetime, timedelta
import random
import os
import requests # Needed for Google OAuth token exchange
import json # For decoding json responses
import string # For generating state
from urllib.parse import urlencode # For constructing URLs
from sqlalchemy import func

from shrambandhu.config import get_google_oauth_config # Import helper

auth_bp = Blueprint('auth', __name__)

# --- Email/Password Registration ---
@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index')) # Redirect logged-in users away

    form = RegistrationForm()
    if form.validate_on_submit():
        try:
            # Create user but mark email/phone as unverified
            user = User(
                name=form.name.data,
                email=form.email.data.lower(), # Store email in lowercase
                phone=form.phone.data,
                role=form.role.data,
                is_email_verified=True,
                is_phone_verified=False # Needs separate verification later
            )
            user.set_password(form.password.data) # Hash the password
            db.session.add(user)
            db.session.flush() # Flush to get user ID if needed for token generation immediately

            # Send email verification link
            token = user.generate_token(purpose='email_verify')
            db.session.commit() # Save user and token
            send_verification_email(user, token) # Call the email sending function

            flash('Registration successful! Please check your email to verify your account.', 'success')
            # Redirect to login page after registration
            return redirect(url_for('auth.login'))
        except Exception as e:
             db.session.rollback()
             current_app.logger.error(f"Registration Error: {e}")
             flash('An error occurred during registration. Please try again.', 'danger')

    return render_template('auth/register_email.html', title='Register', form=form)

# --- Email Verification Route ---
@auth_bp.route('/verify_email/<token>')
def verify_email(token):
    if current_user.is_authenticated:
        # Prevent already logged-in user from verifying someone else's token potentially
        flash('You are already logged in.', 'info')
        return redirect(url_for('index'))

    user = User.query.filter_by(email_verification_token=token).first()

    if user and user.verify_token(token, purpose='email_verify'):
        user.is_email_verified = True
        db.session.commit()
        flash('Your email has been verified successfully! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    else:
        flash('The verification link is invalid or has expired.', 'danger')
        return redirect(url_for('auth.register')) # Or redirect to a page to request new link

# --- Email/Password Login ---
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        # Check if user exists and password is correct
        if user and user.check_password(form.password.data):
            # Check if email is verified (optional but recommended)
            if not user.is_email_verified:
                # Allow login but prompt for verification maybe? Or deny.
                # Let's deny for now for better security.
                flash('Please verify your email address first. Check your inbox for the verification link.', 'warning')
                # Optionally add a way to resend verification email here
                return redirect(url_for('auth.login'))

            login_user(user, remember=form.remember.data)
            user.last_login_at = datetime.utcnow() # Update last login time
            db.session.commit()
            flash('Login successful!', 'success')
            # Redirect to intended page or dashboard
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        else:
            flash('Login Unsuccessful. Please check email and password.', 'danger')

    return render_template('auth/login_email.html', title='Login', form=form)

# --- Logout ---
@auth_bp.route('/logout')
@login_required 
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('auth.login'))

# --- OTP Login (Initiate) ---
@auth_bp.route('/login/otp', methods=['GET', 'POST'])
def login_otp():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = OTPLoginForm()
    if form.validate_on_submit():
        phone = form.phone.data
        user = User.query.filter_by(phone=phone).first()
    
        if user:
            try:
                otp = user.generate_otp()
                db.session.commit()
                
                # BYPASS SMS SENDING COMPLETELY FOR ALL USERS (SINCE SMS SERVICE IS DOWN)
                message = f"Your ShramBandhu login OTP is: {otp}. It's valid for 5 minutes."
                
                # Show OTP on screen instead of sending SMS
                flash(f'SMS service temporarily unavailable. Your OTP is: {otp}', 'info')
                sms_sent = True  # Always treat as successful
                
                if sms_sent:
                    session['otp_login_phone'] = phone
                    return redirect(url_for('auth.verify_login_otp'))
                else:
                    flash('Failed to send OTP. Please try again later or contact support.', 'danger')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"OTP Generation Error for {phone}: {e}")
                flash('An error occurred generating OTP. Please try again.', 'danger')
        else:
            flash('Phone number not registered.', 'danger')
    return render_template('auth/login_otp.html', title='Login with OTP', form=form)



@auth_bp.route('/login/otp/verify', methods=['GET', 'POST'])
def verify_login_otp():
    if current_user.is_authenticated: return redirect(url_for('index')) # Should not happen if verifying phone on profile

    phone = session.get('otp_login_phone')
    # Get the purpose (login or profile_update) and the intended next page
    purpose = session.get('otp_verify_purpose', 'login') # Default to login
    next_url = request.args.get('next') or url_for('index') # Default redirect after verify

    if not phone: flash('OTP session expired or invalid.', 'warning'); return redirect(url_for('auth.login_otp'))

    form = VerifyOTPForm()
    if form.validate_on_submit():
        user = User.query.filter_by(phone=phone).first()
        if user and user.verify_otp(form.otp.data):
             user.is_phone_verified = True # Mark phone as verified
             user.last_login_at = datetime.utcnow() # Update last login too
             db.session.commit()
             session.pop('otp_login_phone', None) # Clear session variables
             session.pop('otp_verify_purpose', None)

             # Log the user in if this wasn't just a profile update verify
             if not current_user.is_authenticated: # If they weren't already logged in
                 login_user(user)
                 flash('Login successful!', 'success')
                 # Use next_url which defaults to index/dashboard
                 return redirect(next_url)
             else: # User was already logged in (likely profile update)
                 flash('Phone number verified successfully!', 'success')
                 # Redirect back to profile page (or the 'next' URL if provided)
                 return redirect(next_url) # next_url should be worker.profile here
        else:
             flash('Invalid or expired OTP.', 'danger')
             # Don't clear session variables on failure, let them retry

    # Pass purpose to template if needed for displaying context
    return render_template('auth/verify_otp.html', title='Verify OTP', form=form, phone=phone, purpose=purpose)



# --- Password Reset Request ---
@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_request():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RequestPasswordResetForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user and user.is_email_verified: # Only send if email is verified
            try:
                # Send password reset email
                token = user.generate_token(purpose='password_reset', expires_in=1800) # 30 min expiry
                db.session.commit()
                send_password_reset_email(user, token)
                flash('A password reset link has been sent to your email.', 'info')
            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Password Reset Email Error for {user.email}: {e}")
                flash('Could not send reset email. Please try again later.', 'danger')
        else:
             # Generic message even if user doesn't exist or isn't verified, for security
             flash('If your email is registered and verified, a password reset link has been sent.', 'info')
        return redirect(url_for('auth.login')) # Redirect regardless to prevent enumeration
    return render_template('auth/reset_request.html', title='Reset Password', form=form)

# --- Password Reset Token Verification & Setting New Password ---
@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    # Find user by token (Must check expiry within verify_token)
    user = User.query.filter_by(password_reset_token=token).first()

    # verify_token handles expiry check and invalidates the token upon success
    if not user or not user.verify_token(token, purpose='password_reset'):
         flash('That is an invalid or expired password reset token.', 'warning')
         return redirect(url_for('auth.reset_request'))

    # If token is valid, show the password reset form
    form = ResetPasswordForm()
    if form.validate_on_submit():
        try:
            user.set_password(form.password.data)
            # Token already cleared by verify_token
            db.session.commit()
            flash('Your password has been updated! You can now log in.', 'success')
            # Log user in automatically after password reset? Optional.
            # login_user(user)
            return redirect(url_for('auth.login'))
        except Exception as e:
             db.session.rollback()
             current_app.logger.error(f"Password Reset Error for user {user.id}: {e}")
             flash('An error occurred updating your password. Please try again.', 'danger')


    return render_template('auth/reset_token.html', title='Set New Password', form=form, token=token)


# --- Google OAuth ---
@auth_bp.route('/login/google')
def login_google():
    oauth_config = get_google_oauth_config(current_app.config)
    if not all([oauth_config.get('client_id'), oauth_config.get('client_secret'), oauth_config.get('redirect_uri')]):
         current_app.logger.error("Google OAuth is not configured in .env file.")
         flash("Login with Google is currently unavailable.", 'danger')
         return redirect(url_for('auth.login'))

    # Generate state for CSRF protection
    state = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    session['oauth_state'] = state

    # Construct Google's authorization URL
    params = {
        'client_id': oauth_config['client_id'],
        'redirect_uri': oauth_config['redirect_uri'],
        'response_type': 'code',
        'scope': oauth_config['scope'],
        'state': state,
        'access_type': 'offline', # Request refresh token if needed later
        'prompt': 'select_account' # Force account selection
    }
    authorize_url = f"{oauth_config['authorize_url']}?{urlencode(params)}"
    return redirect(authorize_url)

@auth_bp.route('/callback/google')
def callback_google():
    oauth_config = get_google_oauth_config(current_app.config)
    
    if not oauth_config:
        # Should not happen if login_google checked, but defensive check
        flash("Google login configuration error.", 'danger')
        return redirect(url_for('auth.login'))
        
    # --- 1. State Verification (CSRF Protection) ---
    received_state = request.args.get('state')
    expected_state = session.pop('oauth_state', None)
    if not received_state or received_state != expected_state:
        flash('Invalid OAuth state. Login attempt rejected.', 'danger')
        return redirect(url_for('auth.login'))
    
    

    # --- 2. Handle OAuth Errors from Google ---
    if 'error' in request.args:
        error = request.args.get('error')
        error_desc = request.args.get('error_description', 'Unknown error.')
        current_app.logger.warning(f"Google OAuth Error: {error} - {error_desc}")
        flash(f"Google login failed: {error_desc}", 'danger')
        return redirect(url_for('auth.login'))

    # --- 3. Exchange Authorization Code for Tokens ---
    code = request.args.get('code')
    if not code:
         flash('Authorization code missing from Google callback.', 'danger')
         return redirect(url_for('auth.login'))

    token_payload = {
        'client_id': oauth_config['client_id'],
        'client_secret': oauth_config['client_secret'],
        'code': code,
        'grant_type': 'authorization_code',
        'redirect_uri': oauth_config['redirect_uri'],
    }
    try:
        token_response = requests.post(oauth_config['token_url'], data=token_payload, timeout=10)
        token_response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        token_json = token_response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Google token exchange request failed: {e}")
        flash('Failed to communicate with Google to exchange authorization code.', 'danger')
        return redirect(url_for('auth.login'))
    except json.JSONDecodeError:
        current_app.logger.error(f"Failed to decode Google token response: {token_response.text}")
        flash('Invalid token response received from Google.', 'danger')
        return redirect(url_for('auth.login'))

    access_token = token_json.get('access_token')
    if not access_token:
        current_app.logger.error(f"Access token missing in Google response: {token_json}")
        flash('Could not retrieve access token from Google.', 'danger')
        return redirect(url_for('auth.login'))

    # --- 4. Fetch User Info from Google ---
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        userinfo_response = requests.get(oauth_config['userinfo_url'], headers=headers, timeout=10)
        userinfo_response.raise_for_status()
        userinfo = userinfo_response.json()
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Google userinfo request failed: {e}")
        flash('Failed to fetch user information from Google.', 'danger')
        return redirect(url_for('auth.login'))
    except json.JSONDecodeError:
         current_app.logger.error(f"Failed to decode Google userinfo response: {userinfo_response.text}")
         flash('Invalid userinfo response received from Google.', 'danger')
         return redirect(url_for('auth.login'))


    google_id = userinfo.get('sub')
    email = userinfo.get('email')
    name = userinfo.get('name')
    is_email_verified_by_google = userinfo.get('email_verified', False)

    if not google_id or not email:
        flash('Required information (ID, Email) not received from Google.', 'danger')
        return redirect(url_for('auth.login'))

    # --- 5. Find or Create User in Database ---
    user = User.query.filter_by(google_id=google_id).first()
    new_user_scenario = False
    if not user:
        # If no user with this google_id, check if email exists
        user = User.query.filter_by(email=email).first()
        if user:
            # Email exists, link Google ID to existing account
            user.google_id = google_id
            # Mark email as verified if Google says so and it wasn't already
            if is_email_verified_by_google and not user.is_email_verified:
                user.is_email_verified = True
        else:
            # New user - need to ask for role
            new_user_scenario = True
            flash('New Google account detected. Please complete registration by selecting your role.', 'info')
            # Store partial info in session and redirect to a completion form
            session['google_oauth_info'] = {'google_id': google_id, 'email': email, 'name': name, 'is_email_verified': is_email_verified_by_google}
            return redirect(url_for('auth.complete_google_registration')) # Need this route/template

    # --- 6. Login User ---
    # If it's not a new user scenario (either found by google_id or linked existing email)
    if not new_user_scenario:
        try:
            user.last_login_at = datetime.utcnow()
            # Ensure email is marked verified if Google says so
            if is_email_verified_by_google and not user.is_email_verified:
                user.is_email_verified = True
            db.session.commit()
            login_user(user, remember=True) # Remember Google logins
            flash('Successfully logged in with Google!', 'success')
            # Redirect to intended page or dashboard
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('index'))
        except Exception as e:
             db.session.rollback()
             current_app.logger.error(f"Error finalizing Google login for user {email}: {e}")
             flash('An error occurred during login. Please try again.', 'danger')
             return redirect(url_for('auth.login'))
    else:
        # Should not reach here if new_user_scenario is True due to redirect above
        flash('An unexpected error occurred during Google login.', 'danger')
        return redirect(url_for('auth.login'))


# --- Route to complete registration after Google OAuth ---
@auth_bp.route('/complete_google_registration', methods=['GET', 'POST'])
def complete_google_registration():
    # Check if user is already logged in, maybe they completed registration in another tab
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if 'google_oauth_info' not in session:
        flash('Invalid registration step or session expired.', 'warning')
        return redirect(url_for('auth.login'))

    oauth_info = session['google_oauth_info']

    # Simple form just to select role (can be expanded)
    if request.method == 'POST':
        role = request.form.get('role')
        phone = request.form.get('phone') # Optional: ask for phone during completion

        if role not in ['worker', 'employer']:
            flash('Please select a valid role.', 'danger')
            # Pass name back to template for display
            return render_template('auth/complete_google.html', name=oauth_info.get('name', ''))

        # Optional Phone validation if requested
        if phone:
            import re
            phone_regex = r'^\+?91[ -]?\d{10}$'
            if not re.match(phone_regex, phone):
                 flash('Invalid phone number format. Use +91XXXXXXXXXX or similar.', 'danger')
                 return render_template('auth/complete_google.html', name=oauth_info.get('name', ''))
            existing_phone = User.query.filter_by(phone=phone).first()
            if existing_phone:
                flash('This phone number is already registered.', 'danger')
                return render_template('auth/complete_google.html', name=oauth_info.get('name', ''))


        try:
            # Check again if email or google_id exists (in case of race condition/reload)
            user = User.query.filter_by(email=oauth_info['email']).first() or \
                   User.query.filter_by(google_id=oauth_info['google_id']).first()

            if user:
                 # Account likely created in another session or linked already
                 flash('Account already exists or was linked. Please log in.', 'info')
                 session.pop('google_oauth_info', None) # Clear session data
                 return redirect(url_for('auth.login'))

            # Create the new user
            user = User(
                google_id=oauth_info['google_id'],
                email=oauth_info['email'],
                name=oauth_info.get('name'),
                is_email_verified=oauth_info.get('is_email_verified', False),
                role=role,
                phone=phone if phone else None,
                is_phone_verified=False # Phone needs OTP verification if provided
            )
            db.session.add(user)
            user.last_login_at = datetime.utcnow()
            db.session.commit()

            session.pop('google_oauth_info', None) # Clear session data
            login_user(user, remember=True) # Log the new user in
            flash('Registration complete! Welcome to ShramBandhu.', 'success')

            # Redirect to appropriate dashboard or profile completion if needed
            if user.role == 'worker' and not user.profile_completion < 100: # Example check
                 return redirect(url_for('worker.complete_profile'))
            return redirect(url_for('index')) # Redirect to main index (which redirects to dashboard)

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error completing Google registration for {oauth_info['email']}: {e}")
            flash('An error occurred during registration completion.', 'danger')
            return redirect(url_for('auth.login'))

    # GET request: Show the role selection form
    return render_template('auth/complete_google.html', name=oauth_info.get('name', ''))



# *** NEW: Phone Only Registration Route ***
@auth_bp.route('/register/phone', methods=['GET', 'POST'])
def register_phone():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    form = PhoneRegistrationForm()
    if form.validate_on_submit():
        phone = form.phone.data
        role = form.role.data

        existing_user = User.query.filter_by(phone=phone).first()

        if existing_user:
            # If user exists but isn't phone verified, maybe resend OTP?
            if not existing_user.is_phone_verified:
                try:
                    otp = existing_user.generate_otp()
                    db.session.commit()
                    message = f"Your ShramBandhu verification OTP is: {otp}. Valid for 5 minutes."
                    sms_sent = send_sms(phone, message)
                    if sms_sent:
                        flash('Phone number already exists but is unverified. A new OTP has been sent.', 'info')
                        session['otp_login_phone'] = phone # Use same session key as login for verify step
                        session['otp_verify_purpose'] = 'registration' # Optional: flag for verify step if needed
                        return redirect(url_for('auth.verify_login_otp')) # Redirect to the OTP entry page
                    else:
                        flash('Phone number already exists but failed to resend OTP. Please try again.', 'danger')
                except Exception as e:
                     db.session.rollback()
                     current_app.logger.error(f"OTP Resend Error for {phone}: {e}")
                     flash('An error occurred resending OTP.', 'danger')
            else:
                # User exists and is already verified
                flash('Phone number is already registered and verified. Please login.', 'warning')
                return redirect(url_for('auth.login_otp')) # Redirect to OTP login page
        else:
            # Phone number doesn't exist, create new user
            try:
                user = User(
                    phone=phone,
                    role=role,
                    is_phone_verified=False, # Verification happens via OTP
                    is_email_verified=False, # No email in this flow
                    is_active=True # Activate immediately, verification gates usage
                )
                # No password needed for phone-only registration/login flow
                otp = user.generate_otp() # Generate OTP for verification
                db.session.add(user)
                db.session.commit()

                # Send OTP
                message = f"Your ShramBandhu registration OTP is: {otp}. Valid for 5 minutes."
                sms_sent = send_sms(phone, message)
                if sms_sent:
                    flash('Registration initiated! Please enter the OTP sent to your phone.', 'success')
                    session['otp_login_phone'] = phone # Store phone for verification step
                    session['otp_verify_purpose'] = 'registration' # Optional flag
                    return redirect(url_for('auth.verify_login_otp')) # Use the same OTP verification page
                else:
                    # User created but OTP failed - allow retry later?
                    flash('Account created but failed to send OTP. Please try logging in via OTP later.', 'warning')
                    return redirect(url_for('auth.login_otp'))

            except Exception as e:
                db.session.rollback()
                current_app.logger.error(f"Phone Registration Error for {phone}: {e}")
                flash('An error occurred during registration. Please try again.', 'danger')

    # GET request or form validation failed
    return render_template('auth/register_phone.html', title='Register with Phone', form=form)




