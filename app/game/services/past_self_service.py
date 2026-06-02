"""Your own earlier run of the same scenario — for the 'beat your past self' beat.

On a daily loop, scenarios recur. Rather than treat a repeat as stale, we surface
how the player resolved this exact crisis last time and invite them to diverge.
Reuses the archive ownership pattern (account + browser fingerprint).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy import or_
from sqlalchemy.orm import contains_eager

from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.models.game import GameRun


def previous_outcome_for_scenario(run: GameRun) -> Optional[Dict[str, Any]]:
    """Most recent *earlier* completed run of the same scenario by this visitor.

    Returns ``None`` when there's no prior run (first encounter) or no identity.
    """
    ownership = []
    if run.user_id:
        ownership.append(GameRun.user_id == run.user_id)
    if run.session_fingerprint:
        ownership.append(GameRun.session_fingerprint == run.session_fingerprint)
    if not ownership:
        return None

    anchor = run.started_at
    prior = (
        GameRun.query.join(GameRun.outcome)
        .options(contains_eager(GameRun.outcome))
        .filter(
            GameRun.scenario_slug == run.scenario_slug,
            GameRun.status == GAME_RUN_STATUS_COMPLETED,
            GameRun.id != run.id,
            or_(*ownership),
        )
    )
    if anchor is not None:
        prior = prior.filter(GameRun.started_at < anchor)
    prior = prior.order_by(GameRun.started_at.desc()).first()

    if not prior or not prior.outcome:
        return None

    current_headline = run.outcome.headline if run.outcome else None
    return {
        'headline': prior.outcome.headline,
        'governance_label': prior.outcome.governance_label,
        'society_name': prior.society_name,
        'completed_at': prior.completed_at or prior.started_at,
        'run_uuid': prior.uuid,
        'diverged': bool(current_headline and current_headline != prior.outcome.headline),
    }
