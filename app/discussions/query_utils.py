from sqlalchemy import and_, or_

from app.models import Discussion, Programme
from app.programmes.access import ranked_programme_access_subquery


def discussion_visibility_predicate(user, discussion_model=Discussion, programme_model=Programme):
    predicates = [
        discussion_model.programme_id.is_(None),
        and_(
            programme_model.status == 'active',
            programme_model.visibility.in_(('public', 'unlisted')),
        ),
    ]
    ranked_access = None
    if getattr(user, 'is_authenticated', False):
        ranked_access = ranked_programme_access_subquery(user)
        predicates.append(ranked_access.c.programme_id.isnot(None))
    return ranked_access, or_(*predicates)


def apply_discussion_visibility(query, user, discussion_model=Discussion, programme_model=Programme):
    ranked_access, predicate = discussion_visibility_predicate(
        user,
        discussion_model=discussion_model,
        programme_model=programme_model,
    )
    query = query.outerjoin(programme_model, discussion_model.programme_id == programme_model.id)
    if ranked_access is not None:
        query = query.outerjoin(ranked_access, ranked_access.c.programme_id == discussion_model.programme_id)
    return query.filter(predicate)
