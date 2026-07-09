"""
Deployed-production detection for outbound email, social posts, and scheduler jobs.

CRITICAL: Do NOT treat FLASK_ENV=production as deployed production.
FLASK_ENV is often set in local/dev and has caused duplicate user emails.

True only when an explicit deploy flag is set on the host that should send:
- DEPLOYED_PRODUCTION=1  (preferred; set on Render via Blueprint)
- REPLIT_DEPLOYMENT=1    (legacy Replit published deployments)

Never set either flag on a second live host while the other is still sending.
"""

from __future__ import annotations

import os


def is_deployed_production() -> bool:
    """Return True only on an intentionally deployed production host."""
    return (
        os.environ.get('DEPLOYED_PRODUCTION') == '1'
        or os.environ.get('REPLIT_DEPLOYMENT') == '1'
    )
