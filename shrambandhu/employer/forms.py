from flask_wtf import FlaskForm

from wtforms import StringField, TextAreaField, FloatField, SelectField, IntegerField, SubmitField, HiddenField, RadioField
from wtforms.validators import DataRequired, Length, NumberRange, Optional ,Email, EqualTo
from flask_wtf.file import FileField, FileAllowed, FileRequired

class PostJobForm(FlaskForm):
    title = StringField('Job Title*', validators=[DataRequired(), Length(max=100)])
    description = TextAreaField('Description*', validators=[DataRequired()])
    salary = FloatField('Salary (₹)*', validators=[DataRequired(), NumberRange(min=1)])
    salary_frequency = SelectField('Salary Frequency', choices=[('daily', 'Daily'), ('weekly', 'Weekly'), ('monthly', 'Monthly'), ('fixed', 'Fixed (One Time)')], default='daily')
    address = StringField('Full Address / Area*', validators=[DataRequired(), Length(max=255)])
    # Hidden fields for coordinates, populated by JavaScript
    latitude = HiddenField('Latitude', validators=[Optional()]) # Make Optional initially, JS should fill it
    longitude = HiddenField('Longitude', validators=[Optional()])
    skills = StringField('Skills Required (comma-separated)', validators=[Optional(), Length(max=500)])
    job_type = SelectField('Job Type', choices=[('one-time', 'One-time'), ('contract', 'Contract'), ('recurring', 'Recurring')], default='one-time')
    duration_days = IntegerField('Duration (days)', validators=[Optional(), NumberRange(min=1)], description="Required if Job Type is Contract")
    submit = SubmitField('Post Job')

    # Add custom validation later if needed, e.g., require duration_days if type is contract
    # Or require latitude/longitude if address fails geocoding

class EditJobForm(PostJobForm): # Inherits fields from PostJobForm
    submit = SubmitField('Update Job')

class PaymentForm(FlaskForm):
   

    payment_method = RadioField('Payment Method',
                               choices=[
                                   ('razorpay', 'Online Payment (Razorpay)'),
                                   ('cash', 'Cash Payment'),
                                   ('bank_transfer', 'Bank Transfer')
                               ],
                               validators=[DataRequired()])