"""Self-serve consultations: one question, one audience, one report.

``host`` holds the organiser's screens, ``participate`` the public voting page.
Both sit behind ``CONSULTATIONS_SELF_SERVE_ENABLED``.
"""
from flask import Blueprint, abort, current_app

consultations_bp = Blueprint('consultations', __name__)


@consultations_bp.before_request
def _require_feature_enabled():
    if not current_app.config.get('CONSULTATIONS_SELF_SERVE_ENABLED'):
        abort(404)


from app.consultations import host, participate  # noqa: E402,F401
from app.consultations import jobs  # noqa: E402,F401  (registers job handlers)
