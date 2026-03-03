from app import db
from app.models import CompanyProfile, OrganizationMember, ProgrammeAccessGrant, ProgrammeSteward


def _is_authenticated(user):
    return bool(user and getattr(user, "is_authenticated", False))


def _is_active_org_editor(company_profile_id, user_id):
    if not company_profile_id or not user_id:
        return False

    org = db.session.get(CompanyProfile, company_profile_id)
    if org and org.user_id == user_id:
        return True

    membership = OrganizationMember.query.filter_by(
        org_id=company_profile_id,
        user_id=user_id,
        status='active'
    ).first()
    return bool(membership and membership.can_edit)


def can_edit_programme(programme, user):
    if not _is_authenticated(user):
        return False
    if getattr(user, "is_admin", False):
        return True
    if programme.creator_id and programme.creator_id == user.id:
        return True
    return _is_active_org_editor(programme.company_profile_id, user.id)


def can_steward_programme(programme, user):
    if can_edit_programme(programme, user):
        return True
    if not _is_authenticated(user):
        return False

    direct_steward = ProgrammeSteward.query.filter_by(
        programme_id=programme.id,
        user_id=user.id,
        status='active'
    ).first()
    if direct_steward:
        return True

    return False


def can_add_discussion_to_programme(programme, user):
    return can_edit_programme(programme, user)


def _has_programme_access_grant(programme_id, user_id):
    if not programme_id or not user_id:
        return False
    grant = ProgrammeAccessGrant.query.filter_by(
        programme_id=programme_id,
        user_id=user_id,
        status='active'
    ).first()
    return grant is not None


def can_view_programme(programme, user):
    if can_steward_programme(programme, user):
        return True

    visibility = (getattr(programme, 'visibility', None) or 'public').strip()
    is_active = getattr(programme, 'status', None) == 'active'
    if not is_active:
        return False

    if visibility == 'public':
        return True
    if visibility == 'unlisted':
        return True
    if visibility == 'private':
        return False
    if visibility == 'invite_only':
        if not _is_authenticated(user):
            return False
        return _has_programme_access_grant(programme.id, user.id)

    # Safe default for unknown visibility values.
    return False


def can_participate_in_programme(programme, user):
    return can_view_programme(programme, user)
