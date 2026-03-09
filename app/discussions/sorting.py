"""Shared statement sorting helpers for discussion read paths."""

from sqlalchemy import Float, String, case, cast, desc, func

from app.models import Statement


def statement_total_votes_expr():
    return (
        Statement.vote_count_agree +
        Statement.vote_count_disagree +
        Statement.vote_count_unsure
    )


def apply_statement_sort(query, sort, discussion_id, session):
    """
    Apply deterministic statement ordering across routes.

    `session` is required so we can inspect DB dialect and avoid using
    Postgres-only functions (e.g., md5) on SQLite during local/dev tests.
    """
    total_votes = statement_total_votes_expr()

    if sort == 'progressive':
        bind = session.get_bind() if session else None
        if bind and bind.dialect.name == 'postgresql':
            stable_tiebreak = func.md5(cast(Statement.id, String) + f":{discussion_id}")
            return query.order_by(total_votes.asc(), stable_tiebreak.asc(), Statement.id.asc())
        return query.order_by(total_votes.asc(), Statement.id.asc())

    if sort == 'controversial':
        decisive = Statement.vote_count_agree + Statement.vote_count_disagree
        controversy_expr = case(
            (decisive == 0, 0.0),
            else_=(1.0 - func.abs(cast(Statement.vote_count_agree, Float) / decisive - 0.5) * 2.0),
        )
        return query.order_by(controversy_expr.desc(), Statement.id.asc())

    if sort == 'best':
        return query.order_by(desc(Statement.vote_count_agree), Statement.id.asc())
    if sort == 'recent':
        return query.order_by(desc(Statement.created_at), desc(Statement.id))
    if sort == 'most_voted':
        return query.order_by(desc(total_votes), desc(Statement.id))
    return query.order_by(desc(Statement.created_at), desc(Statement.id))
