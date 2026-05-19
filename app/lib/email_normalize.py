"""
Email normalization for trial abuse prevention.

The "one trial per email" rule is meaningless if Gmail aliases let a single
mailbox sign up as foo+a@gmail.com, foo+b@gmail.com, foo.bar@gmail.com,
foobar@googlemail.com, etc. This helper collapses all of those to the same
canonical form so the abuse check sees them as identical.

Scope: trial-signup abuse only. Do NOT use this for login lookups — users
register with whatever form they typed, and Gmail dot/plus rules don't apply
to most other providers.

See docs/PAID_BRIEFINGS_WORLD_CLASS_BUILD.md.
"""
from __future__ import annotations

# Gmail and Google Workspace addresses ignore dots in the local part and
# treat +tag as a transparent alias. googlemail.com is an alternate domain
# for the same mailbox.
_GMAIL_DOMAINS = frozenset({'gmail.com', 'googlemail.com'})


def normalize_trial_email(email: str | None) -> str | None:
    """Return the canonical form of ``email`` for trial-abuse de-duplication.

    For Gmail / Googlemail addresses:
      - strip dots from the local part
      - drop any +tag
      - rewrite googlemail.com -> gmail.com

    For all other providers:
      - lowercase and strip whitespace only

    Returns ``None`` for empty / falsy input or malformed addresses (no @).
    """
    if not email:
        return None

    cleaned = email.strip().lower()
    if '@' not in cleaned:
        return None

    local, _, domain = cleaned.rpartition('@')
    if not local or not domain:
        return None

    if domain in _GMAIL_DOMAINS:
        # Strip +tag
        local = local.split('+', 1)[0]
        # Strip dots
        local = local.replace('.', '')
        domain = 'gmail.com'

    if not local:
        # All-dots-and-plusses local part — treat as malformed.
        return None

    return f'{local}@{domain}'
