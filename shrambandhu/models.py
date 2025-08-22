# shrambandhu/models.py (Corrected)
from datetime import datetime, timedelta
from flask import url_for, current_app # Added current_app import
from .extensions import db, login_manager, bcrypt # Corrected import source for login_manager/bcrypt
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
# from werkzeug.utils import secure_filename # Not typically needed in models.py
from sqlalchemy import func , Integer
import os
import random
import string

# login_manager setup is now in extensions.py
# @login_manager.user_loader decorator should also be in extensions.py

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)

    # --- Core Identification ---
    # Made phone nullable to allow email/google registration first
    phone = db.Column(db.String(15), unique=True, index=True, nullable=True)
    email = db.Column(db.String(120), unique=True, index=True, nullable=True)
    password_hash = db.Column(db.String(128), nullable=True)
    google_id = db.Column(db.String(100), unique=True, nullable=True, index=True)

    # --- Verification Status ---
    is_phone_verified = db.Column(db.Boolean, default=False)
    is_email_verified = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True) # Admin control

    # --- Basic Profile ---
    name = db.Column(db.String(100), nullable=True) # Allow name to be null initially
    role = db.Column(db.String(20), nullable=False, index=True)  # worker/employer/admin
    language = db.Column(db.String(10), default='en')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime, nullable=True)

    # --- Location ---
    location_lat = db.Column(db.Float, nullable=True)
    location_lng = db.Column(db.Float, nullable=True)
    location_address = db.Column(db.String(255), nullable=True)
    location_updated_at = db.Column(db.DateTime, nullable=True)

    # --- Worker Specific ---
    skills = db.Column(db.Text, nullable=True) # Storing as comma-separated string
    experience_years = db.Column(db.Integer, nullable=True)
    # 'rating' column removed, use Rating model and average_rating property
    voice_sample_path = db.Column(db.String(255), nullable=True) # Relative path from UPLOAD_FOLDER/voice_samples
    # Optional fields (keep if planned feature)
    public_fields = db.Column(db.Text, default='name,skills,rating') # Fields visible on public profile
    referral_code = db.Column(db.String(20), unique=True, nullable=True)
    referred_by = db.Column(db.String(20), nullable=True)
    profile_views = db.Column(db.Integer, default=0, nullable=False)
    # --- Employer Specific ---
    org_name = db.Column(db.String(100), nullable=True)
    org_type = db.Column(db.String(50), nullable=True)  # individual/company/ngo

    # --- Verification & KYC ---
    # Using DocumentVerification relationship primarily, added overall status summary
    overall_verification_status = db.Column(db.String(20), default='not_verified', index=True) # not_verified, pending, partial, verified

    # --- OTP / Tokens ---
    otp = db.Column(db.String(6), nullable=True)
    otp_expiry = db.Column(db.DateTime, nullable=True)
    email_verification_token = db.Column(db.String(100), unique=True, nullable=True)
    password_reset_token = db.Column(db.String(100), unique=True, nullable=True)
    token_expiry = db.Column(db.DateTime, nullable=True) # Common expiry for email/password tokens

    # --- Relationships (Corrected and Cleaned) ---
    # Worker's Certifications
    worker_certifications = db.relationship('WorkerCertification', back_populates='worker', lazy='dynamic', cascade="all, delete-orphan")
    # Worker's Applications
    worker_applications = db.relationship('Application', foreign_keys='Application.worker_id', back_populates='worker', lazy='dynamic', cascade="all, delete-orphan")
    # Employer's Posted Jobs
    posted_jobs = db.relationship('Job', foreign_keys='Job.employer_id', back_populates='employer', lazy='dynamic', cascade="all, delete-orphan")
    # Payments involving this user
    payments_as_worker = db.relationship('Payment', foreign_keys='Payment.worker_id', back_populates='worker', lazy='dynamic')
    payments_as_employer = db.relationship('Payment', foreign_keys='Payment.employer_id', back_populates='employer', lazy='dynamic')
    # Ratings involving this user
    ratings_given = db.relationship('Rating', foreign_keys='Rating.employer_id', back_populates='employer', lazy='dynamic') # Employer rating worker
    ratings_received = db.relationship('Rating', foreign_keys='Rating.worker_id', back_populates='worker', lazy='dynamic') # Worker being rated
    # Notifications for this user
    notifications = db.relationship('Notification', back_populates='user', lazy='dynamic', cascade="all, delete-orphan")
    # DocumentVerifications submitted by this user
    document_verifications = db.relationship('DocumentVerification', foreign_keys='DocumentVerification.user_id', back_populates='user', lazy='dynamic', cascade="all, delete-orphan")
    # DocumentVerifications verified by this user (if admin)
    verifications_done = db.relationship('DocumentVerification', foreign_keys='DocumentVerification.verified_by', back_populates='verifier', lazy='dynamic')

    def __repr__(self):
        # Show email or phone if available for better identification
        identifier = self.email or self.phone or f"ID:{self.id}"
        return f"<User {identifier} - {self.role}>"

    def set_password(self, password):
        # Ensure bcrypt is available
        #if 'bcrypt' not in current_app.extensions:
            #raise RuntimeError("Bcrypt extension not initialized.")
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        if not self.password_hash:
            return False
        #if 'bcrypt' not in current_app.extensions:
            #raise RuntimeError("Bcrypt extension not initialized.")
        return bcrypt.check_password_hash(self.password_hash, password)

    def generate_token(self, purpose='email_verify', expires_in=3600):
        # ... (Keep implementation from previous step) ...
        token = ''.join(random.choices(string.ascii_letters + string.digits, k=40))
        self.token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
        if purpose == 'email_verify': self.email_verification_token = token
        elif purpose == 'password_reset': self.password_reset_token = token
        return token

    def verify_token(self, token, purpose='email_verify'):
        # ... (Keep implementation from previous step) ...
        correct_token = None
        if purpose == 'email_verify': correct_token = self.email_verification_token
        elif purpose == 'password_reset': correct_token = self.password_reset_token
        if correct_token == token and self.token_expiry and self.token_expiry > datetime.utcnow():
            self.token_expiry = None
            if purpose == 'email_verify': self.email_verification_token = None
            if purpose == 'password_reset': self.password_reset_token = None
            return True
        return False


    def generate_otp(self, expires_in=300):
        # For testing with specific phone number
        if self.phone == "8987607463":
            otp = "654321"  # Fixed OTP for testing
        else:
            otp = str(random.randint(100000, 999999))  # Normal 6-digit OTP
        
        self.otp = otp
        self.otp_expiry = datetime.utcnow() + timedelta(seconds=expires_in)
        return self.otp

    def verify_otp(self, otp_code):
        # Bypass for development and specific test phone
        if (os.getenv('FLASK_ENV') == 'development' and otp_code == "123456") or \
           (self.phone == "8987607463" and otp_code == "654321"):
            self.otp = None
            self.otp_expiry = None
            return True
        
        if self.otp == otp_code and self.otp_expiry and self.otp_expiry > datetime.utcnow():
            self.otp = None
            self.otp_expiry = None
            return True
        return False

    def get_skills_list(self):
        # ... (Keep implementation from previous step) ...
        if not self.skills: return []
        return [skill.strip() for skill in self.skills.split(',') if skill.strip()]

    def set_skills_list(self, skills_list):
        # ... (Keep implementation from previous step) ...
        self.skills = ','.join([skill.strip() for skill in skills_list if skill.strip()])

    @property
    def is_fully_verified(self):
        # ... (Keep implementation from previous step, checking DocumentVerification) ...
        required_types = []
        if self.role == 'worker': required_types = ['aadhaar', 'photo_id'] # Example
        elif self.role == 'employer': required_types = ['pan', 'org_proof'] # Example
        if not required_types: return True
        # Use the relationship directly
        verified_docs = {doc.document_type.lower() for doc in self.document_verifications if doc.status == 'verified'}
        return all(req_type in verified_docs for req_type in required_types)

    @property
    def average_rating(self):
        # ... (Keep implementation from previous step, using ratings_received relationship) ...
         if self.role != 'worker': return None
         avg = db.session.query(func.avg(Rating.rating)).filter(Rating.worker_id == self.id).scalar()
         return round(avg, 1) if avg is not None else None

    @property
    def ratings_count(self):
        # ... (Keep implementation from previous step, using ratings_received relationship) ...
         if self.role != 'worker': return 0
         # Ensure relationship is loaded or use count() directly on query if lazy='dynamic'
         return Rating.query.filter_by(worker_id=self.id).count()
         # Or if lazy != 'dynamic': return len(self.ratings_received)

    @property
    def completed_jobs_count(self):
        # ... (Keep implementation from previous step, using worker_applications relationship) ...
         if self.role != 'worker': return 0
         # Use count() on the query for efficiency
         return Application.query.join(Job, Application.job_id == Job.id)\
                          .filter(Application.worker_id == self.id,
                                  Job.status == 'completed',
                                  Application.status == 'accepted')\
                          .count()

    @property
    def profile_completion(self):
        # ... (Keep implementation from previous step, checking certifications relationship) ...
        completed = 0
        if self.role == 'worker':
            required_fields = 5
            if self.name: completed += 1
            if self.skills: completed += 1
            if self.experience_years is not None: completed += 1
            # Check document verification status using the other property
            if self.is_fully_verified: completed += 1 # Or check specific doc types
            if self.worker_certifications.first(): completed += 1 # Checks if relationship is not empty
            return int((completed / required_fields) * 100) if required_fields > 0 else 100
        elif self.role == 'employer':
             required_fields = 4
             if self.name: completed += 1
             if self.org_name: completed += 1
             if self.org_type: completed += 1
             if self.is_fully_verified: completed += 1 # Assuming employers verify too
             return int((completed / required_fields) * 100) if required_fields > 0 else 100
        else: return 100 # Admin profile always 100%


# --- Job Model (Confirm lat/lng nullable=True is okay as per previous step) ---
class Job(db.Model):
    __tablename__ = 'jobs'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    employer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    location_lat = db.Column(db.Float, nullable=True) # Keep nullable as map might set it
    location_lng = db.Column(db.Float, nullable=True) # Keep nullable
    address = db.Column(db.String(255), nullable=True)
    salary = db.Column(db.Float, nullable=False)
    salary_frequency = db.Column(db.String(20), default='daily')
    skills_required = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), default='active', index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    job_type = db.Column(db.String(20), default='one-time')
    duration_days = db.Column(db.Integer, nullable=True)
    is_urgent = db.Column(db.Boolean, default=False)

    # Relationships (Corrected back_populates)
    employer = db.relationship('User', back_populates='posted_jobs')
    applications = db.relationship('Application', back_populates='job', lazy='dynamic', cascade="all, delete-orphan")
    payments = db.relationship('Payment', back_populates='job', lazy='dynamic')
    ratings = db.relationship('Rating', back_populates='job', lazy='dynamic')

    # --- Methods ---
    # ... (Keep __repr__, accepted_worker, accepted_application, get_skills_list, get_formatted_skills) ...
    def __repr__(self): return f"<Job {self.id}: {self.title}>"
    def accepted_worker(self): app = self.applications.filter_by(status='accepted').first(); return app.worker if app else None
    def accepted_application(self): return self.applications.filter_by(status='accepted').first()
    def get_skills_list(self): return [s.strip() for s in (self.skills_required or '').split(',') if s.strip()]
    def get_formatted_skills(self): return ', '.join(self.get_skills_list())


# --- Application Model (Keep As Is from previous correction) ---
class Application(db.Model):
    __tablename__ = 'applications'
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False, index=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    status = db.Column(db.String(20), default='applied', index=True)
    applied_at = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.Text, nullable=True)
    # Relationships (Corrected back_populates)
    job = db.relationship('Job', back_populates='applications')
    worker = db.relationship('User', back_populates='worker_applications') # Changed from 'applications'
    __table_args__ = (db.UniqueConstraint('job_id', 'worker_id', name='_job_worker_uc'),)
    def __repr__(self): return f"<Application {self.id} (Job: {self.job_id}, Worker: {self.worker_id})>"

# --- Payment Model (Corrected back_populates) ---
class Payment(db.Model):
    __tablename__ = 'payments'
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False) # Should probably be non-nullable
    worker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    employer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    method = db.Column(db.String(20))
    status = db.Column(db.String(20), index=True) # pending, verified, disputed, completed, failed
    transaction_id = db.Column(db.String(100), nullable=True)
    receipt_path = db.Column(db.String(255), nullable=True) # Relative path
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    verified_at = db.Column(db.DateTime, nullable=True)
    # Relationships
    job = db.relationship('Job', back_populates='payments')
    worker = db.relationship('User', foreign_keys=[worker_id], back_populates='payments_as_worker')
    employer = db.relationship('User', foreign_keys=[employer_id], back_populates='payments_as_employer')


# --- EmergencyAlert Model (Keep as is) ---
class EmergencyAlert(db.Model):
    # ... (Keep previous structure) ...
    __tablename__ = 'emergency_alerts'
    id = db.Column(db.Integer, primary_key=True); worker_id = db.Column(db.Integer, db.ForeignKey('users.id')); location_lat = db.Column(db.Float); location_lng = db.Column(db.Float); status = db.Column(db.String(20), default='active'); created_at = db.Column(db.DateTime, default=datetime.utcnow); resolved_at = db.Column(db.DateTime); worker = db.relationship('User', foreign_keys=[worker_id])


# --- Certification Model (Keep as is) ---
class Certification(db.Model):
    # ... (Keep previous structure, corrected relationship name) ...
    __tablename__ = 'certifications'; id = db.Column(db.Integer, primary_key=True); name = db.Column(db.String(100), unique=True); description = db.Column(db.Text); issuing_org = db.Column(db.String(100)); validity_months = db.Column(db.Integer)
    worker_certs = db.relationship('WorkerCertification', back_populates='certification')


# --- WorkerCertification Model (Corrected back_populates) ---
class WorkerCertification(db.Model):
    __tablename__ = 'worker_certifications'
    id = db.Column(db.Integer, primary_key=True)
    worker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    certification_id = db.Column(db.Integer, db.ForeignKey('certifications.id'), nullable=False)
    certified_at = db.Column(db.DateTime, default=datetime.utcnow) # Should maybe be nullable and set by user?
    expires_at = db.Column(db.DateTime, nullable=True)
    verification_status = db.Column(db.String(20), default='pending', index=True) # pending/verified/rejected
    document_path = db.Column(db.String(255), nullable=False) # Relative path
    # Relationships
    certification = db.relationship('Certification', back_populates='worker_certs')
    worker = db.relationship('User', back_populates='worker_certifications') # Changed from 'certifications'


# --- VoiceCall Model (Keep as is) ---
class VoiceCall(db.Model):
    # ... (Keep previous structure) ...
    __tablename__ = 'voice_calls'; id = db.Column(db.Integer, primary_key=True); caller_id = db.Column(db.Integer, db.ForeignKey('users.id')); recipient_id = db.Column(db.Integer, db.ForeignKey('users.id')); room_sid = db.Column(db.String(100)); room_name = db.Column(db.String(100)); call_type = db.Column(db.String(20)); status = db.Column(db.String(20), default='initiated'); started_at = db.Column(db.DateTime); ended_at = db.Column(db.DateTime); caller = db.relationship('User', foreign_keys=[caller_id]); recipient = db.relationship('User', foreign_keys=[recipient_id])


# --- Rating Model (Corrected back_populates) ---
class Rating(db.Model):
    __tablename__ = 'ratings'
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey('jobs.id'), nullable=False)
    worker_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    employer_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    rating = db.Column(db.Integer, nullable=False) # 1-5
    feedback = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # Relationships
    job = db.relationship('Job', back_populates='ratings')
    worker = db.relationship('User', foreign_keys=[worker_id], back_populates='ratings_received')
    employer = db.relationship('User', foreign_keys=[employer_id], back_populates='ratings_given')

# --- DocumentVerification Model (Corrected - removed document_path, ensured file_path) ---
class DocumentVerification(db.Model):
    __tablename__ = 'document_verifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    document_type = db.Column(db.String(50), nullable=False)
    document_number = db.Column(db.String(100), nullable=True) # Number might not always be present
    file_path = db.Column(db.String(255), nullable=False) # Path relative to UPLOAD_FOLDER/documents/<user_id>/
    status = db.Column(db.String(20), default='pending', nullable=False, index=True)
    rejection_reason = db.Column(db.Text, nullable=True)
    verified_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True) # Admin user ID
    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Relationships (Corrected back_populates)
    user = db.relationship('User', foreign_keys=[user_id], back_populates='document_verifications') # Corrected populates
    verifier = db.relationship('User', foreign_keys=[verified_by], back_populates='verifications_done') # Corrected populates

    def __repr__(self):
        return f"<DocumentVerification {self.id} (User: {self.user_id} Type: {self.document_type} Status: {self.status})>"

    @property
    def file_url(self):
        # Generate URL using the correct route
        # Ensure the route 'worker.uploaded_document' exists and handles the filename correctly
        try:
            # Assumes file_path includes the user_id subdirectory, e.g., "123/aadhaar_123_timestamp.pdf"
            return url_for('worker.uploaded_document', filename=self.file_path, _external=True)
        except Exception as e:
            # Log error if URL generation fails
            current_app.logger.error(f"Could not generate URL for document {self.id}: {e}")
            return "#" # Return a placeholder URL

# --- Notification Model (Keep as is) ---
class Notification(db.Model):
    # ... (Keep previous structure, corrected back_populates) ...
    __tablename__ = 'notifications'; id = db.Column(db.Integer, primary_key=True); user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True); title = db.Column(db.String(100), nullable=False); message = db.Column(db.Text, nullable=False); link_url = db.Column(db.String(255), nullable=True); is_read = db.Column(db.Boolean, default=False, nullable=False, index=True); created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True); read_at = db.Column(db.DateTime)
    user = db.relationship('User', back_populates='notifications') # Corrected populates
    def __repr__(self): return f"<Notification {self.id} for User {self.user_id}>"
    # Keep mark_as_read method, but commits should happen in routes/services

    def mark_as_read(self): self.is_read = True; self.read_at = datetime.utcnow()
