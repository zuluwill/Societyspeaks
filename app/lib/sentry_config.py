"""Sentry SDK environment / release resolution.

Keep labels explicit and stable across hosts. Do not derive the Sentry
environment from FLASK_ENV — that value is not a deploy identity and has
produced duplicate labels (e.g. ``prod`` vs SDK default ``production``).
"""

from __future__ import annotations

import os
from typing import Optional


def resolve_sentry_environment() -> str:
    """Return the Sentry environment name (never empty)."""
    value = (os.getenv("SENTRY_ENVIRONMENT") or "production").strip()
    return value or "production"


def resolve_sentry_release() -> Optional[str]:
    """Prefer explicit SENTRY_RELEASE, then Render's git commit SHA."""
    for key in ("SENTRY_RELEASE", "RENDER_GIT_COMMIT"):
        value = (os.getenv(key) or "").strip()
        if value:
            return value
    return None


def resolve_sentry_app_role() -> str:
    """Tag events with APP_ROLE so web/scheduler/worker are distinguishable."""
    value = (os.getenv("APP_ROLE") or "legacy").strip()
    return value or "legacy"
