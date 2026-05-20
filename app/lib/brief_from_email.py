"""Canonical brief transactional From address (env, config, templates, senders)."""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from app.email_utils import extract_clean_email

DEFAULT_BRIEF_FROM_EMAIL = 'hello@brief.societyspeaks.io'


def _raw_brief_from_email(config: Optional[Mapping[str, Any]] = None) -> str:
    if config is not None:
        return (config.get('BRIEF_FROM_EMAIL') or DEFAULT_BRIEF_FROM_EMAIL).strip()
    try:
        from flask import current_app, has_app_context

        if has_app_context():
            return (current_app.config.get('BRIEF_FROM_EMAIL') or DEFAULT_BRIEF_FROM_EMAIL).strip()
    except RuntimeError:
        pass
    return (os.environ.get('BRIEF_FROM_EMAIL') or DEFAULT_BRIEF_FROM_EMAIL).strip()


def brief_from_email_address(config: Optional[Mapping[str, Any]] = None) -> str:
    """Bare address for safe-sender copy and Resend ``from`` when no display name."""
    raw = _raw_brief_from_email(config)
    return extract_clean_email(raw) or DEFAULT_BRIEF_FROM_EMAIL


def brief_from_email_for_templates() -> str:
    """Address injected into Jinja (web + transactional email templates)."""
    return brief_from_email_address()
