from flask import Blueprint
from shrambandhu.extensions import db

chat_bp = Blueprint('chat', __name__)

from . import routes