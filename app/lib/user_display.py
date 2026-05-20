"""
Human-facing display names for users (greetings, nav, avatars).

``User.username`` is an internal handle — never use it in product copy or
transactional email greetings. Prefer :func:`friendly_display_name` and
:func:`derive_profile_from_email` for trial onboarding and emails.
"""
from __future__ import annotations

import re
from typing import Any, Optional

# Local parts that are clearly placeholders — use a neutral greeting instead.
_GENERIC_LOCAL_PARTS = frozenset({
    'test', 'user', 'admin', 'info', 'mail', 'email', 'noreply', 'no-reply',
    'me', 'hello', 'hi', 'demo', 'trial', 'temp', 'tmp',
})


def _local_part_from_email(email: Optional[str]) -> str:
    if not email or '@' not in email:
        return ''
    return email.strip().lower().split('@', 1)[0]


def _strip_plus_tag(local: str) -> str:
    return local.split('+', 1)[0] if local else ''


def derive_profile_from_email(email: Optional[str]) -> dict[str, str]:
    """Build ``full_name`` for a new trial profile from an email address.

    Uses the address the visitor typed when available (preserves ``+tag``
    semantics for derivation before ``+`` only). Falls back to a neutral
    label when the local part is empty or obviously generic.

    Returns:
        dict with ``full_name`` (for ``IndividualProfile.full_name``).
    """
    local = _strip_plus_tag(_local_part_from_email(email))
    if not local:
        return {'full_name': 'New member'}

    parts = [p for p in re.split(r'[._\-+]+', local) if p and p.isalpha()]
    if len(parts) >= 2:
        # william.roberts@… → "William Roberts"
        name = ' '.join(p.capitalize() for p in parts[:3])
        return {'full_name': name}

    if local in _GENERIC_LOCAL_PARTS or len(local) < 2:
        return {'full_name': 'New member'}

    if local.isdigit():
        return {'full_name': 'New member'}

    # Single token: title-case if mostly alphabetic
    if local.isalpha():
        return {'full_name': local.capitalize()}

    return {'full_name': 'New member'}


def friendly_display_name(
    user: Any,
    *,
    submitted_email: Optional[str] = None,
) -> str:
    """First-token greeting name for UI and emails (e.g. ``Hi William``).

    Priority:
      1. First word of ``individual_profile.full_name`` when set and not placeholder
      2. Derived from ``submitted_email`` or ``user.email``
      3. ``"there"`` (templates use ``Hi %(username)s`` with this value)
    """
    profile = getattr(user, 'individual_profile', None)
    if profile and getattr(profile, 'full_name', None):
        full = str(profile.full_name).strip()
        if full and full.lower() != 'new member':
            first = full.split()[0]
            if first:
                return first

    email = submitted_email or getattr(user, 'email', None)
    derived = derive_profile_from_email(email)
    full_name = derived['full_name']
    if full_name == 'New member':
        return 'there'
    return full_name.split()[0] if full_name else 'there'


def initials_from_name(name: Optional[str]) -> str:
    """One or two initials for avatar badges (``AC``, ``W``)."""
    if not name or not str(name).strip():
        return '?'
    parts = [p for p in str(name).strip().split() if p]
    if not parts:
        return '?'
    if len(parts) == 1:
        ch = parts[0][0]
        return ch.upper() if ch else '?'
    return (parts[0][0] + parts[-1][0]).upper()


def is_auto_generated_profile(profile: Any, user: Any) -> bool:
    """True when ``full_name`` looks machine-set, safe to refresh on re-trial."""
    if not profile or not getattr(profile, 'full_name', None):
        return True
    full = str(profile.full_name).strip().lower()
    if not full or full == 'new member':
        return True
    username = (getattr(user, 'username', None) or '').strip().lower()
    if username and full == username:
        return True
    email_local = _strip_plus_tag(_local_part_from_email(getattr(user, 'email', None)))
    if email_local:
        derived = derive_profile_from_email(getattr(user, 'email', None))
        if full == derived['full_name'].lower():
            return True
        # Also match single-token derivation
        if full == email_local.lower():
            return True
    return False


def apply_trial_profile_display_name(user: Any, *, submitted_email: Optional[str] = None) -> bool:
    """Update or create profile ``full_name`` from email when safe.

    Returns True if the profile was created or updated.
    """
    from app import db
    from app.models import IndividualProfile
    from app.models._base import generate_unique_slug

    email = submitted_email or getattr(user, 'email', None)
    derived = derive_profile_from_email(email)
    new_name = derived['full_name']

    profile = IndividualProfile.query.filter_by(user_id=user.id).first()
    if profile:
        if not is_auto_generated_profile(profile, user):
            return False
        if profile.full_name == new_name:
            return False
        profile.full_name = new_name
        db.session.commit()
        return True

    if getattr(user, 'profile_type', None):
        return False

    profile = IndividualProfile(
        user_id=user.id,
        full_name=new_name,
        slug=generate_unique_slug(IndividualProfile, new_name, fallback='profile'),
    )
    user.profile_type = 'individual'
    db.session.add(profile)
    db.session.commit()
    return True
