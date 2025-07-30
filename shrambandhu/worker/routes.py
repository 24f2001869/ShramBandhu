# shrambandhu/worker/routes.py
from flask import (
    Blueprint, render_template, request, flash, redirect, url_for, jsonify,
    current_app, session, send_from_directory, abort
)
from flask_login import current_user, login_required
from shrambandhu.models import (
    User, Job, Application, EmergencyAlert, Certification, WorkerCertification,
    Payment, DocumentVerification, Notification, Rating # Added Rating
)
from datetime import datetime, timedelta
from shrambandhu.utils.location import (
    get_nearby_jobs, get_nearest_responders, get_hospitals_near_location,
    calculate_distance
)
from shrambandhu.utils.twilio_client import send_whatsapp_message, send_sms # Kept send_sms
from shrambandhu.voice.stt import transcribe_audio, extract_worker_details
from shrambandhu.extensions import db
from .forms import ProfileForm, DocumentUploadForm , JobSearchForm # Added JobSearchForm
import json
import os
from werkzeug.utils import secure_filename
import tempfile # For saving temporary audio blob
from sqlalchemy import or_ , desc, asc , and_ , func , case # For SQLAlchemy queries
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload , load_only

# Create the Blueprint
# Ensure template_folder points correctly relative to the Blueprint's location
worker_bp = Blueprint('worker', __name__, template_folder='../templates/worker', static_folder='../static')

# --- Serve uploaded files routes ---
@worker_bp.route('/documents/view/<path:filename>')
@login_required
def uploaded_document(filename):
    # Basic check: Does the logged-in user own this document OR is the user an admin?
    parts = filename.split(os.path.sep)
    if len(parts) < 2: return "Invalid file path", 400
    try: owner_id = int(parts[0])
    except ValueError: return "Invalid file path owner", 400

    # Permission Check
    is_owner = (current_user.id == owner_id)
    is_admin = (current_user.role == 'admin')

    if not is_owner and not is_admin:
         flash('You do not have permission to view this document.', 'danger')
         # Redirect to a safe place
         return redirect(url_for('worker.profile') if current_user.role == 'worker' else url_for('index'))

    base_documents_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'documents')
    try:
        # Pass directory and the filename (including user_id subfolder) separately
        return send_from_directory(base_documents_path, filename, as_attachment=False)
    except FileNotFoundError:
        current_app.logger.error(f"Document file not found: {os.path.join(base_documents_path, filename)}")
        return "File not found", 404
    except Exception as e:
        current_app.logger.error(f"Error serving document {filename}: {e}")
        return "Error serving file", 500


@worker_bp.route('/cert_docs/view/<path:filename>')

def uploaded_cert_document(filename):
    # Assuming filename includes user_id subdirectory like "user_id/cert_file.pdf"
    parts = filename.split(os.path.sep)
    if len(parts) < 2: return "Invalid file path", 400
    try: owner_id = int(parts[0])
    except ValueError: return "Invalid file path owner", 400

    if not (current_user.id == owner_id or current_user.role == 'admin' or current_user.role == 'employer' ):
        flash('Permission denied.', 'danger')
        return redirect(url_for('index'))

    base_certs_path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'cert_docs')
    try:
        return send_from_directory(base_certs_path, filename, as_attachment=False)
    except FileNotFoundError:
        current_app.logger.error(f"Cert Document file not found: {os.path.join(base_certs_path, filename)}")
        return "File not found", 404
    except Exception as e:
        current_app.logger.error(f"Error serving cert doc {filename}: {e}")
        return "Error serving file", 500


# --- Dashboard Route (Updated) ---
@worker_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'worker':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

    # --- Get Worker Location and Skills ---
    worker_location = None
    location_set = False
    if current_user.location_lat and current_user.location_lng:
        worker_location = (current_user.location_lat, current_user.location_lng)
        location_set = True
    worker_skills = current_user.get_skills_list()

    # --- Get Nearby Jobs ---
    nearby_jobs = []
    if location_set:
        nearby_jobs = get_nearby_jobs(worker_location, worker_skills, max_distance_km=25)
    else:
        flash('Please set your location in your profile to find nearby jobs.', 'info')

    # --- Get Dashboard Stats ---
    # Active Applications Count
    active_applications_count = current_user.worker_applications.filter(
        Application.status.in_(['applied', 'shortlisted'])
    ).count()

    # Certifications Summary
    verified_certs_count = current_user.worker_certifications.filter_by(verification_status='verified').count()
    pending_certs_count = current_user.worker_certifications.filter_by(verification_status='pending').count()

    # Document Verification Summary
    pending_docs_count = current_user.document_verifications.filter_by(status='pending').count()
    rejected_docs_count = current_user.document_verifications.filter_by(status='rejected').count()

    # Recent Payments (limit to 3 for dashboard display)
    recent_payments = Payment.query.filter_by(worker_id=current_user.id)\
                                .options(db.joinedload(Payment.job), db.joinedload(Payment.employer))\
                                .order_by(Payment.created_at.desc())\
                                .limit(3).all()

    # Profile Completion
    profile_completion = current_user.profile_completion

    # Overall Verification Status (using the property)
    is_verified = current_user.is_fully_verified # Use the property check

    # Quick Stats for Top Cards (can reuse some from above)
    stats = {
        'active_applications': active_applications_count,
        'verified_certs': verified_certs_count,
        'completed_jobs': current_user.completed_jobs_count, # Use property
        'avg_rating': current_user.average_rating # Use property
    }

    # Verification Summary for Card
    verification_summary = {
        'pending_docs': pending_docs_count,
        'rejected_docs': rejected_docs_count,
        'pending_certs': pending_certs_count,
        'is_fully_verified': is_verified
    }
     
    profile_views_count = current_user.profile_views

    return render_template(
        'dashboard.html', # templates/worker/dashboard.html
        stats=stats,
        nearby_jobs=nearby_jobs[:5], # Show limited jobs on dashboard
        recent_payments=recent_payments,
        profile_completion=profile_completion,
        location_set=location_set,
        verification_summary=verification_summary,
        profile_views_count=profile_views_count
    )

# --- Complete/Update Profile Route ---
@worker_bp.route('/complete-profile', methods=['GET', 'POST'])
@login_required
def complete_profile():
    if current_user.role != 'worker':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

    user = User.query.get_or_404(current_user.id)

    if request.method == 'POST':
        # Check if it's audio data submission (expected from JS)
        if 'audio_blob' in request.files:
            audio_file = request.files['audio_blob']
            if audio_file.filename != '':
                # Use a temporary file to save the blob for transcription
                temp_dir = tempfile.gettempdir()
                # Ensure filename has an extension stt library might need (e.g., .ogg, .wav)
                # The JS should ideally send the correct mime type / extension. Assume .ogg for now.
                temp_filename = f"user_{user.id}_reg_voice_{int(datetime.utcnow().timestamp())}.ogg"
                temp_filepath = os.path.join(temp_dir, temp_filename)

                try:
                    audio_file.save(temp_filepath)
                    current_app.logger.info(f"Saved temporary voice file for transcription: {temp_filepath}")

                    # Transcribe and extract details (Ensure GOOGLE_APPLICATION_CREDENTIALS is set)
                    transcript = transcribe_audio(temp_filepath) # Assuming takes filepath
                    current_app.logger.info(f"Transcription result for user {user.id}: {transcript}")
                    details = extract_worker_details(transcript) # Expects {'name': ..., 'skills': [...]}

                    # Update user profile from voice
                    if details.get('name'): user.name = details['name']
                    if details.get('skills'): user.set_skills_list(details['skills'])

                    # Optionally save the voice file permanently (adjust path)
                    perm_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'voice_samples', str(user.id))
                    os.makedirs(perm_folder, exist_ok=True)
                    perm_filename = f"voice_reg_{int(datetime.utcnow().timestamp())}.ogg"
                    perm_filepath = os.path.join(perm_folder, perm_filename)
                    os.rename(temp_filepath, perm_filepath) # Move temp file
                    user.voice_sample_path = os.path.join(str(user.id), perm_filename) # Store relative path

                    db.session.commit()
                    flash('Profile updated using voice registration!', 'success')
                    return jsonify({'status': 'success', 'redirect': url_for('worker.dashboard')}) # Respond to JS fetch

                except Exception as e:
                    db.session.rollback()
                    current_app.logger.error(f"Voice registration processing error for user {user.id}: {e}", exc_info=True)
                    flash('Error processing voice registration. Please try again or fill manually.', 'danger')
                     # Clean up temp file on error
                    if os.path.exists(temp_filepath):
                         try: os.remove(temp_filepath)
                         except OSError: pass
                    return jsonify({'status': 'error', 'message': 'Error processing audio.'}), 500
                finally:
                    # Ensure temp file is removed if rename didn't happen (e.g., STT failed before move)
                    if os.path.exists(temp_filepath):
                         try: os.remove(temp_filepath)
                         except OSError: pass

            else: # Empty audio file received
                 return jsonify({'status': 'error', 'message': 'No audio data received.'}), 400

        # Handle standard form submission (Name/Skills manual input)
        else:
            # Using request.form directly as no WTForm is explicitly defined for this page yet
            name = request.form.get('name')
            skills_str = request.form.get('skills')
            try:
                if name: user.name = name
                if skills_str is not None: user.set_skills_list(skills_str.split(','))
                db.session.commit()
                flash('Profile updated manually!', 'success')
                return redirect(url_for('worker.dashboard')) # Redirect for standard form post
            except Exception as e:
                 db.session.rollback()
                 current_app.logger.error(f"Manual profile update error for user {user.id}: {e}")
                 flash('An error occurred updating profile.', 'danger')
                 # Need to render template again with error
                 return render_template('complete_profile.html', user=user)

    # GET request
    return render_template('complete_profile.html', user=user)

# --- Worker Profile View/Edit Route (Updated for Phone) ---
@worker_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if current_user.role != 'worker': flash('Access denied.', 'danger'); return redirect(url_for('index'))

    user = User.query.get_or_404(current_user.id)
    form = ProfileForm(obj=user) # Load existing data into form

    # Pre-populate skills correctly for GET request
    if request.method == 'GET':
        form.skills.data = ', '.join(user.get_skills_list())
        # Keep existing phone number in the form field for display
        form.phone.data = user.phone

    if form.validate_on_submit():
        phone_changed = False
        new_phone = form.phone.data.strip() if form.phone.data else None
        original_phone = user.phone

        # --- Phone Number Logic ---
        if new_phone and new_phone != original_phone:
            # Check if this new number is already used and verified by another user
            existing_verified_user = User.query.filter(
                User.phone == new_phone,
                User.is_phone_verified == True,
                User.id != user.id # Exclude the current user
            ).first()

            if existing_verified_user:
                flash('This phone number is already registered and verified by another user.', 'danger')
                # Re-render form, keeping submitted data (form keeps track)
                user_documents = user.document_verifications.order_by(DocumentVerification.created_at.desc()).all()
                return render_template('profile.html', title='My Profile', form=form, user=user, documents=user_documents)
            else:
                # Phone number is new or belongs to an unverified user or current user
                user.phone = new_phone
                user.is_phone_verified = False # Mark as unverified
                phone_changed = True
                flash('Phone number updated. Please verify it using the OTP sent.', 'info')
        elif not new_phone and original_phone:
            # User cleared the phone field - handle as needed (e.g., disallow? keep old? clear?)
            # For now, let's assume clearing means they don't want a phone attached anymore
            user.phone = None
            user.is_phone_verified = False
            phone_changed = True # Consider this a change
            flash('Phone number removed.', 'info')
        # --- End Phone Number Logic ---

        # --- Update other fields ---
        user.name = form.name.data
        user.set_skills_list(form.skills.data.split(','))
        user.experience_years = form.experience_years.data
        # Handle location update (keep from previous step)
        latitude_str = request.form.get('latitude'); longitude_str = request.form.get('longitude'); address_str = request.form.get('location_address')
        if latitude_str and longitude_str:
            try: user.location_lat = float(latitude_str); user.location_lng = float(longitude_str); user.location_address = address_str; user.location_updated_at = datetime.utcnow()
            except ValueError: flash('Invalid location coordinates.', 'warning')
        # --- End Update other fields ---

        try:
            db.session.commit() # Commit all changes

            # If phone changed and needs verification, send OTP and redirect
            if phone_changed and user.phone and not user.is_phone_verified:
                 try:
                     otp = user.generate_otp()
                     db.session.commit() # Save OTP
                     message = f"Your ShramBandhu verification OTP is: {otp}. Valid for 5 minutes."
                     sms_sent = send_sms(user.phone, message)
                     if sms_sent:
                         session['otp_login_phone'] = user.phone # Store phone for verification
                         session['otp_verify_purpose'] = 'profile_update' # Specific purpose
                         flash('OTP sent to your new phone number. Please enter it below.', 'info')
                         return redirect(url_for('auth.verify_login_otp', next=url_for('worker.profile'))) # Redirect to verify, then back to profile
                     else:
                         flash('Phone number updated, but failed to send verification OTP. Please try verifying later.', 'warning')
                 except Exception as e:
                     db.session.rollback() # Rollback OTP generation if SMS fails maybe?
                     current_app.logger.error(f"Failed sending OTP for profile update to {user.phone}: {e}")
                     flash('Phone number updated, but failed to send verification OTP due to an error.', 'warning')

            if not phone_changed: # Only flash success if phone wasn't the main update needing OTP
                flash('Profile updated successfully!', 'success')

            return redirect(url_for('worker.profile')) # Redirect back to profile

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Profile update error for user {user.id}: {e}", exc_info=True)
            flash('An error occurred while updating your profile.', 'danger')

    # GET request or POST validation failed
    user_documents = user.document_verifications.order_by(DocumentVerification.created_at.desc()).all()
    return render_template('profile.html', title='My Profile', form=form, user=user, documents=user_documents)

# --- NEW ROUTE: Resend OTP for Profile Phone Verification ---
@worker_bp.route('/profile/resend-otp', methods=['POST'])
@login_required
def resend_profile_phone_otp():
    if current_user.role != 'worker': abort(403)

    user = User.query.get_or_404(current_user.id)

    if user.is_phone_verified or not user.phone:
        flash('Phone number is already verified or not set.', 'warning')
        return redirect(url_for('worker.profile'))

    try:
        otp = user.generate_otp()
        db.session.commit()
        message = f"Your ShramBandhu verification OTP is: {otp}. Valid for 5 minutes."
        sms_sent = send_sms(user.phone, message)
        if sms_sent:
            flash('A new verification OTP has been sent to your phone number.', 'info')
            # Redirect to verification page? Or stay on profile? Redirect for entering OTP.
            session['otp_login_phone'] = user.phone
            session['otp_verify_purpose'] = 'profile_update'
            return redirect(url_for('auth.verify_login_otp', next=url_for('worker.profile')))
        else:
            flash('Failed to resend OTP. Please try again later.', 'danger')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"OTP Resend Error for profile {user.phone}: {e}")
        flash('An error occurred resending OTP.', 'danger')

    return redirect(url_for('worker.profile'))

# --- Apply for Job ---
@worker_bp.route('/apply/<int:job_id>', methods=['POST'])
@login_required
def apply(job_id):
    if current_user.role != 'worker':
        flash('Only workers can apply for jobs.', 'danger')
        return redirect(url_for('index'))

    job = Job.query.get_or_404(job_id)
    if job.status != 'active':
        flash(f"This job ('{job.title}') is no longer active.", 'warning')
        return redirect(url_for('worker.dashboard'))

    existing_application = Application.query.filter_by(job_id=job.id, worker_id=current_user.id).first()

    if existing_application:
        if existing_application.status != 'withdrawn':
            flash(f"You have already applied for '{job.title}'. Status: {existing_application.status}", 'warning')
            return redirect(url_for('worker.dashboard'))
        else:
            # Re-apply logic: update the status
            existing_application.status = 'applied'
            existing_application.applied_at = datetime.utcnow()  # Optional: update timestamp
    else:
        # Check profile completeness only for new applications
        if current_user.profile_completion < 50:
            flash("Please complete your profile before applying.", 'warning')
            return redirect(url_for('worker.profile'))

        existing_application = Application(job_id=job.id, worker_id=current_user.id, status='applied')
        db.session.add(existing_application)

    try:
        db.session.commit()

        # Notify employer
        employer = job.employer
        if employer:
            notification = Notification(
                user_id=employer.id,
                title="New Job Application",
                message=f"Application received for '{job.title}' from {current_user.name or current_user.phone}.",
                link_url=url_for('employer.view_applications', job_id=job.id, _external=True)
            )
            db.session.add(notification)
            db.session.commit()
        else:
            current_app.logger.warning(f"Employer not found for job {job.id}")

        flash(f'Successfully applied for "{job.title}"!', 'success')

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error applying for job {job_id} by user {current_user.id}: {e}", exc_info=True)
        flash('An error occurred while submitting your application.', 'danger')

    return redirect(url_for('worker.dashboard'))


# --- Emergency SOS ---
@worker_bp.route('/sos', methods=['POST'])
@login_required # Ensures user is logged in
def trigger_sos():
    # Double-check role just in case
    if current_user.role != 'worker':
        current_app.logger.warning(f"Non-worker user {current_user.id} attempted SOS.")
        return jsonify({'success': False, 'error': 'Unauthorized action'}), 403

    # Get location data safely
    data = request.get_json(silent=True) # Use silent=True to avoid request errors if not JSON
    if not data:
        current_app.logger.error("SOS request received without JSON data.")
        return jsonify({'success': False, 'error': 'Invalid request format'}), 400

    lat = data.get('lat')
    lng = data.get('lng')

    if not lat or not lng:
        current_app.logger.error(f"SOS request from user {current_user.id} missing lat/lng.")
        return jsonify({'success': False, 'error': 'Location coordinates required'}), 400

    try:
        # Create emergency alert record
        alert = EmergencyAlert(
            worker_id=current_user.id,
            location_lat=lat,
            location_lng=lng,
            status='active' # Explicitly set status
        )
        db.session.add(alert)
        db.session.commit()
        current_app.logger.info(f"SOS Alert ID {alert.id} created for worker {current_user.id} at ({lat}, {lng}).")

    except SQLAlchemyError as e:
        db.session.rollback()
        current_app.logger.error(f"Database error creating SOS alert for worker {current_user.id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Database error saving alert.'}), 500
    except Exception as e:
        db.session.rollback() # Rollback for any other unexpected error during DB interaction
        current_app.logger.error(f"Unexpected error creating SOS alert for worker {current_user.id}: {e}", exc_info=True)
        return jsonify({'success': False, 'error': 'Failed to record SOS alert.'}), 500

    # --- Alert Notification Logic ---
    # This part can also fail, so wrap it
    responders_contacted_count = 0
    try:
        # Get nearest responders (add error handling within get_nearest_responders if needed)
        responders = get_nearest_responders((lat, lng), radius_km=10) # Increased radius maybe
        admins = User.query.filter_by(role='admin', is_active=True).all()
        all_recipients = responders + admins
        sent_to = set() # Avoid duplicate messages

        Maps_link = f"https://www.google.com/maps?q={lat},{lng}" # Use standard Google Maps link
        message = f"🚨 EMERGENCY SOS 🚨\nWorker: {current_user.name or 'Unknown'} ({current_user.phone})\nLocation: {Maps_link}\nTime: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"

        for recipient in all_recipients:
            # Ensure recipient is valid, not the worker themselves, and not already notified
            if recipient and recipient.phone and recipient.id != current_user.id and recipient.id not in sent_to:
                sms_sent = send_sms(recipient.phone, message) # send_sms should handle its own errors and return None/False on failure
                if sms_sent:
                    responders_contacted_count += 1
                    sent_to.add(recipient.id)
                    current_app.logger.info(f"SOS Alert {alert.id}: Sent SMS to {recipient.phone}")
                else:
                    current_app.logger.warning(f"SOS Alert {alert.id}: Failed to send SMS to {recipient.phone}")

        current_app.logger.info(f"SOS Alert {alert.id}: Notified {responders_contacted_count} responders/admins.")

    except Exception as e:
        # Log error during notification but don't necessarily fail the whole request,
        # as the alert *was* recorded in the database.
        current_app.logger.error(f"Error during SOS notification phase for Alert ID {alert.id}: {e}", exc_info=True)
        # Optionally, you could return success=False here if notifications are critical

    # Return success even if some notifications failed, as the alert is logged
    return jsonify({
        'success': True,
        'alert_id': alert.id,
        'responders_contacted': responders_contacted_count
    }), 200 # OK status

@worker_bp.route('/sos/status/<int:alert_id>')
@login_required
def check_sos_status(alert_id):
    alert = EmergencyAlert.query.get_or_404(alert_id)
    # Allow worker or admin to check status
    if not (alert.worker_id == current_user.id or current_user.role == 'admin'):
        return jsonify({'error': 'Unauthorized'}), 403

    return jsonify({
        'status': alert.status,
        'created_at': alert.created_at.isoformat() + 'Z', # ISO format UTC
        'resolved_at': alert.resolved_at.isoformat() + 'Z' if alert.resolved_at else None
    })


# --- Emergency Resources ---
@worker_bp.route('/emergency-resources')
@login_required
def emergency_resources():
    user_location = (current_user.location_lat, current_user.location_lng) if current_user.location_lat else None
    hospitals = get_hospitals_near_location(user_location, radius_km=10) if user_location else []
    return render_template('emergency_resources.html', hospitals=hospitals)


# --- Certifications ---
@worker_bp.route('/certifications')
@login_required
def my_certifications():
    if current_user.role != 'worker': return redirect(url_for('index'))
    # Eager load related certification details
    certs = current_user.worker_certifications.options(db.joinedload(WorkerCertification.certification)).order_by(WorkerCertification.certified_at.desc()).all()
    return render_template('certifications.html', certifications=certs)

@worker_bp.route('/certifications/add', methods=['GET', 'POST'])
@login_required
def add_certification():
    if current_user.role != 'worker': return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            cert_id = request.form.get('certification_id')
            document = request.files.get('document')

            if not cert_id or not document or not document.filename:
                flash('Certification type and document file are required.', 'danger')
                return redirect(url_for('worker.add_certification'))

            cert_info = Certification.query.get(cert_id)
            if not cert_info:
                flash('Invalid Certification Type selected.', 'danger')
                return redirect(url_for('worker.add_certification'))

            # Save document
            user_cert_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'cert_docs', str(current_user.id))
            os.makedirs(user_cert_folder, exist_ok=True)
            filename_base = secure_filename(f"cert_{cert_info.name.replace(' ','_')}_{current_user.id}_{int(datetime.utcnow().timestamp())}")
            filename_ext = os.path.splitext(document.filename)[1].lower()
            if not ('.' in document.filename and filename_ext[1:] in current_app.config['ALLOWED_EXTENSIONS']):
                 flash('Invalid file type for certification.', 'danger')
                 return redirect(url_for('worker.add_certification'))

            filename = f"{filename_base}{filename_ext}"
            file_save_path = os.path.join(user_cert_folder, filename)
            document.save(file_save_path)
            relative_path = os.path.join(str(current_user.id), filename)

            # Calculate expiry
            expires_at = None
            if cert_info.validity_months and cert_info.validity_months > 0:
                expires_at = datetime.utcnow() + timedelta(days=cert_info.validity_months * 30) # Approx

            worker_cert = WorkerCertification(
                worker_id=current_user.id,
                certification_id=cert_id,
                document_path=relative_path,
                expires_at=expires_at,
                verification_status='pending'
            )
            db.session.add(worker_cert)
            db.session.commit()
            flash('Certification submitted for verification!', 'success')
            return redirect(url_for('worker.my_certifications'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Add certification error for user {current_user.id}: {e}", exc_info=True)
            flash(f'Error submitting certification: {str(e)}', 'danger')

    # GET request
    available_certifications = Certification.query.order_by(Certification.name).all()
    return render_template('add_certification.html', certifications=available_certifications)

# --- Document Verification Upload (Worker) ---
@worker_bp.route('/documents/upload', methods=['GET', 'POST'])
@login_required
def upload_document():
     if current_user.role != 'worker':
         flash('Access denied.', 'danger')
         return redirect(url_for('index'))

     form = DocumentUploadForm()
     if form.validate_on_submit():
        doc_type = form.document_type.data
        doc_number = form.document_number.data
        doc_file = form.document_file.data

        # Prevent re-submission if pending/verified
        existing_doc = DocumentVerification.query.filter_by(
            user_id=current_user.id, document_type=doc_type
        ).filter(DocumentVerification.status.in_(['pending', 'verified'])).first()
        if existing_doc:
            flash(f"You have already submitted a '{doc_type.replace('_',' ').title()}' which is currently '{existing_doc.status}'.", 'warning')
            return redirect(url_for('worker.profile'))

        try:
            user_doc_folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'documents', str(current_user.id))
            os.makedirs(user_doc_folder, exist_ok=True)
            filename_base = secure_filename(f"{doc_type}_{current_user.id}_{int(datetime.utcnow().timestamp())}")
            filename_ext = os.path.splitext(doc_file.filename)[1].lower()
            filename = f"{filename_base}{filename_ext}"
            # Path validation done by FileAllowed validator in form

            file_save_path = os.path.join(user_doc_folder, filename)
            doc_file.save(file_save_path)
            relative_path = os.path.join(str(current_user.id), filename)

            new_verification = DocumentVerification(
                user_id=current_user.id, document_type=doc_type,
                document_number=doc_number, file_path=relative_path, status='pending'
            )
            db.session.add(new_verification)
            db.session.commit()
            flash(f'{doc_type.replace("_", " ").title()} uploaded successfully for verification.', 'success')
            return redirect(url_for('worker.profile'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Document upload error for user {current_user.id}: {e}", exc_info=True)
            if 'file_save_path' in locals() and os.path.exists(file_save_path):
                 try: os.remove(file_save_path)
                 except OSError: pass
            flash('An error occurred uploading the document.', 'danger')

     # GET request
     user_documents = DocumentVerification.query.filter_by(user_id=current_user.id).order_by(DocumentVerification.created_at.desc()).all()
     return render_template('upload_document.html', title='Upload Verification Document', form=form, documents=user_documents)


# --- Payment History ---
@worker_bp.route('/payments')
@login_required
def payment_history():
    if current_user.role != 'worker': return redirect(url_for('index'))
    page = request.args.get('page', 1, type=int)
    per_page = 15
    payments_pagination = Payment.query.filter_by(worker_id=current_user.id)\
                                  .options(db.joinedload(Payment.job), db.joinedload(Payment.employer))\
                                  .order_by(Payment.created_at.desc())\
                                  .paginate(page=page, per_page=per_page, error_out=False)
    return render_template('payment_history.html', payments_pagination=payments_pagination)


# --- Verify/Dispute Payment Recorded by Employer ---
@worker_bp.route('/payments/<int:payment_id>/verify', methods=['POST'])
@login_required
def verify_payment(payment_id):
     if current_user.role != 'worker': return redirect(url_for('index'))

     payment = Payment.query.filter_by(id=payment_id, worker_id=current_user.id).first_or_404()

     if payment.status != 'pending':
          flash(f'This payment is already marked as {payment.status}.', 'warning')
          return redirect(url_for('worker.payment_history'))

     action = request.form.get('action') # 'confirm' or 'dispute'

     try:
        if action == 'confirm':
             payment.status = 'verified'
             payment.verified_at = datetime.utcnow()
             # Maybe notify employer?
             flash('Payment confirmed successfully!', 'success')
        elif action == 'dispute':
             payment.status = 'disputed'
             # Add reason if form includes it: payment.rejection_reason = request.form.get('reason')
             # Notify Employer and Admin
             flash('Payment disputed. Admin will review.', 'warning')
             # Create notification for admin
             admins = User.query.filter_by(role='admin').all()
             for admin in admins:
                 if admin:
                     notification = Notification(
                         user_id=admin.id,
                         title="Payment Dispute Raised",
                         message=f"Worker {current_user.name or current_user.phone} disputed payment ID {payment.id} for job '{payment.job.title}'.",
                         link_url=url_for('admin.payment_disputes', _external=True) # Link to admin dispute page
                     )
                     db.session.add(notification)
        else:
             flash('Invalid action.', 'danger')
             return redirect(url_for('worker.payment_history'))

        db.session.commit()
     except Exception as e:
         db.session.rollback()
         current_app.logger.error(f"Error verifying/disputing payment {payment_id} by user {current_user.id}: {e}")
         flash('An error occurred processing the payment action.', 'danger')

     return redirect(url_for('worker.payment_history'))


# --- Public Profile Route (Updated to Increment Views) ---
@worker_bp.route('/public/<int:worker_id>')
# No login required to view public profile, but we check viewer inside
def public_profile(worker_id):
    # Fetch only necessary columns initially to check existence and role
    worker = User.query.options(load_only(User.id, User.role, User.is_active)).filter_by(id=worker_id).first_or_404()

    # Ensure it's an active worker profile
    if worker.role != 'worker' or not worker.is_active:
        abort(404)

    # --- Increment View Count Logic ---
    increment_count = False
    if current_user.is_authenticated:
        # Only increment if viewer is authenticated, is an employer, and is NOT viewing their own profile
        if current_user.id != worker.id and current_user.role == 'employer':
            increment_count = True
            # Optional: Add session/timestamp logic here to prevent rapid increments from same employer
    else:
        # Decide if anonymous views should count (less reliable)
        # For now, let's only count views by logged-in employers
        pass

    if increment_count:
        try:
            # Fetch the full worker object only if we need to increment
            worker_to_update = User.query.get(worker_id) # Get full object for update
            if worker_to_update: # Should exist, but double check
                worker_to_update.profile_views = (worker_to_update.profile_views or 0) + 1
                db.session.commit()
                current_app.logger.info(f"Profile view count for worker {worker_id} incremented by employer {current_user.id}")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error incrementing profile view count for worker {worker_id}: {e}")
    # --- End Increment Logic ---

    # Fetch full worker details for display after potential increment
    # We re-fetch or use worker_to_update if available to get the latest count
    display_worker = User.query.options(
        db.selectinload(User.ratings_received).joinedload(Rating.employer), # Load ratings+employer
        db.selectinload(User.ratings_received).joinedload(Rating.job), # Load ratings+job
        db.selectinload(User.worker_certifications).joinedload(WorkerCertification.certification) # Load certs+details
    ).get(worker_id)

    if not display_worker: # Should not happen if first query worked, but safety check
        abort(404)

    # Get ratings (already loaded potentially via selectinload)
    # Sort in Python if needed, limit display
    ratings_to_display = sorted(display_worker.ratings_received, key=lambda r: r.created_at, reverse=True)[:10]

    # Get verified certifications (already loaded potentially)
    verified_certs = [wc for wc in display_worker.worker_certifications if wc.verification_status == 'verified']

    return render_template(
        'public_profile.html',
        worker=display_worker,
        ratings=ratings_to_display,
        verified_certs=verified_certs
    )

# +++ NEW: Find Jobs Route +++
@worker_bp.route('/find-jobs')
@login_required
def find_jobs():
    if current_user.role != 'worker':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

    # Check if worker has set their location
    worker_location = None
    if current_user.location_lat and current_user.location_lng:
        worker_location = (current_user.location_lat, current_user.location_lng)
    else:
        flash('Please set your location in your profile to search for jobs.', 'warning')
        return redirect(url_for('worker.profile')) # Redirect to profile if no location

    # Get filters from request arguments (using GET method for the form)
    page = request.args.get('page', 1, type=int)
    per_page = 10 # Jobs per page
    keywords = request.args.get('keywords', '').strip()
    distance_str = request.args.get('distance', '25') # Default 25km
    skills_str = request.args.get('skills', '').strip()
    job_type = request.args.get('job_type', '')
    min_salary_str = request.args.get('min_salary', '').strip()
    sort_by = request.args.get('sort_by', 'distance')

    # Initialize the form, populating with current filter values from request args
    form = JobSearchForm(request.args)
    form.validate() # Run validators if any (optional for GET)

    # --- Build Base Query ---
    query = Job.query.filter(
        Job.status == 'active',
        Job.location_lat.isnot(None),
        Job.location_lng.isnot(None)
    )

    # --- Apply DB Filters ---
    if keywords:
        search_term = f"%{keywords}%"
        query = query.filter(
            or_(Job.title.ilike(search_term), Job.description.ilike(search_term))
        )

    if job_type:
        query = query.filter(Job.job_type == job_type)

    if min_salary_str:
        try:
            min_salary = float(min_salary_str)
            if min_salary > 0:
                 query = query.filter(Job.salary >= min_salary)
        except ValueError:
            flash("Invalid minimum salary specified.", "warning")

    # Apply skill filters (similar to get_nearby_jobs)
    if skills_str:
        worker_skills = [s.strip() for s in skills_str.split(',') if s.strip()]
        skill_filters = []
        for skill in worker_skills:
            skill_filters.append(Job.skills_required.ilike(f"%{skill}%"))
        if skill_filters:
            # Assuming skills entered by worker should *all* be required by job
            # query = query.filter(and_(*skill_filters))
            # OR if *any* skill match is okay:
             query = query.filter(or_(*skill_filters))


    # --- Fetch potential jobs BEFORE distance filtering ---
    potential_jobs = query.all() # Fetch all matching DB criteria

    # --- Filter by Distance in Python ---
    filtered_jobs = []
    max_distance = float('inf') # Default to no distance limit
    if distance_str:
        try:
            max_distance = float(distance_str)
        except ValueError:
            flash("Invalid distance specified.", "warning")

    for job in potential_jobs:
        job_location = (job.location_lat, job.location_lng)
        distance = calculate_distance(worker_location, job_location)
        if distance <= max_distance:
            job.distance = distance # Add distance attribute
            filtered_jobs.append(job)

    # --- Sort Results ---
    if sort_by == 'date':
        filtered_jobs.sort(key=lambda j: j.created_at, reverse=True)
    elif sort_by == 'salary':
        filtered_jobs.sort(key=lambda j: j.salary or 0, reverse=True)
    else: # Default sort by distance
        filtered_jobs.sort(key=lambda j: j.distance)

    # --- Paginate the final list (Manual Pagination) ---
    total_jobs = len(filtered_jobs)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_jobs_list = filtered_jobs[start:end]

    # Create a pagination-like object for the template
    from flask_sqlalchemy.pagination import Pagination
    # Note: This manual pagination doesn't provide all helper methods of query.paginate()
    # It's sufficient for basic prev/next links if needed.
    class ManualPagination:
        def __init__(self, items, page, per_page, total):
            self.items = items
            self.page = page
            self.per_page = per_page
            self.total = total
            self.pages = (total + per_page - 1) // per_page if total > 0 else 0
            self.has_prev = page > 1
            self.has_next = page < self.pages
            self.prev_num = page - 1 if self.has_prev else None
            self.next_num = page + 1 if self.has_next else None

    pagination_obj = ManualPagination(paginated_jobs_list, page, per_page, total_jobs)

    return render_template(
        'find_jobs.html',
        title='Find Jobs',
        form=form,
        jobs_pagination=pagination_obj # Pass the manual pagination object
    )


# +++ NEW: My Applications Route +++
@worker_bp.route('/my-applications')
@login_required
def my_applications():
    if current_user.role != 'worker':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

    page = request.args.get('page', 1, type=int)
    per_page = 10

    # Query applications for the current worker
    # Eager load Job and Employer details
    applications_pagination = Application.query.filter_by(worker_id=current_user.id)\
                                .options(
                                    joinedload(Application.job).joinedload(Job.employer)
                                ).order_by(Application.applied_at.desc())\
                                .paginate(page=page, per_page=per_page, error_out=False)

    return render_template('my_applications.html',
                           title="My Job Applications",
                           applications_pagination=applications_pagination)


# +++ NEW: Withdraw Application Route +++
@worker_bp.route('/application/<int:application_id>/withdraw', methods=['POST'])
@login_required
def withdraw_application(application_id):
    if current_user.role != 'worker':
        abort(403) # Use abort for unauthorized actions

    application = Application.query.filter_by(id=application_id, worker_id=current_user.id).first_or_404()

    # Allow withdrawal only if status is 'applied' or maybe 'shortlisted'
    if application.status not in ['applied', 'shortlisted']:
        flash(f'Cannot withdraw application with status: {application.status}', 'warning')
        return redirect(url_for('worker.my_applications'))

    try:
        # Option 1: Delete the application
        # db.session.delete(application)
        # Option 2: Set status to 'withdrawn' (Requires adding 'withdrawn' as a possibility)
        application.status = 'withdrawn'
        db.session.commit()
        flash('Application withdrawn successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error withdrawing application {application_id}: {e}")
        flash('An error occurred while withdrawing the application.', 'danger')

    return redirect(url_for('worker.my_applications'))
