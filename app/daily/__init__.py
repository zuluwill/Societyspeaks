from flask import Blueprint

daily_bp = Blueprint('daily', __name__)

from app.daily import routes
