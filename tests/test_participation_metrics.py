"""Contracts for published participation aggregates."""

from app.lib.participation_metrics import PUBLIC_PARTICIPANT_COUNT_PARAMS, visible_statement_vote_filters
from app.models import Statement


def test_visible_statement_vote_filters_tuple():
    clauses = visible_statement_vote_filters(Statement)
    assert len(clauses) == 2


def test_public_participant_params_document_defaults():
    assert PUBLIC_PARTICIPANT_COUNT_PARAMS["include_deleted_statement_votes"] is False
    assert PUBLIC_PARTICIPANT_COUNT_PARAMS["min_mod_status"] == 0
