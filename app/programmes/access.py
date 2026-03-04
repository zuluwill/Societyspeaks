from sqlalchemy import func, literal, or_

from app import db
from app.models import CompanyProfile, OrganizationMember, Programme, ProgrammeAccessGrant, ProgrammeSteward


def programme_access_labels():
    return {
        3: "Owner/Editor",
        2: "Steward",
        1: "Invited participant",
    }


def _editable_org_ids_for_user(user):
    org_ids = set()
    if getattr(user, "company_profile", None):
        org_ids.add(user.company_profile.id)

    memberships = OrganizationMember.query.filter_by(user_id=user.id, status="active").all()
    for membership in memberships:
        if membership.can_edit:
            org_ids.add(membership.org_id)

    return org_ids


def editable_company_profiles(user):
    """Return CompanyProfile objects the user can edit (owner or active editor/admin member)."""
    if not getattr(user, "is_authenticated", False):
        return []
    org_ids = _editable_org_ids_for_user(user)
    if not org_ids:
        return []
    return CompanyProfile.query.filter(CompanyProfile.id.in_(list(org_ids))).order_by(
        CompanyProfile.company_name.asc()
    ).all()


def ranked_programme_access_subquery(user):
    org_ids = _editable_org_ids_for_user(user)
    editable_predicate = or_(
        Programme.creator_id == user.id,
        Programme.company_profile_id.in_(list(org_ids)) if org_ids else Programme.id == -1,
    )

    editable_q = db.session.query(
        Programme.id.label("programme_id"),
        literal(3).label("access_rank"),
    ).filter(editable_predicate)
    stewarded_q = db.session.query(
        ProgrammeSteward.programme_id.label("programme_id"),
        literal(2).label("access_rank"),
    ).filter(
        ProgrammeSteward.user_id == user.id,
        ProgrammeSteward.status == "active",
    )
    invited_q = db.session.query(
        ProgrammeAccessGrant.programme_id.label("programme_id"),
        literal(1).label("access_rank"),
    ).filter(
        ProgrammeAccessGrant.user_id == user.id,
        ProgrammeAccessGrant.status == "active",
    )

    access_union = editable_q.union_all(stewarded_q, invited_q).subquery()
    return db.session.query(
        access_union.c.programme_id,
        func.max(access_union.c.access_rank).label("access_rank"),
    ).group_by(access_union.c.programme_id).subquery()


def query_accessible_programmes(user):
    ranked_access = ranked_programme_access_subquery(user)
    return db.session.query(Programme, ranked_access.c.access_rank).join(
        ranked_access,
        ranked_access.c.programme_id == Programme.id,
    )
