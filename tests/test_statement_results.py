"""Statement-level results: the rules, and the counts they rest on.

The acceptance tests run synthetic audiences with a known truth through
``classify``. They are what stands between a customer and a report that calls
a result the votes do not support.
"""
import random

import pytest

from app.lib.statement_results import (
    StatementTally,
    Verdict,
    classify,
    results_for_discussion,
    tallies_for_discussion,
)
from app.discussions.thresholds import RESULT_MIN_VOTES
from app.models import Statement, StatementVote
from tests.test_consensus_report_and_export import _create_user, _discussion, _statement


def _verdict(agree, disagree, unsure):
    return classify(StatementTally(1, agree, disagree, unsure)).verdict


# ── The rules ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize('agree, disagree, unsure, expected', [
    (2, 2, 0, Verdict.TOO_FEW_VOTES),          # 4 votes: counts only
    (4, 0, 0, Verdict.TOO_FEW_VOTES),          # unanimous, still too few
    (4, 2, 0, Verdict.NO_CLEAR_RESULT),        # 6 votes: called, but no majority
    (9, 0, 0, Verdict.AGREES),                 # unanimous small room is a result
    (24, 4, 2, Verdict.AGREES),                # 80% of 30
    (9, 1, 0, Verdict.AGREES),                 # 9 of 10
    (4, 24, 2, Verdict.DISAGREES),
    (18, 8, 4, Verdict.NO_CLEAR_RESULT),       # 60% of 30: a lean, not a finding
    (7, 2, 1, Verdict.NO_CLEAR_RESULT),        # 7 of 10
    (60, 30, 10, Verdict.AGREES),              # 60% of 100 clears the bar
    (20, 20, 60, Verdict.UNSURE),
    (35, 20, 45, Verdict.UNSURE),
    (44, 41, 15, Verdict.SPLIT),
    (50, 50, 0, Verdict.SPLIT),
    (36, 36, 28, Verdict.SPLIT),
    (34, 33, 33, Verdict.NO_CLEAR_RESULT),     # three-way: nothing to call
    (55, 30, 15, Verdict.NO_CLEAR_RESULT),     # ahead, not a confident majority
])
def test_verdict_rules(agree, disagree, unsure, expected):
    assert _verdict(agree, disagree, unsure) == expected


def test_no_clear_result_reports_its_lean():
    assert classify(StatementTally(1, 18, 8, 4)).lean == 'agree'
    assert classify(StatementTally(1, 8, 18, 4)).lean == 'disagree'
    assert classify(StatementTally(1, 12, 12, 6)).lean is None


def test_shares_include_unsure_votes():
    tally = StatementTally(1, agree=10, disagree=5, unsure=5)
    assert tally.total == 20
    assert tally.agree_share == 0.5
    assert tally.unsure_share == 0.25


def test_a_statement_with_no_votes_has_no_verdict():
    result = classify(StatementTally(1))
    assert result.verdict == Verdict.TOO_FEW_VOTES
    assert result.tally.agree_share == 0.0


# ── Synthetic audiences with a known truth ──────────────────────────────────

def _simulate(rng, participants, p_agree, p_disagree, missing=0.2):
    agree = disagree = unsure = 0
    for _participant in range(participants):
        if rng.random() < missing:
            continue
        draw = rng.random()
        if draw < p_agree:
            agree += 1
        elif draw < p_agree + p_disagree:
            disagree += 1
        else:
            unsure += 1
    return StatementTally(1, agree, disagree, unsure)


def _verdict_rates(participants, p_agree, p_disagree, runs=2000, seed=20261002):
    rng = random.Random(seed + participants)
    counts = {verdict: 0 for verdict in Verdict}
    for _run in range(runs):
        counts[classify(_simulate(rng, participants, p_agree, p_disagree)).verdict] += 1
    return {verdict: count / runs for verdict, count in counts.items()}


@pytest.mark.parametrize('participants', [30, 60, 120, 400])
def test_random_votes_are_almost_never_called_a_finding(participants):
    rates = _verdict_rates(participants, 1 / 3, 1 / 3)
    assert rates[Verdict.AGREES] < 0.01
    assert rates[Verdict.DISAGREES] < 0.01
    assert rates[Verdict.UNSURE] < 0.05


@pytest.mark.parametrize('participants', [40, 60, 120, 400])
def test_broad_agreement_is_called_agreement(participants):
    rates = _verdict_rates(participants, 0.80, 0.12)
    assert rates[Verdict.AGREES] > 0.95
    assert rates[Verdict.DISAGREES] == 0


@pytest.mark.parametrize('participants', [120, 400])
def test_an_evenly_divided_audience_is_split_not_unsure(participants):
    rates = _verdict_rates(participants, 0.47, 0.47)
    assert rates[Verdict.UNSURE] == 0
    assert rates[Verdict.AGREES] < 0.02
    assert rates[Verdict.DISAGREES] < 0.02
    assert rates[Verdict.SPLIT] > 0.75


@pytest.mark.parametrize('participants', [60, 120, 400])
def test_an_unsure_audience_is_unsure_not_split(participants):
    rates = _verdict_rates(participants, 0.20, 0.20)
    assert rates[Verdict.SPLIT] == 0
    assert rates[Verdict.UNSURE] > 0.95


def test_a_small_audience_gets_no_verdict_rather_than_a_wrong_one():
    rates = _verdict_rates(RESULT_MIN_VOTES - 1, 0.80, 0.12)
    assert rates[Verdict.TOO_FEW_VOTES] == 1.0


# ── The counts ──────────────────────────────────────────────────────────────

def _vote(db, discussion_id, statement_id, fingerprint, vote):
    db.session.add(StatementVote(
        statement_id=statement_id, discussion_id=discussion_id,
        session_fingerprint=fingerprint, vote=vote,
    ))


@pytest.fixture
def discussion(db):
    owner = _create_user(db, 'resultsowner', 'resultsowner@example.com')
    discussion = _discussion(db, owner.id, title='Statement Results Fixture')
    db.session.commit()
    return discussion


def test_tallies_are_counted_from_vote_rows_not_cached_counters(db, discussion):
    statement = _statement(db, discussion.id, discussion.creator_id, 'Counted from rows, not counters.', agree=99)
    for index, vote in enumerate([1, 1, 1, -1, 0]):
        _vote(db, discussion.id, statement.id, f'fp-{index}', vote)
    db.session.commit()

    tally = tallies_for_discussion(discussion.id)[statement.id]

    assert (tally.agree, tally.disagree, tally.unsure) == (3, 1, 1)


def test_deleted_and_rejected_statements_are_left_out(db, discussion):
    kept = _statement(db, discussion.id, discussion.creator_id, 'A statement that stays published.')
    deleted = _statement(db, discussion.id, discussion.creator_id, 'A statement that was deleted.')
    rejected = _statement(db, discussion.id, discussion.creator_id, 'A statement a moderator rejected.')
    deleted.is_deleted = True
    rejected.mod_status = -1
    for statement in (kept, deleted, rejected):
        _vote(db, discussion.id, statement.id, 'fp-a', 1)
    db.session.commit()

    summary = results_for_discussion(discussion)

    assert [r.statement_id for r in summary.results] == [kept.id]
    assert summary.vote_count == 1
    assert summary.participant_count == 1


def test_a_statement_nobody_voted_on_is_still_listed(db, discussion):
    statement = _statement(db, discussion.id, discussion.creator_id, 'Nobody has voted on this yet.')
    db.session.commit()

    tally = tallies_for_discussion(discussion.id)[statement.id]

    assert tally.total == 0


def test_changing_a_vote_moves_one_count(db, discussion):
    statement = _statement(db, discussion.id, discussion.creator_id, 'A statement someone reconsiders.')
    _vote(db, discussion.id, statement.id, 'fp-a', 1)
    _vote(db, discussion.id, statement.id, 'fp-b', 1)
    db.session.commit()

    vote = StatementVote.query.filter_by(statement_id=statement.id, session_fingerprint='fp-a').one()
    vote.vote = -1
    db.session.commit()
    tally = tallies_for_discussion(discussion.id)[statement.id]

    assert (tally.agree, tally.disagree, tally.unsure) == (1, 1, 0)


def test_results_are_ordered_strongest_finding_first(db, discussion):
    weaker = _statement(db, discussion.id, discussion.creator_id, 'Most people agree with this one.')
    stronger = _statement(db, discussion.id, discussion.creator_id, 'Nearly everyone agrees with this one.')
    rejected_idea = _statement(db, discussion.id, discussion.creator_id, 'Nearly everyone rejects this one.')
    for index in range(20):
        _vote(db, discussion.id, stronger.id, f'fp-{index}', 1)
        _vote(db, discussion.id, weaker.id, f'fp-{index}', 1 if index < 16 else -1)
        _vote(db, discussion.id, rejected_idea.id, f'fp-{index}', -1)
    db.session.commit()

    summary = results_for_discussion(discussion)

    assert [r.statement_id for r in summary.results] == [stronger.id, weaker.id, rejected_idea.id]
    assert summary.counts_by_verdict()['agrees'] == 2
    assert summary.counts_by_verdict()['disagrees'] == 1
    assert summary.participant_count == 20
    assert summary.vote_count == 60
