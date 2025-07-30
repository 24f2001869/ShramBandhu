# shrambandhu/auth/forms.py (Complete File)

from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, BooleanField, SelectField, TelField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, Regexp
from shrambandhu.models import User # Import User model to check existence
from sqlalchemy import func # Import func for case-insensitive queries
import re # Import re for regex

# Custom validator for phone number format (adjust regex as needed for India)
# Allows optional +91, optional space/hyphen, then 10 digits
phone_regex = r'^(\+91[\-\s]?)?[6-9]\d{9}$'

# --- Custom Validators (Keep these if defined before) ---
# def validate_phone_format(form, field): # Integrated into Regexp
#     if not re.match(phone_regex, field.data):
#         raise ValidationError('Invalid phone number format. Use +91XXXXXXXXXX or 91XXXXXXXXXX.')

# def validate_phone_exists(form, field): # Check done in route or RegistrationForm
#     if User.query.filter_by(phone=field.data, is_phone_verified=True).first():
#         raise ValidationError('Phone number already registered and verified.')

# def validate_email_exists(form, field): # Check done in route or RegistrationForm
#     if User.query.filter_by(email=field.data, is_email_verified=True).first():
#         raise ValidationError('Email address already registered and verified.')
# --- End Custom Validators ---


class RegistrationForm(FlaskForm):
    """Form for user registration (Email/Password or Phone)."""
    name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    phone = TelField('Phone Number (+91XXXXXXXXXX)', validators=[DataRequired(), Regexp(phone_regex, message="Invalid Indian phone number format.")])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password', message='Passwords must match.')])
    role = SelectField('I am registering as a:', choices=[('worker', 'Worker'), ('employer', 'Employer')], validators=[DataRequired()])
    submit = SubmitField('Register')

    # Custom validation to check if email or phone already exists
    def validate_email(self, email):
        user = User.query.filter(func.lower(User.email) == func.lower(email.data)).first() # Case-insensitive check
        if user:
            raise ValidationError('That email is already registered. Please choose a different one or login.')

    def validate_phone(self, phone):
        # Normalize phone number before checking? (e.g., remove +91, spaces)
        # This depends on how you store it. Assuming stored with +91 for now.
        # A more robust check might involve formatting the input first.
         user = User.query.filter_by(phone=phone.data).first()
         if user:
             raise ValidationError('That phone number is already registered. Please choose a different one or login.')


class LoginForm(FlaskForm):
    """Form for user login using Email/Password."""
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Login')


class OTPLoginForm(FlaskForm):
    """Form for initiating login via Phone OTP."""
    phone = TelField('Phone Number (+91XXXXXXXXXX)', validators=[DataRequired(), Regexp(phone_regex, message="Invalid Indian phone number format.")])
    submit = SubmitField('Send OTP')

    # Validator moved to route logic usually, but can be kept here
    def validate_phone(self, phone):
        user = User.query.filter_by(phone=phone.data).first()
        if not user:
            raise ValidationError('Phone number not found. Please register first.')
        # Optional: Check if phone is verified
        # if not user.is_phone_verified:
        #      raise ValidationError('Phone number not verified.')


class VerifyOTPForm(FlaskForm):
    """Form for verifying OTP."""
    # Ensure OTP length matches what your generate_otp function creates
    otp = StringField('Enter OTP', validators=[DataRequired(), Length(min=6, max=6, message="OTP must be 6 digits.")])
    submit = SubmitField('Verify OTP')


class RequestPasswordResetForm(FlaskForm):
    """Form to request a password reset email."""
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')

    def validate_email(self, email):
        user = User.query.filter(func.lower(User.email) == func.lower(email.data)).first() # Case-insensitive
        if not user:
            # Avoid revealing if email exists, show generic message in route
            pass # Validation done in route is better for security here
        # elif not user.is_email_verified:
        #     raise ValidationError('Email not verified. Please verify your email first.')


class ResetPasswordForm(FlaskForm):
    """Form to reset password using a token."""
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('password', message='Passwords must match.')])
    submit = SubmitField('Reset Password')



class PhoneRegistrationForm(FlaskForm):
    """Form for registering with only Phone and Role."""
    phone = TelField('Phone Number (+91XXXXXXXXXX)', validators=[DataRequired(), Regexp(phone_regex, message="Invalid Indian phone number format.")])
    role = SelectField('I am registering as a:', choices=[('worker', 'Worker'), ('employer', 'Employer')], validators=[DataRequired()])
    submit = SubmitField('Register with Phone')

    # Optional: Add phone existence validation here too if desired
    def validate_phone(self, phone):
        user = User.query.filter_by(phone=phone.data).first()
        if user:
            # Check if they just need to verify or if already fully registered
            if user.is_phone_verified:
                 raise ValidationError('Phone number already registered and verified. Please login instead.')
            else:
                 # Allow re-sending OTP if unverified? Or handle in route.
                 # For now, let route handle existing unverified user.
                 pass # Let route logic decide
