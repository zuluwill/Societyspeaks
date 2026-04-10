from datetime import datetime, timedelta

from flask import current_app, flash, redirect, session, url_for
from sqlalchemy import func

from app.lib.auth_utils import normalize_email
from app.lib.time import utcnow_naive
from app.models import Partner, PartnerMember

PARTNER_LOGIN_LOCKOUT_ATTEMPTS = 5
PARTNER_LOGIN_LOCKOUT_WINDOW = timedelta(minutes=5)


def clear_partner_portal_session():
    """Remove all partner portal session keys."""
    for key in list(session.keys()):
        if key.startswith("partner_"):
            session.pop(key, None)


def sync_partner_portal_session_for_email(email):
    """
    Ensure partner portal session keys reflect the currently authenticated email.

    Always clears any prior partner session first so a reused browser session
    cannot retain portal access from a different account.
    """
    clear_partner_portal_session()

    normalized_email = normalize_email(email)
    if not normalized_email:
        return

    try:
        member = (
            PartnerMember.query.filter(
                func.lower(PartnerMember.email) == normalized_email,
                PartnerMember.status == "active",
            )
            .first()
        )
        if member and member.partner and member.partner.status == "active":
            session["partner_portal_id"] = member.partner_id
            session["partner_member_id"] = member.id
            return

        partner = (
            Partner.query.filter(
                func.lower(Partner.contact_email) == normalized_email,
                Partner.status == "active",
            )
            .first()
        )
        if partner:
            session["partner_portal_id"] = partner.id
    except Exception as exc:
        current_app.logger.warning(
            "Could not sync partner portal session for %s: %s", normalized_email, exc
        )


def partner_login_lockout_key(email):
    normalized_email = normalize_email(email)
    return f"_lockout_partner:{normalized_email}" if normalized_email else ""


def get_partner_login_lockout(email):
    """
    Return the remaining lockout seconds for this email, or 0 if not locked.
    """
    lockout_key = partner_login_lockout_key(email)
    if not lockout_key:
        return 0

    lockout_until = session.get(f"{lockout_key}:until")
    if not lockout_until:
        return 0

    try:
        lockout_dt = datetime.fromisoformat(lockout_until)
    except ValueError:
        session.pop(lockout_key, None)
        session.pop(f"{lockout_key}:until", None)
        return 0

    remaining = int((lockout_dt - utcnow_naive()).total_seconds())
    if remaining > 0:
        return remaining

    session.pop(lockout_key, None)
    session.pop(f"{lockout_key}:until", None)
    return 0


def record_partner_login_failure(email):
    """
    Increment lockout counters for failed partner authentication attempts.

    Returns (fail_count, remaining_seconds).
    """
    lockout_key = partner_login_lockout_key(email)
    if not lockout_key:
        return 0, 0

    remaining = get_partner_login_lockout(email)
    if remaining > 0:
        return int(session.get(lockout_key, PARTNER_LOGIN_LOCKOUT_ATTEMPTS)), remaining

    fail_count = int(session.get(lockout_key, 0)) + 1
    session[lockout_key] = fail_count

    if fail_count >= PARTNER_LOGIN_LOCKOUT_ATTEMPTS:
        lockout_dt = utcnow_naive() + PARTNER_LOGIN_LOCKOUT_WINDOW
        session[f"{lockout_key}:until"] = lockout_dt.isoformat()
        remaining = int(PARTNER_LOGIN_LOCKOUT_WINDOW.total_seconds())

    return fail_count, remaining


def get_or_create_owner_member(partner):
    owner_member = PartnerMember.query.filter_by(
        partner_id=partner.id,
        email=partner.contact_email,
    ).first()
    if owner_member:
        if owner_member.role != "owner":
            owner_member.role = "owner"
        if owner_member.status != "active":
            owner_member.status = "active"
        if not owner_member.password_hash:
            owner_member.password_hash = partner.password_hash
        return owner_member

    owner_member = PartnerMember(
        partner_id=partner.id,
        email=partner.contact_email,
        full_name=partner.name,
        password_hash=partner.password_hash,
        role="owner",
        status="active",
        accepted_at=utcnow_naive(),
    )
    from app import db

    db.session.add(owner_member)
    db.session.flush()
    return owner_member


def authenticate_partner_credentials(email, password):
    """
    Authenticate partner/member credentials using the same precedence as the portal.

    Returns normalized_email, partner, member, valid_login where:
    - `partner` is the resolved Partner row, or None if no candidate exists
    - `member` is the matching active PartnerMember used for login, or None
    - `valid_login` indicates whether the password matched under portal rules
    """
    normalized_email = normalize_email(email)
    member_record = (
        PartnerMember.query.filter(func.lower(PartnerMember.email) == normalized_email)
        .first()
    )
    partner = (
        member_record.partner
        if member_record
        else Partner.query.filter(func.lower(Partner.contact_email) == normalized_email).first()
    )

    valid_login = False
    active_member = None

    if member_record:
        # Authenticate active members even if the partner is deactivated so the
        # caller can show the explicit deactivated-account message instead of
        # misclassifying correct credentials as a failed login attempt.
        if member_record.status == "active" and partner:
            # Owner credentials are sourced from Partner for backward compatibility.
            if (
                member_record.role == "owner"
                or member_record.email == partner.contact_email
            ):
                valid_login = partner.check_password(password)
                if valid_login and member_record.password_hash != partner.password_hash:
                    member_record.password_hash = partner.password_hash
            else:
                valid_login = member_record.check_password(password)

            if valid_login:
                active_member = member_record
    elif partner:
        valid_login = partner.check_password(password)

    return normalized_email, partner, active_member, valid_login


def finalize_partner_portal_login(partner, member=None):
    """
    Reset the pre-login session and establish a clean partner portal session.
    """
    active_member = member
    if not active_member or active_member.partner_id != partner.id or active_member.status != "active":
        active_member = get_or_create_owner_member(partner)

    active_member.last_login_at = utcnow_naive()

    from app import db

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("finalize_partner_portal_login: failed to persist member updates")

    session.clear()
    session["partner_portal_id"] = partner.id
    session["partner_member_id"] = active_member.id
    return active_member


def attempt_partner_only_login(email, password):
    """
    Authenticate a partner account for users who have no User table record.

    Returns a redirect Response to the partner portal on success, or None if
    the credentials do not match any active partner account.  The caller is
    responsible for showing an error flash when None is returned.
    """
    try:
        remaining = get_partner_login_lockout(email)
        if remaining > 0:
            flash(
                f"Too many failed attempts. Please try again in {remaining} seconds.",
                "error",
            )
            return redirect(url_for("auth.login"))

        normalized_email, partner, active_member, valid_login = authenticate_partner_credentials(
            email, password
        )

        if not partner or not valid_login:
            fail_count, remaining = record_partner_login_failure(normalized_email)
            if remaining > 0:
                current_app.logger.warning(
                    "Partner login lockout triggered for %s after %s failures",
                    normalized_email,
                    fail_count,
                )
            return None

        # Correct credentials but account deactivated — tell the user and do
        # not record a failure (mirrors the dedicated portal login behaviour).
        if partner.status != "active":
            flash(
                "This account has been deactivated. Please contact support.",
                "error",
            )
            return redirect(url_for("auth.login"))

        finalize_partner_portal_login(partner, active_member)

        flash("Welcome back.", "success")
        return redirect(url_for("partner.portal_dashboard"))

    except Exception as exc:
        current_app.logger.warning(
            "Partner-only login attempt failed for %s: %s", normalized_email if 'normalized_email' in locals() else email, exc
        )
        return None
