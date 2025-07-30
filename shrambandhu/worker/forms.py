# shrambandhu/worker/forms.py (Corrected)
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed, FileRequired
from wtforms import (
    StringField, SubmitField, TextAreaField, IntegerField, SelectField,
    FloatField, HiddenField, RadioField , TelField
)
from wtforms.validators import DataRequired, Length, Optional, NumberRange , Regexp
# Import the base Config object directly to access static config values
from shrambandhu.config import Config # Assuming config.py is one level up
from shrambandhu.models import User # Import User for validation if needed
import re # Import re

# Regex for Indian phone numbers (adjust if needed)
phone_regex = r'^(\+91[\-\s]?)?[6-9]\d{9}$'

class ProfileForm(FlaskForm):
    """Form for workers to edit their profile details."""
    name = StringField('Full Name', validators=[DataRequired(), Length(min=2, max=100)])

    # --- ADD PHONE FIELD ---
    phone = TelField('Phone Number',
                     validators=[
                         Optional(), # Allow submitting profile without changing phone
                         Regexp(phone_regex, message="Invalid Indian phone number format.")
                     ],
                     description="Update your primary contact number. Verification required if changed.")
    # ---------------------
    
    skills = StringField('Skills (comma-separated)',
                         validators=[Optional(), Length(max=500)],
                         description="E.g., Masonry, Plumbing, Electrician, Carpentry")
    experience_years = IntegerField('Years of Experience',
                                   validators=[Optional(), NumberRange(min=0, max=60)])
    # location_address = StringField('Current Location Address', ...) # Keep if added before
    submit = SubmitField('Update Profile')

class DocumentUploadForm(FlaskForm):
    """Form for uploading verification documents."""
    document_type = SelectField('Document Type',
                                choices=[
                                    ('', '-- Select Type --'),
                                    ('aadhaar', 'Aadhaar Card'),
                                    ('pan', 'PAN Card'),
                                    ('eshram', 'e-Shram Card'),
                                    ('voter_id', 'Voter ID Card'),
                                    ('driving_license', "Driver's License"),
                                    ('photo_id', 'Other Photo ID'),
                                    ('address_proof', 'Address Proof'),
                                    # Add more types as needed
                                ],
                                validators=[DataRequired(message="Please select a document type.")])

    document_number = StringField('Document Number (Optional)',
                                  validators=[Optional(), Length(max=100)],
                                  description="Enter if applicable (e.g., Aadhaar number, PAN number)")

    document_file = FileField('Upload Document File',
                              validators=[
                                  FileRequired(message="Please select a file to upload."),
                                  # *** FIX: Access config directly via imported class ***
                                  FileAllowed(
                                      Config.ALLOWED_EXTENSIONS, # Access directly from imported Config class
                                      'Only images (jpg, png) and PDF files are allowed.'
                                  )
                              ])
    submit = SubmitField('Upload Document')

class JobSearchForm(FlaskForm):
    """Form for filtering and searching jobs."""
    keywords = StringField('Keywords (Title/Description)',
                           validators=[Optional(), Length(max=100)])

    distance = SelectField('Distance (Max)',
                           choices=[
                               ('5', 'Up to 5 km'), ('10', 'Up to 10 km'), ('25', 'Up to 25 km'),
                               ('50', 'Up to 50 km'), ('100', 'Up to 100 km'), ('', 'Any Distance')
                           ], default='25', validators=[Optional()])

    skills = StringField('Required Skills (comma-separated)',
                         validators=[Optional(), Length(max=200)], description="E.g., Plumbing, Electrician")

    job_type = SelectField('Job Type',
                           choices=[ ('', 'Any Type'), ('one-time', 'One-time'), ('contract', 'Contract'), ('recurring', 'Recurring') ],
                           default='', validators=[Optional()])

    min_salary = FloatField('Minimum Salary (₹)',
                             validators=[Optional(), NumberRange(min=0)], description="Leave blank for any salary")

    sort_by = RadioField('Sort By',
                         choices=[ ('distance', 'Distance'), ('date', 'Date Posted'), ('salary', 'Salary') ],
                         default='distance', validators=[DataRequired()])

    submit = SubmitField('Search Jobs')