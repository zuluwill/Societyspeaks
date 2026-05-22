"""Friend challenge links — plan §6.2."""

from __future__ import annotations

import logging
import secrets
from typing import Any, Dict, Optional

from flask import url_for
from flask_babel import _
from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.game.constants import DEFAULT_SOCIETY_NAME, GAME_RUN_STATUS_COMPLETED
from app.game.services.daily_service import utc_game_date
from app.lib.time import utcnow_naive
from app.models.game import GameChallenge, GameRun

logger = logging.getLogger(__name__)

# Sentinel stored in the DB when the creator kept the default society name.
# The challenge-view path renders this through gettext at request time so the
# label localises to the viewer's language rather than the creator's.
_ANONYMOUS_CREATOR_TOKEN = '__anon__'


def _creator_display_name(run: GameRun) -> str:
    name = (run.society_name or '').strip()
    if name and name != DEFAULT_SOCIETY_NAME:
        return name[:48]
    return _ANONYMOUS_CREATOR_TOKEN


def _localised_display_name(stored: Optional[str]) -> str:
    """Resolve the stored display name to the viewer's locale at render time."""
    if not stored or stored == _ANONYMOUS_CREATOR_TOKEN:
        return _('Someone')
    return stored


def get_or_create_challenge(run: GameRun) -> Optional[GameChallenge]:
    """Idempotently create a challenge link for a completed run."""
    if run.status != GAME_RUN_STATUS_COMPLETED or not run.outcome:
        return None

    try:
        existing = GameChallenge.query.filter_by(creator_run_id=run.id).first()
        if existing:
            return existing

        schedule_date = None
        if run.mode == 'daily' and run.started_at:
            schedule_date = run.started_at.date()

        challenge = GameChallenge(
            token=secrets.token_urlsafe(18),
            creator_run_id=run.id,
            scenario_slug=run.scenario_slug,
            mode=run.mode,
            schedule_date=schedule_date,
            creator_display_name=_creator_display_name(run),
            creator_headline=(run.outcome.headline or '')[:300],
            created_at=utcnow_naive(),
        )
        db.session.add(challenge)
        db.session.commit()
        return challenge
    except SQLAlchemyError as exc:
        logger.error('get_or_create_challenge failed for run %s: %s', run.uuid, exc)
        db.session.rollback()
        return None


def challenge_url(challenge: GameChallenge, *, _external: bool = True) -> str:
    return url_for('game.challenge', token=challenge.token, _external=_external)


def challenge_play_target(challenge: GameChallenge) -> Dict[str, Any]:
    """Resolve where the challenged friend should start playing."""
    if challenge.mode == 'daily' and challenge.schedule_date:
        today = utc_game_date()
        age_days = (today - challenge.schedule_date).days
        if 0 <= age_days <= 2:
            return {
                'endpoint': 'daily',
                'schedule_date': challenge.schedule_date.isoformat(),
            }
    return {
        'endpoint': 'quick_run',
        'scenario_slug': challenge.scenario_slug,
    }


def challenge_reveal_for_run(
    *,
    completed_run: GameRun,
    pending_token: Optional[str],
) -> Optional[Dict[str, str]]:
    """After the friend finishes, return the creator headline (plan §6.2 v1)."""
    if not pending_token or completed_run.status != GAME_RUN_STATUS_COMPLETED:
        return None

    challenge = GameChallenge.query.filter_by(token=pending_token).first()
    if not challenge or challenge.creator_run_id == completed_run.id:
        return None

    if completed_run.scenario_slug != challenge.scenario_slug:
        return None

    return {
        'display_name': _localised_display_name(challenge.creator_display_name),
        'headline': challenge.creator_headline or '',
        'scenario_slug': challenge.scenario_slug,
    }
