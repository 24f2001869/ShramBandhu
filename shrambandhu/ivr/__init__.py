# shrambandhu/ivr/__init__.py
from flask import Blueprint

ivr_bp = Blueprint('ivr', __name__, url_prefix='/ivr')

# Import routes after blueprint creation to avoid circular imports
from . import routes