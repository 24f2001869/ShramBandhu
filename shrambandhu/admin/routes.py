from flask import Blueprint, render_template, request, redirect, url_for, flash , current_app
from flask_login import current_user , login_required 
from shrambandhu.extensions import db
from shrambandhu.models import User, Job, Payment, EmergencyAlert, DocumentVerification, Certification, WorkerCertification, Application, Rating
#from shrambandhu.utils.auth import login_required  # Your custom decorator
from shrambandhu.utils.twilio_client import send_whatsapp_message
from . import admin_bp
from datetime import datetime, timedelta
from sqlalchemy import func

@admin_bp.route('/')
@login_required
def dashboard():
    # Platform Statistics
    stats = {
        'users': {
            'total': User.query.count(),
            'workers': User.query.filter_by(role='worker').count(),
            'employers': User.query.filter_by(role='employer').count(),
            'new_today': User.query.filter(
                User.created_at >= datetime.utcnow() - timedelta(days=1)
            ).count()
        },
        'jobs': {
            'total': Job.query.count(),
            'active': Job.query.filter_by(status='active').count(),
            'completed': Job.query.filter_by(status='completed').count()
        },
        'payments': {
            'total_amount': db.session.query(
                func.sum(Payment.amount)
            ).scalar() or 0,
            'verified': Payment.query.filter_by(status='verified').count(),
            'disputed': Payment.query.filter_by(status='disputed').count()
        }
    }

    # Recent Activities
    recent_alerts = EmergencyAlert.query.order_by(
        EmergencyAlert.created_at.desc()
    ).limit(5).all()
    
    pending_verifications = DocumentVerification.query.filter_by(
        status='pending'
    ).count()
    
    pending_certifications = WorkerCertification.query.filter_by(
        verification_status='pending'
    ).count()

    pending_documents = DocumentVerification.query.filter_by(status='pending').all()


    return render_template('admin/dashboard.html',
                         stats=stats,
                         recent_alerts=recent_alerts,
                         pending_verifications=pending_verifications,
                         pending_certifications=pending_certifications,
                         pending_documents=pending_documents,
                         datetime=datetime) 

@admin_bp.route('/users')
@login_required
def manage_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=users)

@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    flash(f'User {user.phone} has been {"activated" if user.is_active else "deactivated"}', 'success')
    return redirect(url_for('admin.manage_users'))


@admin_bp.route('/jobs')
@login_required
def manage_jobs():
    jobs = Job.query.order_by(Job.created_at.desc()).all()
    return render_template('admin/jobs.html', jobs=jobs)


@admin_bp.route('/emergency-alerts')
@login_required
def emergency_alerts():
    alerts = EmergencyAlert.query.order_by(
        EmergencyAlert.created_at.desc()
    ).all()
    return render_template('admin/emergency_alerts.html', alerts=alerts)


@admin_bp.route('/resolve-alert/<int:alert_id>', methods=['POST'])
@login_required
def resolve_alert(alert_id):
    alert = EmergencyAlert.query.get_or_404(alert_id)
    alert.status = 'resolved'
    alert.resolved_at = datetime.utcnow()
    db.session.commit()
    flash('Emergency marked as resolved', 'success')
    return redirect(url_for('admin.emergency_alerts'))

@admin_bp.route('/verify-document/<int:doc_id>', methods=['GET', 'POST'])
@login_required
def verify_document(doc_id):
    document = DocumentVerification.query.get_or_404(doc_id)
    
    # Only process if it's a POST request with action parameter
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'approve':
            document.status = 'verified'
            flash('Document approved', 'success')
        elif action == 'reject':
            document.status = 'rejected'
            flash('Document rejected', 'warning')
        db.session.commit()
        return redirect(url_for('admin.verify_documents'))
    
    # For GET requests, redirect to view documents page
    return redirect(url_for('admin.verify_documents'))

@admin_bp.route('/verify-documents')
@login_required
def verify_documents():
     # Redirect to the new paginated view
     return redirect(url_for('admin.list_pending_verifications'))

@admin_bp.route('/certifications')
@login_required
def manage_certifications():
    certifications = Certification.query.all()
    return render_template('admin/certifications.html',
                         certifications=certifications)

@admin_bp.route('/certifications/new', methods=['GET', 'POST'])
@login_required
def add_certification():
    if request.method == 'POST':
        try:
            cert = Certification(
                name=request.form.get('name'),
                description=request.form.get('description'),
                issuing_org=request.form.get('issuing_org'),
                validity_months=int(request.form.get('validity') or 0)
            )
            db.session.add(cert)
            db.session.commit()
            flash('Certification added successfully!', 'success')
            return redirect(url_for('admin.manage_certifications'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'danger')
    
    return render_template('admin/add_certification.html')

@admin_bp.route('/certifications/verify', methods=['GET', 'POST'])
@login_required
def verify_certifications():
    pending_certs = WorkerCertification.query.filter_by(
        verification_status='pending'
    ).all()
    
    if request.method == 'POST':
        cert_id = request.form.get('cert_id')
        action = request.form.get('action')
        
        worker_cert = WorkerCertification.query.get(cert_id)
        if worker_cert:
            if action == 'verify':
                worker_cert.verification_status = 'verified'
                flash('Certification verified!', 'success')
            else:
                worker_cert.verification_status = 'rejected'
                flash('Certification rejected', 'warning')
            
            db.session.commit()
        
        return redirect(url_for('admin.verify_certifications'))
    
    return render_template('admin/verify_certifications.html',
                         pending_certs=pending_certs)


@admin_bp.route('/payment-disputes')
@login_required
def payment_disputes():
    disputes = Payment.query.filter_by(
        status='disputed'
    ).order_by(Payment.created_at.desc()).all()

    disputed_payments = (
        Payment.query.filter_by(status='disputed')
        .order_by(Payment.created_at.desc()).all()
    )    
    return render_template('admin/payment_disputes.html',
                         payments=disputed_payments, disputes=disputes)

@admin_bp.route('/resolve-dispute/<int:payment_id>', methods=['POST'])
@login_required
def resolve_dispute(payment_id):
    payment = Payment.query.get_or_404(payment_id)
    resolution = request.form.get('resolution')
    
    if resolution == 'approve':
        payment.status = 'verified'
        payment.verified_at = datetime.utcnow()
        
        # Notify both parties
        message = f"Admin has verified your payment of ₹{payment.amount} for {payment.job.title}"
        send_whatsapp_message(payment.worker.phone, message)
        send_whatsapp_message(payment.employer.phone, message)
        
        flash('Payment verified by admin', 'success')
    else:
        payment.status = 'rejected'
        # Mark application as unpaid
        application = Application.query.filter_by(
            job_id=payment.job_id,
            worker_id=payment.worker_id
        ).first()
        if application:
            application.status = 'applied'
        
        flash('Payment rejected by admin', 'warning')
    
    db.session.commit()
    return redirect(url_for('admin.payment_disputes'))                         


@admin_bp.route('/analytics')
@login_required
def analytics_dashboard():
    # Key metrics
    total_workers = User.query.filter_by(role='worker').count()
    total_employers = User.query.filter_by(role='employer').count()
    total_jobs = Job.query.count()
    total_payments = db.session.query(func.sum(Payment.amount)).scalar() or 0
    
    # Recent activity
    recent_jobs = Job.query.order_by(Job.created_at.desc()).limit(5).all()
    recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(5).all()
    
    # Worker ratings distribution
    rating_distribution = db.session.query(
        Rating.rating,
        func.count(Rating.id)
    ).group_by(Rating.rating).all()
    
    return render_template('admin/analytics.html',
                         total_workers=total_workers,
                         total_employers=total_employers,
                         total_jobs=total_jobs,
                         total_payments=total_payments,
                         recent_jobs=recent_jobs,
                         recent_payments=recent_payments,
                         rating_distribution=rating_distribution)    



@admin_bp.route('/verify-certification/<int:cert_id>', methods=['POST'])
def verify_certification(cert_id):
    worker_cert = WorkerCertification.query.get_or_404(cert_id)
    action = request.form.get('action')
    
    if action == 'approve':
        worker_cert.verification_status = 'verified'
        flash('Certification approved', 'success')
    else:
        worker_cert.verification_status = 'rejected'
        flash('Certification rejected', 'warning')
    
    db.session.commit()
    return redirect(url_for('admin.verify_certifications'))



@admin_bp.route('/verifications/pending')
@login_required
#@admin_required # Add decorator if you create one for admin role check
def list_pending_verifications():
     if current_user.role != 'admin':
         flash('Admin access required.', 'danger')
         return redirect(url_for('index'))

     page = request.args.get('page', 1, type=int)
     per_page = 15
     pending_docs = DocumentVerification.query.filter_by(status='pending')\
                                         .order_by(DocumentVerification.created_at.asc())\
                                         .paginate(page=page, per_page=per_page, error_out=False)

     return render_template('admin/pending_verifications.html',
                          title='Pending Document Verifications',
                          docs_pagination=pending_docs)


@admin_bp.route('/verifications/view/<int:doc_id>', methods=['GET', 'POST'])
@login_required
#@admin_required
def view_verification(doc_id):
    if current_user.role != 'admin':
         flash('Admin access required.', 'danger')
         return redirect(url_for('index'))

    doc = DocumentVerification.query.options(db.joinedload(DocumentVerification.user)).get_or_404(doc_id)

    if request.method == 'POST':
        action = request.form.get('action')
        rejection_reason = request.form.get('rejection_reason', '').strip()

        try:
            if action == 'approve':
                doc.status = 'verified'
                doc.verified_by = current_user.id
                doc.verified_at = datetime.utcnow()
                doc.rejection_reason = None # Clear any previous reason
                # Optionally update user's overall verification status
                # user = doc.user
                # user.overall_verification_status = 'verified' # Or 'partially_verified' based on logic
                # db.session.add(user)
                flash(f'{doc.document_type} for {doc.user.name or doc.user.phone} approved.', 'success')
            elif action == 'reject':
                if not rejection_reason:
                     flash('Please provide a reason for rejection.', 'warning')
                     # Stay on the same page, retain form data if using Flask-WTF
                     return render_template('admin/view_verification.html', title='Review Document', doc=doc)

                doc.status = 'rejected'
                doc.rejection_reason = rejection_reason
                doc.verified_by = current_user.id # Record who rejected it
                doc.verified_at = datetime.utcnow() # Record time of action
                # Optionally update user's overall status if needed
                flash(f'{doc.document_type} for {doc.user.name or doc.user.phone} rejected.', 'warning')
                # Optionally send notification to user about rejection
            else:
                flash('Invalid action.', 'danger')
                return redirect(url_for('admin.view_verification', doc_id=doc.id))

            db.session.commit()
            return redirect(url_for('admin.list_pending_verifications'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error processing verification {doc_id}: {e}")
            flash('An error occurred while processing the verification.', 'danger')

    # GET request
    return render_template('admin/view_verification.html', title='Review Document', doc=doc)
