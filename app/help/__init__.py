from flask import Blueprint

help_bp = Blueprint('help', __name__, template_folder='../templates/help')

# Import routes after blueprint creation
from app.help import routes