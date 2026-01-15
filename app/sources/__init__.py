# app/sources/__init__.py
from flask import Blueprint

sources_bp = Blueprint('sources', __name__, template_folder='../templates/sources')

from app.sources import routes  # noqa: E402, F401
