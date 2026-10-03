"""Consultation lifecycle. The only place a consultation changes state.

``draft`` → ``live`` → ``closed`` (and back to ``live`` on reopen). The
discussion underneath is link-only for its whole life and accepts votes only
while the consultation is live.
"""
import secrets
from datetime import timedelta
from typing import List, Optional

from flask import current_app
from flask_babel import gettext as _
from sqlalchemy.exc import IntegrityError

from app import db
from app.lib.participation_metrics import visible_statement_vote_filters
from app.lib.time import utcnow_naive
from app.models import Consultation, Discussion, ModStatus, Statement, StatementVote

SOURCE_AI = 'ai_generated'
SOURCE_HOST = 'host_written'
SOURCE_AUDIENCE = 'user_submitted'

STATEMENT_MIN_LENGTH = 10
STATEMENT_MAX_LENGTH = 300
# The longest a consultation can stay open, counted from now.
MAX_OPEN_DAYS = 90


class ConsultationError(Exception):
    """A lifecycle rule was broken. The message is safe to show the host."""


def create_consultation(
    owner,
    *,
    question: str,
    organisation_name: str,
    context: Optional[str] = None,
    audience_label: Optional[str] = None,
    audience_size: Optional[int] = None,
) -> Consultation:
    """Create a draft consultation and the link-only discussion beneath it."""
    question = ' '.join((question or '').split())
    discussion = Discussion(
        title=question[:200],
        # Random, so the question never appears in a URL.
        slug=f'c-{secrets.token_hex(10)}',
        has_native_statements=True,
        geographic_scope=Discussion.SCOPE_GLOBAL,
        link_only=True,
        # Votes are accepted only while the consultation is live.
        is_closed=True,
    )
    db.session.add(discussion)
    db.session.flush()
    consultation = Consultation(
        discussion_id=discussion.id,
        owner_user_id=owner.id,
        question=question,
        context=(context or '').strip() or None,
        organisation_name=' '.join((organisation_name or '').split()),
        audience_label=(audience_label or '').strip() or None,
        audience_size=audience_size,
        show_results_to_participants=True,
    )
    db.session.add(consultation)
    db.session.commit()
    return consultation


# ── Statements ──────────────────────────────────────────────────────────────

def statements_query(consultation: Consultation):
    return Statement.query.filter(
        Statement.discussion_id == consultation.discussion_id,
        Statement.is_deleted.is_(False),
    )


def published_statements(consultation: Consultation) -> List[Statement]:
    """The statements participants vote on, in a stable order."""
    return (
        Statement.query.filter(
            Statement.discussion_id == consultation.discussion_id,
            *visible_statement_vote_filters(Statement),
        )
        .order_by(Statement.id.asc())
        .all()
    )


def pending_statements(consultation: Consultation) -> List[Statement]:
    """Audience submissions waiting for the host."""
    return (
        statements_query(consultation)
        .filter(Statement.mod_status == ModStatus.PENDING)
        .order_by(Statement.id.asc())
        .all()
    )


def clean_statement_text(content: str) -> str:
    text = ' '.join((content or '').split())
    if len(text) < STATEMENT_MIN_LENGTH:
        raise ConsultationError(_('A statement needs at least 10 characters.'))
    if len(text) > STATEMENT_MAX_LENGTH:
        raise ConsultationError(_('Keep each statement under %(limit)d characters.', limit=STATEMENT_MAX_LENGTH))
    return text


def _is_published(statement: Statement) -> bool:
    return not statement.is_deleted and (statement.mod_status or 0) >= 0


def _same_wording(consultation: Consultation, content: str) -> List[Statement]:
    """Every statement in this consultation with these words, whatever its state."""
    return Statement.query.filter(
        Statement.discussion_id == consultation.discussion_id,
        db.func.lower(Statement.content) == content.lower(),
    ).all()


def _ensure_room(consultation: Consultation) -> None:
    """Only statements people can vote on count towards the limit."""
    limit = current_app.config.get('CONSULTATION_MAX_STATEMENTS', 30)
    if len(published_statements(consultation)) >= limit:
        raise ConsultationError(_('A consultation can have up to %(limit)d statements.', limit=limit))


def _commit_statement() -> None:
    try:
        db.session.commit()
    except IntegrityError:
        # Lost a race with the same wording being added elsewhere.
        db.session.rollback()
        raise ConsultationError(_('That statement is already in the list.'))


def add_statement(
    consultation: Consultation,
    content: str,
    *,
    source: str = SOURCE_HOST,
    stance: Optional[str] = None,
    mod_status: int = ModStatus.ACCEPTED,
    session_fingerprint: Optional[str] = None,
    commit: bool = True,
) -> Statement:
    """Add a statement.

    Wording the consultation has seen before is never duplicated. The host
    adding it again brings the earlier statement back (withdrawn, rejected or
    still waiting); the model and the audience are simply turned away, so
    neither can undo a decision the host made.
    """
    content = clean_statement_text(content)
    matches = _same_wording(consultation, content)
    if any(_is_published(m) for m in matches):
        raise ConsultationError(_('That statement is already in the list.'))
    if matches and source != SOURCE_HOST:
        raise ConsultationError(_('That statement has already been suggested.'))

    if source == SOURCE_AUDIENCE:
        limit = current_app.config.get('CONSULTATION_MAX_STATEMENTS', 30)
        if len(pending_statements(consultation)) >= limit:
            raise ConsultationError(_('This consultation is not taking more suggestions at the moment.'))
    else:
        _ensure_room(consultation)

    # The unique rule on a discussion's statements is exact, so only an exact
    # earlier row has to be reused; a differently-cased one can sit beside it.
    statement = next((m for m in matches if m.content == content), None)
    if statement is not None:
        statement.is_deleted = False
        statement.mod_status = mod_status
    else:
        statement = Statement(
            discussion_id=consultation.discussion_id,
            content=content,
            is_seed=source != SOURCE_AUDIENCE,
            source=source,
            seed_stance=stance,
            mod_status=mod_status,
            session_fingerprint=session_fingerprint,
        )
        db.session.add(statement)
    if commit:
        _commit_statement()
    return statement


def _statement_for(consultation: Consultation, statement_id: int) -> Statement:
    statement = db.session.get(Statement, statement_id)
    if statement is None or statement.discussion_id != consultation.discussion_id or statement.is_deleted:
        raise ConsultationError(_('That statement is no longer in this consultation.'))
    return statement


def edit_statement(consultation: Consultation, statement_id: int, content: str) -> Statement:
    """Rewording is allowed only before anyone has voted on anything."""
    if not consultation.is_draft:
        raise ConsultationError(_(
            'Statements cannot be reworded once voting has started. '
            'Withdraw this one and add a new statement instead.'
        ))
    statement = _statement_for(consultation, statement_id)
    content = clean_statement_text(content)
    others = [m for m in _same_wording(consultation, content) if m.id != statement.id]
    if any(_is_published(m) for m in others):
        raise ConsultationError(_('That statement is already in the list.'))
    for other in others:
        if other.content == content:
            # A withdrawn draft row holding this exact wording. Nobody has
            # voted yet, so it can make way.
            db.session.delete(other)
    db.session.flush()
    if statement.content != content:
        statement.content = content
        if statement.source == SOURCE_AI:
            # The host's wording now, not the model's.
            statement.source = SOURCE_HOST
    _commit_statement()
    return statement


def remove_statement(consultation: Consultation, statement_id: int) -> None:
    """Take a statement out. Votes already cast on it are kept for audit (ADR 0001)."""
    statement = _statement_for(consultation, statement_id)
    statement.is_deleted = True
    db.session.commit()


def approve_statement(consultation: Consultation, statement_id: int) -> Statement:
    statement = _statement_for(consultation, statement_id)
    if not _is_published(statement):
        _ensure_room(consultation)
    statement.mod_status = ModStatus.ACCEPTED
    db.session.commit()
    return statement


def reject_statement(consultation: Consultation, statement_id: int) -> Statement:
    statement = _statement_for(consultation, statement_id)
    statement.mod_status = ModStatus.REJECTED
    db.session.commit()
    return statement


# ── Lifecycle ───────────────────────────────────────────────────────────────

def default_closes_at():
    days = current_app.config.get('CONSULTATION_DEFAULT_OPEN_DAYS', 7)
    return utcnow_naive() + timedelta(days=days)


def publish_blocker(consultation: Consultation) -> Optional[str]:
    """Why this draft cannot go live yet, or None when it can."""
    if not consultation.is_draft:
        return _('This consultation is already live.')
    minimum = current_app.config.get('CONSULTATION_MIN_STATEMENTS', 5)
    count = len(published_statements(consultation))
    if count < minimum:
        return _('Add at least %(minimum)d statements before going live. You have %(count)d.', minimum=minimum, count=count)
    return None


def publish(consultation: Consultation, *, covered_by: str) -> Consultation:
    blocker = publish_blocker(consultation)
    if blocker:
        raise ConsultationError(blocker)
    now = utcnow_naive()
    consultation.status = Consultation.STATUS_LIVE
    consultation.covered_by = covered_by
    consultation.published_at = now
    if consultation.closes_at is None or consultation.closes_at <= now:
        consultation.closes_at = default_closes_at()
    # The host's closing date is kept even when it sits past the end of access.
    # The sweep closes an open consultation when access ends, and a later
    # payment keeps it open until the date they chose.
    consultation.discussion.is_closed = False
    db.session.commit()
    return consultation


def close(consultation: Consultation) -> Consultation:
    """Stop voting. Idempotent: closing a closed consultation changes nothing."""
    if not consultation.is_live:
        return consultation
    consultation.status = Consultation.STATUS_CLOSED
    consultation.closed_at = utcnow_naive()
    consultation.discussion.is_closed = True
    db.session.commit()
    return consultation


def set_closing_time(consultation: Consultation, closes_at) -> Consultation:
    """Move the closing time; reopens a closed consultation.

    A date past the end of access is allowed. Voting still stops when access
    ends, unless the host pays and the new window covers this date.
    """
    if consultation.is_draft:
        consultation.closes_at = closes_at
        db.session.commit()
        return consultation
    now = utcnow_naive()
    if closes_at <= now:
        raise ConsultationError(_('Choose a closing time in the future.'))
    if closes_at > now + timedelta(days=MAX_OPEN_DAYS):
        raise ConsultationError(_(
            'A consultation can stay open for up to %(days)d days from today.', days=MAX_OPEN_DAYS,
        ))
    consultation.closes_at = closes_at
    consultation.status = Consultation.STATUS_LIVE
    consultation.closed_at = None
    consultation.low_turnout_notified_at = None
    consultation.discussion.is_closed = False
    db.session.commit()
    return consultation


def due_to_close() -> List[Consultation]:
    return Consultation.query.filter(
        Consultation.status == Consultation.STATUS_LIVE,
        Consultation.closes_at.isnot(None),
        Consultation.closes_at <= utcnow_naive(),
    ).all()


def delete_consultation(consultation: Consultation, *, commit: bool = True) -> None:
    """Delete a consultation with its statements, votes and reports."""
    from app.models import (
        AnalyticsDailyAggregate,
        AnalyticsEvent,
        BackgroundJob,
        ConsensusAnalysis,
        ConsensusJob,
        ConsultationPurchase,
        DiscussionParticipant,
        DiscussionView,
        LLMUsage,
        Response,
        StatementFlag,
    )

    discussion = consultation.discussion
    discussion_id = consultation.discussion_id
    # Drafting runs are kept, detached, so the daily drafting limit still counts them.
    BackgroundJob.query.filter(
        BackgroundJob.consultation_id == consultation.id,
        BackgroundJob.kind == 'consultation.draft_statements',
        BackgroundJob.user_id.isnot(None),
    ).update({'consultation_id': None, 'result': None}, synchronize_session=False)
    BackgroundJob.query.filter_by(consultation_id=consultation.id).delete(synchronize_session=False)
    # A spent purchase stays spent: ``consumed_at`` is kept.
    ConsultationPurchase.query.filter_by(consultation_id=consultation.id).update(
        {'consultation_id': None}, synchronize_session=False,
    )
    LLMUsage.query.filter_by(consultation_id=consultation.id).update(
        {'consultation_id': None}, synchronize_session=False,
    )
    AnalyticsEvent.query.filter_by(discussion_id=discussion_id).update(
        {'discussion_id': None, 'statement_id': None}, synchronize_session=False,
    )
    # Nothing writes these rows for a consultation. They are cleared anyway so a
    # stray one can never block a customer deleting their data.
    AnalyticsDailyAggregate.query.filter_by(discussion_id=discussion_id).update(
        {'discussion_id': None}, synchronize_session=False,
    )
    statement_ids = db.session.query(Statement.id).filter_by(discussion_id=discussion_id)
    StatementFlag.query.filter(StatementFlag.statement_id.in_(statement_ids)).delete(synchronize_session=False)
    Response.query.filter(Response.statement_id.in_(statement_ids)).delete(synchronize_session=False)
    ConsensusJob.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
    ConsensusAnalysis.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
    DiscussionView.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
    StatementVote.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
    DiscussionParticipant.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
    Statement.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
    db.session.delete(consultation)
    db.session.flush()
    db.session.delete(discussion)
    if commit:
        db.session.commit()
    else:
        db.session.flush()


# ── Counts for the host ─────────────────────────────────────────────────────

def participation(consultation: Consultation) -> dict:
    """Live participant and vote counts, under the published scope."""
    from app.api.utils import get_discussion_participant_count
    from app.lib.participation_metrics import PUBLIC_PARTICIPANT_COUNT_PARAMS

    votes = (
        db.session.query(db.func.count(StatementVote.id))
        .join(Statement, StatementVote.statement_id == Statement.id)
        .filter(
            StatementVote.discussion_id == consultation.discussion_id,
            *visible_statement_vote_filters(Statement),
        )
        .scalar()
        or 0
    )
    participants = get_discussion_participant_count(
        consultation.discussion, **PUBLIC_PARTICIPANT_COUNT_PARAMS
    )
    recommended = current_app.config.get('CONSULTATION_RECOMMENDED_PARTICIPANTS', 30)
    return {
        'participants': participants,
        'votes': int(votes),
        'recommended_participants': recommended,
        'is_low_turnout': participants < recommended,
    }
