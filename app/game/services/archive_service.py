"""Completed runs owned by a visitor (account + browser fingerprint)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import func, or_
from sqlalchemy.orm import contains_eager

from app import db
from app.game.constants import GAME_RUN_STATUS_COMPLETED
from app.game.engine.emblem import emblem_for_run
from app.game.engine.scenario import load_scenario
from app.game.services.identity_service import ownership_clauses
from app.models.game import GameRun

_DEFAULT_LIMIT = 60


def count_completed_societies_for_visitor(
    *,
    user_id: Optional[int],
    session_fingerprint: Optional[str],
) -> int:
    """Total completed-with-outcome runs owned by this visitor.

    Index-only on ``idx_game_run_user_status`` / ``idx_game_run_fingerprint_status``.
    """
    ownership = ownership_clauses(user_id, session_fingerprint)
    if not ownership:
        return 0
    return (
        db.session.query(func.count(GameRun.id))
        .join(GameRun.outcome)
        .filter(
            GameRun.status == GAME_RUN_STATUS_COMPLETED,
            or_(*ownership),
        )
        .scalar()
        or 0
    )


def completed_societies_for_visitor(
    *,
    user_id: Optional[int],
    session_fingerprint: Optional[str],
    limit: int = _DEFAULT_LIMIT,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """Return this visitor's completed runs, newest first, as view dicts.

    Inner-joins the outcome (so only finished runs surface) and eager-loads it
    to avoid an N+1 over the page. ``offset``/``limit`` support pagination.
    """
    ownership = ownership_clauses(user_id, session_fingerprint)
    if not ownership:
        return []

    runs = (
        GameRun.query.join(GameRun.outcome)
        .options(contains_eager(GameRun.outcome))
        .filter(
            GameRun.status == GAME_RUN_STATUS_COMPLETED,
            or_(*ownership),
        )
        .order_by(GameRun.completed_at.desc().nullslast())
        .offset(max(0, offset))
        .limit(limit)
        .all()
    )

    title_cache: Dict[str, str] = {}

    def _title(slug: str) -> str:
        if slug not in title_cache:
            try:
                title_cache[slug] = load_scenario(slug).get('title', slug)
            except Exception:  # noqa: BLE001 — missing scenario shouldn't break the gallery
                title_cache[slug] = slug
        return title_cache[slug]

    societies: List[Dict[str, Any]] = []
    for run in runs:
        outcome = run.outcome
        societies.append(
            {
                'run_uuid': run.uuid,
                'society_name': run.society_name,
                'headline': outcome.headline,
                'governance_label': outcome.governance_label,
                'scenario_title': _title(run.scenario_slug),
                'scenario_slug': run.scenario_slug,
                'is_quick_run': run.mode == 'quick',
                'completed_at': run.completed_at or run.started_at,
                'emblem': emblem_for_run(run),
                'trait_chips': (outcome.trait_chips_json or [])[:3],
            }
        )
    return societies
