from flask import current_app, session

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
