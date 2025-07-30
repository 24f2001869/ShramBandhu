from flask import current_app, url_for, render_template
from flask_mail import Message
from shrambandhu.extensions import mail
import threading # For sending email asynchronously

def send_async_email(app, msg):
    """Helper function to send email in a background thread."""
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as e:
            app.logger.error(f"Failed to send email to {msg.recipients}: {e}")

def send_email(subject, recipients, text_body, html_body=None):
    """General function to send email asynchronously."""
    app = current_app._get_current_object() # Get the actual app instance
    msg = Message(
        subject,
        sender=app.config['MAIL_DEFAULT_SENDER'],
        recipients=recipients # Should be a list
    )
    msg.body = text_body
    if html_body:
        msg.html = html_body

    # Send email in a separate thread so it doesn't block the request
    thr = threading.Thread(target=send_async_email, args=[app, msg])
    thr.start()
    return thr # You could potentially join this thread later if needed

def send_verification_email(user, token):
    """Sends the email verification email."""
    try:
        # Ensure user object has an email attribute
        if not hasattr(user, 'email') or not user.email:
            current_app.logger.error(f"Attempted to send verification email to user {user.id} without email address.")
            return

        verification_url = url_for('auth.verify_email', token=token, _external=True)
        subject = "Verify Your Email Address - ShramBandhu"
        recipients = [user.email]

        # Consider creating simple text and HTML templates for these emails
        # templates/email/verify_email.txt
        # templates/email/verify_email.html
        text_body = f"""
        Welcome to ShramBandhu!

        To verify your email address and activate your account, please click the following link:
        {verification_url}

        If you did not create an account, please ignore this email.

        This link will expire in 1 hour.

        Thanks,
        The ShramBandhu Team
        """

        # Example using render_template (create the template file)
        html_body = render_template(
            'email/account_action.html', # Create a generic action email template
            title="Verify Your Email",
            user_name=user.name or 'User',
            action_text="Click the button below to verify your email address:",
            action_url=verification_url,
            button_text="Verify Email",
            info_text="If you did not create an account, please ignore this email. This link expires in 1 hour."
         )

        send_email(subject, recipients, text_body, html_body)
        current_app.logger.info(f"Verification email sent to {user.email}")

    except Exception as e:
        current_app.logger.error(f"Error sending verification email to {getattr(user, 'email', 'N/A')}: {e}")


def send_password_reset_email(user, token):
    """Sends the password reset email."""
    try:
        if not hasattr(user, 'email') or not user.email:
            current_app.logger.error(f"Attempted to send password reset to user {user.id} without email address.")
            return

        reset_url = url_for('auth.reset_token', token=token, _external=True)
        subject = "Password Reset Request - ShramBandhu"
        recipients = [user.email]

        text_body = f"""
        Hello {user.name or 'User'},

        Someone (hopefully you) requested a password reset for your ShramBandhu account.
        Click the link below to set a new password:
        {reset_url}

        If you did not request a password reset, please ignore this email. Your password will remain unchanged.

        This link will expire in 30 minutes.

        Thanks,
        The ShramBandhu Team
        """

        html_body = render_template(
             'email/account_action.html', # Reuse the generic template
             title="Reset Your Password",
             user_name=user.name or 'User',
             action_text="Click the button below to reset your password:",
             action_url=reset_url,
             button_text="Reset Password",
             info_text="If you did not request a password reset, please ignore this email. This link expires in 30 minutes."
         )

        send_email(subject, recipients, text_body, html_body)
        current_app.logger.info(f"Password reset email sent to {user.email}")

    except Exception as e:
        current_app.logger.error(f"Error sending password reset email to {getattr(user, 'email', 'N/A')}: {e}")