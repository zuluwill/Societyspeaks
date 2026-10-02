"""Statement-level results: where an audience agrees, disagrees, is unsure or is split.

The single definition of a statement's result. Every share is **of everyone
who voted on that statement, unsure included**, counted from ``statement_vote``
rows under the published scope (``visible_statement_vote_filters``, ADR 0001).
Nothing here depends on opinion groups or the clustering engine.

The Wilson interval guards against calling a result from a handful of votes.
It is not a claim about people who did not take part: participants choose to
take part, so results describe them and nobody else.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from sqlalchemy import case, func

from app.discussions.thresholds import (
    RESULT_MAJORITY_SHARE,
    RESULT_MIN_VOTES,
    RESULT_SPLIT_MAX_GAP,
    RESULT_SPLIT_MIN_SIDE_SHARE,
    RESULT_UNSURE_SHARE,
)
from app.lib.participation_metrics import (
    PUBLIC_PARTICIPANT_COUNT_PARAMS,
    visible_statement_vote_filters,
)
from app.lib.stats import wilson_interval


class Verdict(str, Enum):
    AGREES = 'agrees'
    DISAGREES = 'disagrees'
    UNSURE = 'unsure'
    SPLIT = 'split'
    NO_CLEAR_RESULT = 'no_clear_result'
    TOO_FEW_VOTES = 'too_few_votes'


# The order findings are presented in.
VERDICT_ORDER = (
    Verdict.AGREES,
    Verdict.DISAGREES,
    Verdict.UNSURE,
    Verdict.SPLIT,
    Verdict.NO_CLEAR_RESULT,
    Verdict.TOO_FEW_VOTES,
)


@dataclass(frozen=True)
class StatementTally:
    statement_id: int
    agree: int = 0
    disagree: int = 0
    unsure: int = 0

    @property
    def total(self) -> int:
        return self.agree + self.disagree + self.unsure

    def share(self, count: int) -> float:
        return count / self.total if self.total else 0.0

    @property
    def agree_share(self) -> float:
        return self.share(self.agree)

    @property
    def disagree_share(self) -> float:
        return self.share(self.disagree)

    @property
    def unsure_share(self) -> float:
        return self.share(self.unsure)


@dataclass(frozen=True)
class StatementResult:
    tally: StatementTally
    verdict: Verdict
    # For NO_CLEAR_RESULT: the largest response, or None on a tie.
    lean: Optional[str]
    # Wilson 95% bounds of the share the verdict rests on (agree share when
    # there is no verdict).
    interval_low: float
    interval_high: float
    # Sort key within a verdict: larger is a stronger finding.
    strength: float

    @property
    def statement_id(self) -> int:
        return self.tally.statement_id

    def to_dict(self) -> dict:
        tally = self.tally
        return {
            'statement_id': tally.statement_id,
            'agree': tally.agree,
            'disagree': tally.disagree,
            'unsure': tally.unsure,
            'total': tally.total,
            'agree_share': round(tally.agree_share, 4),
            'disagree_share': round(tally.disagree_share, 4),
            'unsure_share': round(tally.unsure_share, 4),
            'verdict': self.verdict.value,
            'lean': self.lean,
            'interval_low': round(self.interval_low, 4),
            'interval_high': round(self.interval_high, 4),
        }


@dataclass(frozen=True)
class ResultsSummary:
    discussion_id: int
    participant_count: int
    vote_count: int
    results: List[StatementResult]

    def with_verdict(self, verdict: Verdict) -> List[StatementResult]:
        return [r for r in self.results if r.verdict == verdict]

    def counts_by_verdict(self) -> Dict[str, int]:
        return {verdict.value: len(self.with_verdict(verdict)) for verdict in VERDICT_ORDER}


def _lean(tally: StatementTally) -> Optional[str]:
    ranked = sorted(
        (('agree', tally.agree), ('disagree', tally.disagree), ('unsure', tally.unsure)),
        key=lambda pair: pair[1],
        reverse=True,
    )
    if ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def classify(tally: StatementTally) -> StatementResult:
    """The verdict for one statement's votes."""
    total = tally.total
    __, agree_low, agree_high = wilson_interval(tally.agree, total)
    if total < RESULT_MIN_VOTES:
        return StatementResult(tally, Verdict.TOO_FEW_VOTES, _lean(tally), agree_low, agree_high, float(total))

    if agree_low >= RESULT_MAJORITY_SHARE:
        return StatementResult(tally, Verdict.AGREES, 'agree', agree_low, agree_high, agree_low)

    __, disagree_low, disagree_high = wilson_interval(tally.disagree, total)
    if disagree_low >= RESULT_MAJORITY_SHARE:
        return StatementResult(tally, Verdict.DISAGREES, 'disagree', disagree_low, disagree_high, disagree_low)

    __, unsure_low, unsure_high = wilson_interval(tally.unsure, total)
    if (
        tally.unsure > tally.agree
        and tally.unsure > tally.disagree
        and unsure_low >= RESULT_UNSURE_SHARE
    ):
        return StatementResult(tally, Verdict.UNSURE, 'unsure', unsure_low, unsure_high, unsure_low)

    gap = abs(tally.agree_share - tally.disagree_share)
    if (
        tally.agree_share >= RESULT_SPLIT_MIN_SIDE_SHARE
        and tally.disagree_share >= RESULT_SPLIT_MIN_SIDE_SHARE
        and gap < RESULT_SPLIT_MAX_GAP
    ):
        return StatementResult(tally, Verdict.SPLIT, None, agree_low, agree_high, 1.0 - gap)

    return StatementResult(
        tally, Verdict.NO_CLEAR_RESULT, _lean(tally), agree_low, agree_high, float(total),
    )


def tallies_for_discussion(discussion_id: int) -> Dict[int, StatementTally]:
    """Votes per published statement, including statements nobody has voted on."""
    from app import db
    from app.models import Statement, StatementVote

    rows = (
        db.session.query(
            Statement.id,
            func.coalesce(func.sum(case((StatementVote.vote == 1, 1), else_=0)), 0),
            func.coalesce(func.sum(case((StatementVote.vote == -1, 1), else_=0)), 0),
            func.coalesce(func.sum(case((StatementVote.vote == 0, 1), else_=0)), 0),
        )
        .outerjoin(StatementVote, StatementVote.statement_id == Statement.id)
        .filter(
            Statement.discussion_id == discussion_id,
            *visible_statement_vote_filters(Statement),
        )
        .group_by(Statement.id)
        .all()
    )
    return {
        statement_id: StatementTally(statement_id, int(agree), int(disagree), int(unsure))
        for statement_id, agree, disagree, unsure in rows
    }


def results_for_discussion(discussion) -> ResultsSummary:
    """Every published statement's result, strongest findings first within each verdict."""
    from app.api.utils import get_discussion_participant_count

    results = [classify(tally) for tally in tallies_for_discussion(discussion.id).values()]
    verdict_rank = {verdict: rank for rank, verdict in enumerate(VERDICT_ORDER)}
    results.sort(key=lambda r: (verdict_rank[r.verdict], -r.strength, r.statement_id))
    return ResultsSummary(
        discussion_id=discussion.id,
        participant_count=get_discussion_participant_count(
            discussion, **PUBLIC_PARTICIPANT_COUNT_PARAMS
        ),
        vote_count=sum(r.tally.total for r in results),
        results=results,
    )
