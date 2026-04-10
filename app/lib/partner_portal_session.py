from flask import current_app, flash, redirect, session, url_for

from app.models import Partner, PartnerMember


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

    if not email:
        return

    try:
        member = PartnerMember.query.filter_by(email=email, status="active").first()
        if member and member.partner and member.partner.status == "active":
            session["partner_portal_id"] = member.partner_id
            session["partner_member_id"] = member.id
            return

        partner = Partner.query.filter_by(contact_email=email, status="active").first()
        if partner:
            session["partner_portal_id"] = partner.id
    except Exception as exc:
        current_app.logger.warning(
            "Could not sync partner portal session for %s: %s", email, exc
        )


def attempt_partner_only_login(email, password):
    """
    Authenticate a partner account for users who have no User table record.

    Returns a redirect Response to the partner portal on success, or None if
    the credentials do not match any active partner account.  The caller is
    responsible for showing an error flash when None is returned.
    """
    try:
        member = PartnerMember.query.filter_by(email=email, status="active").first()
        partner = (
            member.partner
            if member
            else Partner.query.filter_by(contact_email=email, status="active").first()
        )

        if not partner or partner.status != "active":
            return None

        valid = False
        active_member = member

        if member and member.status == "active":
            # Owner credentials live on Partner for backward-compatibility.
            if member.role == "owner" or member.email == partner.contact_email:
                valid = partner.check_password(password)
                if valid and member.password_hash != partner.password_hash:
                    member.password_hash = partner.password_hash
                    try:
                        from app import db
                        db.session.commit()
                    except Exception:
                        from app import db
                        db.session.rollback()
            else:
                valid = member.check_password(password)
        elif partner:
            valid = partner.check_password(password)

        if not valid:
            return None

        clear_partner_portal_session()
        session["partner_portal_id"] = partner.id
        if active_member:
            session["partner_member_id"] = active_member.id

        flash("Welcome back.", "success")
        return redirect(url_for("partner.portal_dashboard"))

    except Exception as exc:
        current_app.logger.warning(
            "Partner-only login attempt failed for %s: %s", email, exc
        )
        return None
