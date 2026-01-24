# app/admin/__init__.py
from flask import Blueprint

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# Only import routes after blueprint creation
from . import routes

# Import Polymarket admin routes (optional - only if module exists)
try:
    from . import polymarket_routes
except ImportError:
    pass  # Polymarket routes are optional