# shrambandhu/employer/routes.py
from flask import render_template, request, redirect, url_for, flash, Blueprint, current_app, abort # Added abort
from shrambandhu.models import db, Job, User, Application, Payment, Rating, Notification
from flask_login import login_required, current_user
from datetime import datetime
from shrambandhu.utils.payment import create_payment_order, verify_payment , get_razorpay_client
# from shrambandhu.utils.location import get_coordinates # Commented out if not used
from werkzeug.utils import secure_filename
import os
from sqlalchemy import or_, and_, func, case # Added and_, func, case
from sqlalchemy.orm import joinedload, selectinload # For eager loading
# Assuming PaymentForm is still needed for initiate_payment route
from .forms import PaymentForm, PostJobForm, EditJobForm # Import job forms if used
from shrambandhu.extensions import csrf
import razorpay

employer_bp = Blueprint('employer', __name__, template_folder='../templates/employer')

@employer_bp.route('/dashboard')
@login_required
def dashboard():
    if current_user.role != 'employer':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

    # --- Fetch Data for Dashboard ---

    # Basic User Info
    user = User.query.get(current_user.id) # Already loaded by login_manager

    # Get Employer's Jobs with Counts (Active/Pending Apps)
    jobs_query = db.session.query(
        Job,
        # Count applications with status 'pending' for this job
        func.count(case((Application.status == 'pending', Application.id))).label('pending_apps_count'),
        # Count total applications for this job
        func.count(Application.id).label('total_apps_count')
    ).outerjoin(Application, Job.id == Application.job_id)\
     .filter(Job.employer_id == current_user.id)\
     .group_by(Job.id)\
     .order_by(Job.created_at.desc())

    all_employer_jobs = jobs_query.all() # List of (Job, pending_apps_count, total_apps_count) tuples

    # Separate jobs by status for easier templating
    active_jobs = []
    in_progress_jobs = []
    completed_jobs_info = [] # Store job and related info
    jobs_with_pending_apps = []

    # Process jobs
    for job, pending_apps, total_apps in all_employer_jobs:
        job.pending_apps_count = pending_apps # Attach counts to job object for template ease
        job.total_apps_count = total_apps
        if job.status == 'active':
            active_jobs.append(job)
            if pending_apps > 0:
                jobs_with_pending_apps.append(job)
        elif job.status == 'in-progress':
            in_progress_jobs.append(job)
        elif job.status == 'completed':
             # Check rating status for completed jobs
             has_rated = Rating.query.filter_by(job_id=job.id, employer_id=current_user.id).first() is not None
             job.has_rated = has_rated # Attach rating status
             completed_jobs_info.append(job)


    # --- Stats Cards Data ---
    total_jobs_count = len(all_employer_jobs)
    active_jobs_count = len(active_jobs)
    # Total pending applications across all active jobs
    total_pending_apps = sum(job.pending_apps_count for job in active_jobs if hasattr(job, 'pending_apps_count'))

    # Calculate total spent (consider only verified/completed payments)
    total_spent = db.session.query(func.sum(Payment.amount))\
                          .filter(Payment.employer_id == current_user.id)\
                          .filter(Payment.status.in_(['completed', 'verified']))\
                          .scalar() or 0

    stats = {
        'total_jobs': total_jobs_count,
        'active_jobs': active_jobs_count,
        'pending_applications': total_pending_apps,
        'total_spent': total_spent
    }

    # Recent Notifications (Limit for dashboard)
    recent_notifications = Notification.query.filter_by(user_id=current_user.id)\
                                     .order_by(Notification.created_at.desc())\
                                     .limit(5).all()

    return render_template(
        'employer/dashboard.html', # employer/dashboard.html
        user=user,
        stats=stats,
        jobs_with_pending_apps=jobs_with_pending_apps, # Jobs needing application review
        active_jobs=active_jobs, # All active jobs
        in_progress_jobs=in_progress_jobs,
        completed_jobs=completed_jobs_info, # Jobs needing payment/rating
        recent_notifications=recent_notifications,
        current_date=datetime.utcnow() # Keep for display
    )


# --- Post Job Route ---
@employer_bp.route('/post-job', methods=['GET', 'POST'])
@login_required
def post_job():
    # ...(Implementation from previous step, potentially using PostJobForm)...
    if current_user.role != 'employer': flash('Access denied.', 'danger'); return redirect(url_for('index'))
    form = PostJobForm() # Using WTForms now
    if form.validate_on_submit():
        try:
            latitude = float(form.latitude.data) if form.latitude.data else None
            longitude = float(form.longitude.data) if form.longitude.data else None
            address = form.address.data # Keep address

            # Geocode if lat/lon are missing but address is present (optional fallback)
            # if not latitude or not longitude:
            #     coords = get_coordinates(address)
            #     if coords: latitude, longitude = coords
            #     else: flash("Could not determine location from address.", "warning") # Or make map pin mandatory

            if not latitude or not longitude: # Make map pin mandatory now
                 flash("Please set the job location using the map pin.", 'danger')
                 return render_template('post_job.html', title='Post New Job', form=form)

            job = Job(
                title=form.title.data,
                description=form.description.data,
                salary=form.salary.data,
                salary_frequency=form.salary_frequency.data,
                location_lat=latitude,
                location_lng=longitude,
                address=address,
                skills_required=form.skills.data, # Store comma-separated
                employer_id=current_user.id,
                job_type=form.job_type.data,
                duration_days=form.duration_days.data if form.job_type.data == 'contract' else None,
                status='active'
            )
            db.session.add(job); db.session.commit()
            flash('Job posted successfully!', 'success')
            return redirect(url_for('employer.dashboard'))
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Post job error: {e}", exc_info=True)
            flash('Error posting job.', 'danger')
    # GET request
    return render_template('post_job.html', title='Post New Job', form=form)

# --- View Job Route (SIMPLIFIED QUERY TEST) ---
@employer_bp.route('/job/<int:job_id>')
@login_required
def view_job(job_id):
    if current_user.role != 'employer':
        flash('Access denied.', 'danger')
        return redirect(url_for('index'))

    # *** TEMPORARY SIMPLIFIED QUERY - REMOVED ALL .options() ***
    job = Job.query.filter(
        Job.id == job_id, Job.employer_id == current_user.id
    ).first_or_404()
    # *** END SIMPLIFIED QUERY ***

    # The rest of the logic relies on lazy loading relationships
    # This might be slow but should avoid the InvalidRequestError

    pending_applications = []
    accepted_application = None
    other_applications = []
    # Accessing job.applications triggers lazy loading here
    for app in job.applications:
        if app.status == 'pending':
            pending_applications.append(app)
        elif app.status == 'accepted':
            accepted_application = app
        else:
            other_applications.append(app)

    payment_status = None
    if job.status == 'completed' and accepted_application:
        # This will trigger another query if payments weren't loaded
        payment = Payment.query.filter_by(
            job_id=job.id,
            worker_id=accepted_application.worker_id,
            employer_id=current_user.id
        ).order_by(Payment.created_at.desc()).first()
        if payment:
            payment_status = payment.status

    employer_rating = None
    # This will trigger another query if ratings weren't loaded
    rating_obj = Rating.query.filter_by(
        job_id=job.id,
        employer_id=current_user.id
    ).first()
    if rating_obj:
        employer_rating = rating_obj # Pass the object or just the rating value

    return render_template(
        'job_detail.html',
        job=job,
        pending_applications=pending_applications,
        accepted_application=accepted_application,
        other_applications=other_applications,
        payment_status=payment_status,
        employer_rating=employer_rating
       )


# --- Edit Job Route ---
@employer_bp.route('/job/<int:job_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_job(job_id):
    # ...(Refined implementation using EditJobForm)...
    if current_user.role != 'employer': flash('Access denied.', 'danger'); return redirect(url_for('index'))
    job = Job.query.filter_by(id=job_id, employer_id=current_user.id).first_or_404()

    if job.status != 'active': flash('Only active jobs can be edited.', 'warning'); return redirect(url_for('employer.view_job', job_id=job.id))

    form = EditJobForm(obj=job) # Pre-populate form
    if request.method == 'GET':
        form.skills.data = job.get_formatted_skills() # Format skills for display

    if form.validate_on_submit():
        try:
            latitude = float(form.latitude.data) if form.latitude.data else None
            longitude = float(form.longitude.data) if form.longitude.data else None
            if not latitude or not longitude: # Make map pin mandatory
                 flash("Please set the job location using the map pin.", 'danger')
                 return render_template('edit_job.html', title='Edit Job', form=form, job=job) # Re-render form

            # Update job fields from form
            job.title = form.title.data
            job.description = form.description.data
            job.salary = form.salary.data
            job.salary_frequency = form.salary_frequency.data
            job.location_lat = latitude
            job.location_lng = longitude
            job.address = form.address.data
            job.skills_required = form.skills.data
            job.job_type = form.job_type.data
            job.duration_days = form.duration_days.data if form.job_type.data == 'contract' else None
            job.updated_at = datetime.utcnow()

            db.session.commit()
            flash('Job updated successfully!', 'success')
            return redirect(url_for('employer.view_job', job_id=job.id))
        except Exception as e:
            db.session.rollback(); current_app.logger.error(f"Edit job error: {e}", exc_info=True)
            flash('Error updating job.', 'danger')

    # GET request or validation failure
    # Populate hidden fields for map JS if not already done by form(obj=job)
    form.latitude.data = form.latitude.data or job.location_lat
    form.longitude.data = form.longitude.data or job.location_lng
    return render_template('edit_job.html', title='Edit Job', form=form, job=job)


# --- View Applications Route ---
@employer_bp.route('/applications/<int:job_id>')
@login_required
def view_applications(job_id):
    # ...(Implementation from previous step)...
    if current_user.role != 'employer': flash('Access denied.', 'danger'); return redirect(url_for('index'))
    job = Job.query.options(joinedload(Job.employer)).filter_by(id=job_id, employer_id=current_user.id).first_or_404()
    # Eager load worker details with applications
    applications = Application.query.filter_by(job_id=job_id)\
                                .options(joinedload(Application.worker))\
                                .order_by(Application.applied_at.desc()).all()
    return render_template('applications.html', job=job, applications=applications)


# --- Application Action Route ---
@employer_bp.route('/applications/<int:application_id>/action', methods=['POST'])
@login_required
def application_action(application_id):
    # ...(Implementation from previous step, including notifications)...
    if current_user.role != 'employer': abort(403)
    application = Application.query.options(joinedload(Application.job)).get_or_404(application_id)
    job = application.job
    if job.employer_id != current_user.id: abort(403)
    action = request.form.get('action')

    try:
        if action == 'accept':
            if job.status != 'active': flash('Job is not active, cannot accept application.', 'warning'); return redirect(url_for('employer.view_applications', job_id=job.id))
            # Reject others, accept this one, update job status
            Application.query.filter(Application.job_id == job.id, Application.id != application_id).update({'status': 'rejected'})
            application.status = 'accepted'; job.status = 'in-progress'
            # Notify worker
            notification = Notification(user_id=application.worker_id, title="Application Accepted", message=f"Your application for '{job.title}' was accepted!") # Add link_url if needed
            db.session.add(notification); flash('Application accepted.', 'success')
        elif action == 'reject':
            application.status = 'rejected'
            # Notify worker
            notification = Notification(user_id=application.worker_id, title="Application Update", message=f"Regarding your application for '{job.title}', the employer has chosen another candidate.")
            db.session.add(notification); flash('Application rejected.', 'info')
        elif action == 'complete':
            if application.status != 'accepted' or job.status != 'in-progress': flash('Cannot mark job complete from this state.', 'warning'); return redirect(url_for('employer.view_job', job_id=job.id))
            job.status = 'completed'; job.updated_at = datetime.utcnow()
             # Notify worker
            notification = Notification(user_id=application.worker_id, title="Job Completed", message=f"Job '{job.title}' has been marked complete by the employer.")
            db.session.add(notification); flash('Job marked as completed. Please initiate payment and rate the worker.', 'success')
        else: flash('Invalid action.', 'danger'); return redirect(url_for('employer.view_applications', job_id=job.id))
        db.session.commit()
    except Exception as e:
        db.session.rollback(); current_app.logger.error(f"Application action error: {e}", exc_info=True); flash('Error processing action.','danger')

    # Redirect back
    if action == 'complete': return redirect(url_for('employer.view_job', job_id=job.id))
    return redirect(url_for('employer.view_applications', job_id=job.id))


# --- Payment Routes (Keep As Is, maybe update templates later) ---
@employer_bp.route('/initiate-payment/<int:application_id>', methods=['GET', 'POST'])
@login_required
def initiate_payment(application_id):
    # ...(Implementation from previous step using PaymentForm)...
     if current_user.role != 'employer': abort(403)
     application = Application.query.options(joinedload(Application.job), joinedload(Application.worker)).get_or_404(application_id)
     job = application.job; worker = application.worker
     if job.employer_id != current_user.id: abort(403)
     if job.status != 'completed': flash('Job must be completed first.', 'warning'); return redirect(url_for('employer.view_job', job_id=job.id))
     # Check if already paid online?
     existing_payment = Payment.query.filter_by(job_id=job.id, worker_id=worker.id, status='completed').first()
     if existing_payment: flash('Payment already seems completed.', 'info'); return redirect(url_for('employer.view_job', job_id=job.id))

     form = PaymentForm() # Ensure form uses CSRF protection if enabled
     if form.validate_on_submit():
         selected_method = form.payment_method.data
         if selected_method == 'razorpay':
             try:
                 order = create_payment_order(amount=job.salary, job_id=job.id, employer_id=current_user.id, worker_id=application.worker_id)
                 if not order: raise Exception("Razorpay order creation failed.")
                 return render_template('payment.html', order=order, application=application, key=current_app.config['RAZORPAY_KEY_ID'])
             except Exception as e: flash(f'Payment initiation failed: {e}', 'danger'); return redirect(url_for('employer.view_job', job_id=job.id))
         else: # Cash or Bank Transfer - redirect to record payment flow
              return redirect(url_for('employer.record_payment', application_id=application_id, method=selected_method))

     return render_template('initiate_payment.html', application=application, job=job, form=form)


# --- Payment Callback Route (UPDATED WITH CSRF EXEMPTION) ---
# *** ADD @csrf.exempt DECORATOR ***
@csrf.exempt
@employer_bp.route('/payment-callback', methods=['POST'])
# No @login_required needed here typically, as Razorpay posts directly
# Security is handled by verifying the signature
def payment_callback():
    data = request.form
    razorpay_payment_id = data.get('razorpay_payment_id')
    razorpay_order_id = data.get('razorpay_order_id')
    razorpay_signature = data.get('razorpay_signature')

    if not all([razorpay_payment_id, razorpay_order_id, razorpay_signature]):
        flash('Invalid payment callback data received.', 'danger')
        return redirect(url_for('employer.dashboard')) # Redirect on error

    try:
        # --- Verify Signature ---
        # Get keys safely from config
        key_id = current_app.config.get('RAZORPAY_KEY_ID')
        key_secret = current_app.config.get('RAZORPAY_KEY_SECRET')
        if not key_id or not key_secret:
            current_app.logger.error("Razorpay keys not configured for signature verification.")
            raise Exception("Payment gateway configuration error.")

        client = get_razorpay_client() # Use helper from utils.payment
        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }
        client.utility.verify_payment_signature(params_dict)
        # Signature is valid if no exception is raised
        current_app.logger.info(f"Razorpay signature verified for order {razorpay_order_id}")

        # --- Fetch Payment Details from Razorpay (Verify Amount/Status) ---
        payment_details = client.payment.fetch(razorpay_payment_id)
        # Example checks:
        if payment_details.get('status') != 'captured':
             raise Exception(f"Payment status is not 'captured': {payment_details.get('status')}")

        # Get notes from payment details (safer than assuming they exist in params_dict)
        notes = payment_details.get('notes', {})
        job_id = notes.get('job_id')
        worker_id = notes.get('worker_id')
        employer_id = notes.get('employer_id') # Should match current_user if check needed

        if not job_id or not worker_id or not employer_id:
            raise Exception("Missing required details in payment notes.")

        # --- Update Database ---
        # Check if payment record already exists (to prevent duplicates)
        existing_payment = Payment.query.filter_by(transaction_id=razorpay_payment_id).first()
        if existing_payment:
            flash('Payment already recorded.', 'info')
            return redirect(url_for('employer.view_job', job_id=job_id))

        # Create payment record
        payment_record = Payment(
            job_id=int(job_id),
            employer_id=int(employer_id),
            worker_id=int(worker_id),
            amount=(payment_details['amount'] / 100.0), # Convert paise to rupees
            method='razorpay',
            status='completed', # Or 'verified'
            transaction_id=razorpay_payment_id, # Use Razorpay payment ID
            created_at=datetime.utcfromtimestamp(payment_details['created_at']), # Use Razorpay timestamp
            verified_at=datetime.utcnow() # Mark verified now
        )
        db.session.add(payment_record)

        # Update application status
        application = Application.query.filter_by(job_id=job_id, worker_id=worker_id).first()
        if application:
            # Decide appropriate status - 'paid' or maybe back to 'accepted' until rating?
            # Or maybe we don't need a 'paid' status on Application if Payment tracks it?
            # Let's assume we just need the Payment record for now.
            pass # No change to application status needed if Payment model tracks 'completed'/'verified'

        db.session.commit()
        flash('Payment successful and recorded!', 'success')
        return redirect(url_for('employer.view_job', job_id=job_id)) # Redirect to job detail

    except razorpay.errors.SignatureVerificationError as e:
        db.session.rollback()
        current_app.logger.error(f"Razorpay signature verification failed: {e}")
        flash('Payment verification failed (Invalid Signature). Please contact support.', 'danger')
        return redirect(url_for('employer.dashboard')) # Or specific error page
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error processing payment callback: {e}", exc_info=True)
        flash(f'An error occurred while processing the payment: {str(e)}', 'danger')
        # Redirect to a safe place, maybe dashboard or the job detail page
        # Use job_id from notes if available, otherwise dashboard
        job_id_from_notes = data.get('notes[job_id]') # Razorpay might send notes like this
        redirect_url = url_for('employer.view_job', job_id=job_id_from_notes) if job_id_from_notes else url_for('employer.dashboard')
        return redirect(redirect_url)


@employer_bp.route('/record-payment/<int:application_id>', methods=['GET', 'POST'])
@login_required
def record_payment(application_id):
    # ...(Implementation from previous step, handle offline payment recording, file upload)...
     if current_user.role != 'employer': abort(403)
     application = Application.query.options(joinedload(Application.job), joinedload(Application.worker)).get_or_404(application_id)
     job = application.job; worker = application.worker
     if job.employer_id != current_user.id: abort(403)
     # Pre-fill method if passed from initiate_payment
     default_method = request.args.get('method', 'cash')

     if request.method == 'POST':
        # ... (Get amount, method, transaction_id, handle receipt upload) ...
        try:
            # ... (Save file if uploaded) ...
            receipt_relative_path = None # Placeholder for saved path if needed
            payment = Payment( job_id=job.id, worker_id=worker.id, employer_id=current_user.id, amount=float(request.form.get('amount')),
                method=request.form.get('method'), status='pending', # Worker needs to verify
                transaction_id=request.form.get('transaction_id'), receipt_path=receipt_relative_path )
            db.session.add(payment)
            # Mark application as paid? Or wait for worker verification? Let's mark it pending payment verification
            # application.status = 'paid' # Or maybe a new status like 'payment_pending_verification'
            db.session.commit()
            # Notify worker to verify
            notification = Notification(user_id=worker.id, title="Payment Recorded", message=f"Employer recorded a {payment.method} payment of Rs.{payment.amount} for '{job.title}'. Please verify in Payment History.")
            db.session.add(notification); db.session.commit()
            flash('Payment recorded. Worker needs to verify.', 'success')
            return redirect(url_for('employer.view_job', job_id=job.id))
        except Exception as e: db.session.rollback(); flash('Error recording payment.', 'danger')

     # GET request
     return render_template('record_payment.html', application=application, job=job, default_method=default_method)


# --- Payment History Route ---
@employer_bp.route('/payment-history')
@login_required
def payment_history():
    # ...(Implementation from previous step)...
    if current_user.role != 'employer': flash('Access denied.', 'danger'); return redirect(url_for('index'))
    page = request.args.get('page', 1, type=int); per_page = 10
    payments = Payment.query.filter_by(employer_id=current_user.id)\
                           .options(joinedload(Payment.job), joinedload(Payment.worker))\
                           .order_by(Payment.created_at.desc())\
                           .paginate(page=page, per_page=per_page, error_out=False)
    return render_template('payment_history.html', payments=payments)

# --- Rate Worker Route (Corrected Query) ---
@employer_bp.route('/rate-worker/<int:job_id>', methods=['GET', 'POST'])
@login_required
def rate_worker(job_id):
    if current_user.role != 'employer':
         abort(403)

    # --- CORRECTED QUERY: Load job simply, get worker via helper ---
    job = Job.query.filter_by(id=job_id, employer_id=current_user.id).first_or_404()
    # --------------------------------------------------------------

    if job.status != 'completed':
        flash('Job must be completed before rating.', 'warning')
        return redirect(url_for('employer.view_job', job_id=job.id))

    # Get the accepted worker using the helper method
    worker = job.accepted_worker()
    if not worker:
        flash('No accepted worker found for this completed job.', 'danger')
        return redirect(url_for('employer.view_job', job_id=job.id))

    # Check if this employer already rated for this job
    existing_rating = Rating.query.filter_by(
        job_id=job_id,
        employer_id=current_user.id
        # Optionally add worker_id=worker.id if needed, but job_id/employer_id should be unique
    ).first()

    if request.method == 'POST':
        try:
            rating_val_str = request.form.get('rating')
            feedback = request.form.get('feedback','').strip()

            if not rating_val_str:
                raise ValueError('Rating value is required.')
            rating_val = int(rating_val_str)
            if not 1 <= rating_val <= 5:
                raise ValueError('Rating must be between 1 and 5.')

            if existing_rating:
                existing_rating.rating = rating_val
                existing_rating.feedback = feedback
                flash('Rating updated successfully!', 'success')
            else:
                new_rating = Rating(
                    job_id=job.id,
                    worker_id=worker.id,
                    employer_id=current_user.id,
                    rating=rating_val,
                    feedback=feedback
                )
                db.session.add(new_rating)
                flash('Rating submitted successfully!', 'success')

            db.session.commit()
            return redirect(url_for('employer.view_job', job_id=job.id)) # Redirect back to job detail

        except ValueError as e:
            flash(str(e), 'danger')
            # Fall through to render template again on validation error
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error submitting rating for job {job_id}: {e}", exc_info=True)
            flash('An error occurred while submitting the rating.', 'danger')
            # Fall through to render template again

    # GET request or POST failed validation
    return render_template(
        'rate_worker.html',
        job=job,
        worker=worker,
        existing_rating=existing_rating
    )

# --- Notification Routes ---
@employer_bp.route('/notifications')
@login_required
def notifications():
    # ...(Implementation from previous step)...
    if current_user.role != 'employer': flash('Access denied.', 'danger'); return redirect(url_for('index'))
    notifications = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    # Mark displayed notifications as read (or do this via JS onClick later)
    try:
        unread_ids = [n.id for n in notifications if not n.is_read]
        if unread_ids:
            Notification.query.filter(Notification.id.in_(unread_ids)).update({'is_read': True, 'read_at': datetime.utcnow()}, synchronize_session=False)
            db.session.commit()
    except Exception as e: db.session.rollback(); current_app.logger.error(f"Error marking notifications read: {e}")
    return render_template('notifications.html', notifications=notifications)


@employer_bp.route('/clear-notifications', methods=['POST'])
@login_required
def clear_notifications():
    # ...(Implementation from previous step)...
     if current_user.role != 'employer': flash('Access denied.', 'danger'); return redirect(url_for('index'))
     try:
        Notification.query.filter_by(user_id=current_user.id, is_read=False).update({'is_read': True, 'read_at': datetime.utcnow()}, synchronize_session=False)
        db.session.commit(); flash('All notifications marked as read', 'success')
     except Exception as e: db.session.rollback(); flash('Error clearing notifications', 'danger')
     return redirect(url_for('employer.notifications'))


# --- View Worker Profile ---
@employer_bp.route('/worker/<int:worker_id>')
@login_required
def view_worker(worker_id):
    # ...(Implementation from previous step)...
    if current_user.role != 'employer': flash('Access denied.', 'danger'); return redirect(url_for('index'))
    worker = User.query.filter_by(id=worker_id, role='worker').first_or_404()
    # Find jobs this employer posted where this worker was accepted
    collaborated_jobs = db.session.query(Job, Application)\
        .join(Application, Job.id == Application.job_id)\
        .filter(Job.employer_id == current_user.id, Application.worker_id == worker_id, Application.status == 'accepted')\
        .order_by(Job.created_at.desc()).all()
    # Get ratings given *by any employer* for this worker
    ratings = Rating.query.filter_by(worker_id=worker_id)\
                    .options(joinedload(Rating.employer), joinedload(Rating.job))\
                    .order_by(Rating.created_at.desc()).limit(10).all()
    return render_template('worker_profile.html', worker=worker, collaborated_jobs=collaborated_jobs, ratings=ratings)