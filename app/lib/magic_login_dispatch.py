"""Issue + dispatch magic-login emails with Resend-safe failure handling.

``User.get_magic_login_token`` bumps ``magic_login_valid_after`` and must be
committed before send (so concurrent consumers see the new gate). If Resend
then rejects the send, that bump would invalidate any previously delivered
link while the UI still said "check your inbox" — the Deepak / Sentry 409
failure mode. On send failure we restore the prior ``valid_after`` so an
earlier working link stays usable and the user can retry cleanly.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from app import db
from app.resend_client import send_magic_login_email

logger = logging.getLogger(__name__)


def dispatch_magic_login_email(
    user,
    build_magic_url: Callable[[str], str],
    *,
    submitted_email: Optional[str] = None,
) -> bool:
    """Issue a token, commit, send. Restore prior ``valid_after`` if send fails.

    Args:
        user: User row (attached to the current session).
        build_magic_url: ``token -> absolute URL`` (keeps route-specific
            ``url_for`` / ``next`` params at the call site).
        submitted_email: Optional typed address for greeting personalisation.

    Returns:
        True if Resend accepted the email; False on send failure (after
        restoring the previous magic-login gate).
    """
    previous_valid_after = user.magic_login_valid_after
    token = user.get_magic_login_token()
    db.session.commit()

    magic_url = build_magic_url(token)
    # ``send_magic_login_email`` is contractually non-raising, but guard anyway
    # so the restore invariant below holds even if that contract ever changes.
    try:
        sent = send_magic_login_email(
            user, magic_url, submitted_email=submitted_email
        )
    except Exception:
        logger.exception(
            "Magic-login send raised for user %s — treating as failure",
            getattr(user, 'id', 'unknown'),
        )
        sent = False
    if sent:
        return True

    logger.error(
        "Magic-login email failed for user %s — restoring prior valid_after",
        getattr(user, 'id', 'unknown'),
    )
    try:
        user.magic_login_valid_after = previous_valid_after
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception(
            "Failed to restore magic_login_valid_after for user %s",
            getattr(user, 'id', 'unknown'),
        )
    return False
