"""The participant's side of a consultation: ``/c/<token>``.

Built to be private and fast:

* No account, no session and no analytics. The only cookie is the voter id.
* Every voter is identified by a fingerprint scoped to this consultation, so a
  vote cannot be linked to the same person's activity anywhere else, even when
  they are signed in to Society Speaks.
* The link token is the capability. It is checked on every request, so
  rotating it cuts off the old link immediately.
"""
import random

from flask import abort, current_app, g, jsonify, make_response, render_template, request
from flask_babel import gettext as _
from flask_limiter.util import get_remote_address
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app import csrf, db, limiter
from app.consultations import consultations_bp, service
from app.lib.content_spam import assess_user_content_spam
from app.lib.session_policy import user_agent_is_bot
from app.lib.statement_results import StatementTally, Verdict, classify, tallies_for_discussion
from app.lib.vote_identity import (
    VOTER_CANONICAL_COOKIE_NAME,
    VOTER_CLIENT_ID_LENGTH,
    scoped_voter_fingerprint,
    set_voter_client_cookies_if_needed,
)
from app.models import Consultation, ModStatus, Statement, StatementVote

# Votes needed before a participant may see how others voted (anti-anchoring).
_RESULTS_MIN_OWN_VOTES = 5
_SUGGESTIONS_PER_PARTICIPANT = 5


def _consultation_or_404(token: str) -> Consultation:
    consultation = Consultation.query.filter_by(access_token=token).first()
    if consultation is None:
        abort(404)
    return consultation


def _fingerprint(consultation: Consultation) -> str:
    return scoped_voter_fingerprint(f'consultation:{consultation.id}')


def _has_voter_cookie() -> bool:
    """Whether the browser sent back the voter id this page gave it."""
    client_id = request.cookies.get(VOTER_CANONICAL_COOKIE_NAME) or ''
    return len(client_id) == VOTER_CLIENT_ID_LENGTH and all(c in '0123456789abcdef' for c in client_id)


def _participant_rate_key() -> str:
    """Per device when the browser has our cookie, else per IP.

    A room on one Wi-Fi shares an IP, so the limit must not be per IP for
    real participants. A client without a well-formed cookie is limited by IP.
    """
    if _has_voter_cookie():
        return f'participant:{request.cookies[VOTER_CANONICAL_COOKIE_NAME][:32]}'
    return f'participant-ip:{get_remote_address()}'


def _private(response):
    """Headers for every participant response."""
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Robots-Tag'] = 'noindex, nofollow'
    # The address is the key to the consultation: never pass it on as a referrer.
    g.referrer_policy = 'no-referrer'
    return set_voter_client_cookies_if_needed(response, include_authenticated=True, canonical_only=True)


def _own_votes(consultation: Consultation, fingerprint: str) -> dict:
    rows = (
        db.session.query(StatementVote.statement_id, StatementVote.vote)
        .filter(
            StatementVote.discussion_id == consultation.discussion_id,
            StatementVote.session_fingerprint == fingerprint,
            StatementVote.user_id.is_(None),
        )
        .all()
    )
    return {statement_id: vote for statement_id, vote in rows}


def _is_owner_preview(consultation: Consultation) -> bool:
    return (
        consultation.is_draft
        and current_user.is_authenticated
        and current_user.id == consultation.owner_user_id
    )


@consultations_bp.route('/consultations/demo')
@limiter.limit('120 per minute', key_func=get_remote_address)
def demo():
    """The participant page with a made-up consultation, for anyone deciding
    whether to buy. It is the real page in preview mode: nothing is sent,
    nothing is stored and no cookie is set."""
    from app.consultations import example

    statements = example.example_statements()
    response = make_response(render_template(
        'consultations/participate.html',
        consultation=example.example_consultation(),
        statements=statements,
        votes={},
        preview=True,
        demo=True,
        minutes=max(1, round(len(statements) * 10 / 60)),
        suggestions_enabled=False,
    ))
    response.headers['X-Robots-Tag'] = 'noindex, follow'
    return response


@consultations_bp.route('/c/<token>')
# A whole hall scanning one QR code arrives from a single address.
@limiter.limit('3000 per minute', key_func=get_remote_address)
def participate(token):
    consultation = _consultation_or_404(token)
    preview = _is_owner_preview(consultation)

    if consultation.is_closed or (consultation.is_draft and not preview):
        return _private(make_response(render_template(
            'consultations/participate_unavailable.html',
            consultation=consultation,
            reason='closed' if consultation.is_closed else 'not_open',
        )))

    fingerprint = _fingerprint(consultation)
    statements = service.published_statements(consultation)
    if not statements:
        # Withdrawing every statement after go-live must not tell people their
        # answers were received. There was nothing to answer.
        return _private(make_response(render_template(
            'consultations/participate_unavailable.html',
            consultation=consultation,
            reason='empty',
        )))
    # Every participant sees the statements in their own, stable order, so no
    # statement is always first.
    random.Random(fingerprint).shuffle(statements)
    votes = {} if preview else _own_votes(consultation, fingerprint)

    return _private(make_response(render_template(
        'consultations/participate.html',
        consultation=consultation,
        statements=[{'id': s.id, 'content': s.content} for s in statements],
        votes={str(statement_id): vote for statement_id, vote in votes.items()},
        preview=preview,
        minutes=max(1, round(len(statements) * 10 / 60)),
        suggestions_enabled=consultation.allow_audience_statements and not preview,
    )))


@consultations_bp.route('/c/<token>/vote', methods=['POST'])
# The link token is the capability and the voter cookie is SameSite=Lax, so a
# forged cross-site vote is just another anonymous voter. Skipping CSRF keeps
# the page free of a server session.
@csrf.exempt
@limiter.limit('120 per minute', key_func=_participant_rate_key)
@limiter.limit('6000 per minute', key_func=get_remote_address)
def vote(token):
    consultation = _consultation_or_404(token)
    if user_agent_is_bot(request.headers.get('User-Agent')):
        return _private(jsonify({'error': 'automated'})), 403
    if not consultation.is_live:
        return _private(jsonify({'error': 'closed'})), 409
    if not _has_voter_cookie():
        # The page sets the cookie before anyone can vote. Without it every
        # vote would count as a new participant.
        return _private(jsonify({'error': 'cookie_required'})), 400

    payload = request.get_json(silent=True) or {}
    try:
        statement_id = int(payload.get('statement_id'))
        vote_value = int(payload.get('vote'))
    except (TypeError, ValueError):
        return _private(jsonify({'error': 'invalid'})), 400
    if vote_value not in (-1, 0, 1):
        return _private(jsonify({'error': 'invalid'})), 400

    statement = db.session.get(Statement, statement_id)
    if (
        statement is None
        or statement.discussion_id != consultation.discussion_id
        or statement.is_deleted
        or (statement.mod_status or 0) < 0
    ):
        return _private(jsonify({'error': 'not_found'})), 404

    from app.discussions.statements import _persist_vote_with_upsert

    fingerprint = _fingerprint(consultation)
    for attempt in (1, 2):
        try:
            _persist_vote_with_upsert(
                statement=statement,
                vote_value=vote_value,
                confidence=None,
                partner_ref=None,
                cohort_slug=None,
                user_id=None,
                session_fingerprint=fingerprint,
                stamp_analytics_identity=False,
            )
            break
        except IntegrityError:
            db.session.rollback()
            if attempt == 2:
                # Not 409: the page reads that as "voting has closed". This one is worth retrying.
                return _private(jsonify({'error': 'busy'})), 503

    return _private(jsonify({'ok': True}))


@consultations_bp.route('/c/<token>/results.json')
@limiter.limit('60 per minute', key_func=_participant_rate_key)
def participant_results(token):
    """How others voted, once the host allows it and the visitor has voted."""
    consultation = _consultation_or_404(token)
    if not consultation.show_results_to_participants or consultation.is_draft:
        abort(404)
    votes = _own_votes(consultation, _fingerprint(consultation))
    published = service.published_statements(consultation)
    needed = min(_RESULTS_MIN_OWN_VOTES, len(published))
    if len(votes) < needed:
        return _private(jsonify({'error': 'vote_first', 'needed': needed - len(votes)})), 403

    tallies = tallies_for_discussion(consultation.discussion_id)
    rows = []
    for statement in published:
        if statement.id not in votes:
            continue
        result = classify(tallies.get(statement.id) or StatementTally(statement.id))
        row = result.to_dict()
        enough = result.verdict != Verdict.TOO_FEW_VOTES
        rows.append({
            'statement_id': statement.id,
            'content': statement.content,
            'your_vote': votes[statement.id],
            'enough_votes': enough,
            # With only a few votes in, the shares would give away how
            # individual people answered, so they are withheld.
            'agree_share': row['agree_share'] if enough else None,
            'disagree_share': row['disagree_share'] if enough else None,
            'unsure_share': row['unsure_share'] if enough else None,
        })
    return _private(jsonify({'results': rows}))


@consultations_bp.route('/c/<token>/statements', methods=['POST'])
@csrf.exempt  # see ``vote``
@limiter.limit('10 per hour', key_func=_participant_rate_key)
@limiter.limit('300 per hour', key_func=get_remote_address)
def suggest_statement(token):
    """A participant suggests a statement. It is held until the host approves it."""
    consultation = _consultation_or_404(token)
    if not consultation.is_live or not consultation.allow_audience_statements:
        return _private(jsonify({'error': 'closed'})), 409
    if user_agent_is_bot(request.headers.get('User-Agent')):
        return _private(jsonify({'error': 'automated'})), 403

    payload = request.get_json(silent=True) or {}
    if payload.get('website_url'):  # honeypot
        return _private(jsonify({'ok': True}))
    content = payload.get('content') or ''

    if assess_user_content_spam(content).blocked:
        return _private(jsonify({
            'error': 'rejected',
            'message': _('That does not look like a statement people can vote on.'),
        })), 400

    fingerprint = _fingerprint(consultation)
    already = Statement.query.filter_by(
        discussion_id=consultation.discussion_id, session_fingerprint=fingerprint,
    ).count()
    if already >= _SUGGESTIONS_PER_PARTICIPANT:
        return _private(jsonify({
            'error': 'limit',
            'message': _('Thank you. You have suggested as many statements as one person can.'),
        })), 429

    try:
        statement = service.add_statement(
            consultation,
            content,
            source=service.SOURCE_AUDIENCE,
            mod_status=ModStatus.PENDING,
            session_fingerprint=fingerprint,
        )
    except service.ConsultationError as exc:
        return _private(jsonify({'error': 'invalid', 'message': str(exc)})), 400
    except IntegrityError:
        db.session.rollback()
        return _private(jsonify({'error': 'invalid', 'message': _('That statement is already in the list.')})), 400

    from app.consultations.jobs import enqueue_screening

    try:
        enqueue_screening(consultation, statement)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Could not queue screening for statement %s', statement.id)
    return _private(jsonify({'ok': True}))
