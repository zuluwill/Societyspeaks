"""Game JSON API."""

from __future__ import annotations

from flask import abort, current_app, jsonify, request
from flask_login import current_user

from app import limiter
from app.game import game_bp
from app.game.services.identity_service import visitor_owns_run
from app.game.services.run_service import (
    GameRunNotFound,
    InvalidChoice,
    RunAlreadyComplete,
    apply_run_choice,
    build_turn_view,
    get_run_by_uuid,
)
from app.lib.vote_identity import get_voter_fingerprint


def _assert_game_enabled() -> None:
    if not current_app.config.get('GAME_ENABLED', True):
        abort(404)


def _assert_run_owner(run) -> bool:
    user_id = current_user.id if current_user.is_authenticated else None
    return visitor_owns_run(
        run,
        user_id=user_id,
        session_fingerprint=get_voter_fingerprint(),
    )


@game_bp.route('/api/run/<run_uuid>/choose', methods=['POST'])
@limiter.limit(lambda: current_app.config.get('GAME_RATE_LIMIT_CHOOSE', '30 per minute'))
def choose(run_uuid: str):
    _assert_game_enabled()

    payload = request.get_json(silent=True) or {}
    choice_id = (payload.get('choice_id') or '').strip()
    if not choice_id:
        return jsonify({'error': 'choice_id required'}), 400

    try:
        run = get_run_by_uuid(run_uuid)
    except GameRunNotFound:
        return jsonify({'error': 'Run not found'}), 404

    if not _assert_run_owner(run):
        return jsonify({'error': 'Forbidden'}), 403

    try:
        result = apply_run_choice(run, choice_id)
    except RunAlreadyComplete:
        return jsonify({'error': 'Run complete', 'outcome_url': f'/play/outcome/{run.uuid}'}), 409
    except InvalidChoice as exc:
        return jsonify({'error': str(exc)}), 400

    # Subscriber↔visitor bridge: a completed turn is real participation, so
    # join email-acquired players to their run identity (no-op otherwise).
    from app.lib.subscriber_identity import link_subscriber_identity_from_request

    link_subscriber_identity_from_request(
        source='game_turn',
        session_fingerprint=run.session_fingerprint,
        user_id=run.user_id,
    )

    return jsonify(result)


@game_bp.route('/api/run/<run_uuid>/state')
@limiter.limit(lambda: current_app.config.get('GAME_RATE_LIMIT_STATE', '60 per minute'))
def run_state(run_uuid: str):
    _assert_game_enabled()

    try:
        run = get_run_by_uuid(run_uuid)
    except GameRunNotFound:
        return jsonify({'error': 'Not found'}), 404

    if not _assert_run_owner(run):
        return jsonify({'error': 'Forbidden'}), 403

    view = build_turn_view(run)
    return jsonify(
        {
            'complete': view.get('complete'),
            'turn_index': run.turn_index,
            'total_turns': run.total_turns,
            'state': view.get('state'),
            'visible_stats': view.get('visible_stats'),
        }
    )
