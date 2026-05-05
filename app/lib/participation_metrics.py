"""
Published participation metrics — single definition for voter aggregates.

Use ``visible_statement_vote_filters`` whenever counts are shown to participants,
partners, or in exports that should match **published** semantics (exclude deleted /
negatively moderated statements).

**Audit / raw:** ``statement_vote`` rows on non-visible statements may still exist for
audit. Exports or analyses that must include every cast vote must be explicitly named
(e.g. raw audit export) and must not reuse published totals without adjustment.
See ``adr/0001-published-vs-audit-vote-semantics.md`` (repo root).

Authenticated voters are keyed by ``StatementVote.user_id``; anonymous voters by
``StatementVote.session_fingerprint``, unified via ``app.lib.vote_identity``
(``anonymous_fingerprint_aliases_for_daily_lookup`` for read paths).
"""

from __future__ import annotations

from typing import Any


def visible_statement_vote_filters(statement_cls: Any) -> tuple:
    """
    Tuple of SQLAlchemy filter clauses: votes only on public-visible statements.

    ``statement_cls`` is normally ``Statement`` from ``app.models``.
    """
    return (
        statement_cls.is_deleted.is_(False),
        statement_cls.mod_status >= 0,
    )


# Arguments for ``get_discussion_participant_count`` aligned with programme summaries / batches.
PUBLIC_PARTICIPANT_COUNT_PARAMS = {
    "include_deleted_statement_votes": False,
    "min_mod_status": 0,
}
