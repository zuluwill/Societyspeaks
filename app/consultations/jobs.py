"""Background work for consultations, and the periodic sweep.

Each handler degrades on its own: drafting failure hands the host a blank
page with guidance, a failed narrative leaves the template in place, a failed
PDF leaves the print view, and a failed email is logged. None of them leaves
a consultation stuck.
"""
import logging
from datetime import timedelta

from flask import current_app
from flask_babel import force_locale
from sqlalchemy.exc import IntegrityError

from app import db
from app.consultations import emails, service
from app.lib.job_queue import enqueue_job, job_handler, latest_job, on_dead_letter
from app.lib.llm_client import LLMError
from app.lib.locale_utils import resolve_user_locale
from app.lib.time import utcnow_naive
from app.models import BackgroundJob, Consultation, ConsultationReport, ModStatus, Statement

logger = logging.getLogger(__name__)

JOB_DRAFT = 'consultation.draft_statements'
JOB_REPORT = 'consultation.build_report'
JOB_SCREEN = 'consultation.screen_statement'

# Longer than the handler's worst case (see ``llm_client``: one call can take
# 240 seconds with its retry), so a job still running is never taken for dead.
_DRAFT_TIMEOUT_SECONDS = 360
_REPORT_TIMEOUT_SECONDS = 720
_SCREEN_TIMEOUT_SECONDS = 360

_MODERATION_NOTICE_INTERVAL = timedelta(hours=1)
_CLOSING_SOON_WINDOW = timedelta(hours=24)


def _consultation_for(job):
    return db.session.get(Consultation, job.consultation_id) if job.consultation_id else None


# ── Drafting ────────────────────────────────────────────────────────────────

def drafts_used_today(user_id: int) -> int:
    """Drafting runs this account started in the last day, including for
    consultations it has since deleted."""
    since = utcnow_naive() - timedelta(days=1)
    return BackgroundJob.query.filter(
        BackgroundJob.kind == JOB_DRAFT,
        BackgroundJob.user_id == user_id,
        BackgroundJob.created_at >= since,
    ).count()


def enqueue_drafting(consultation: Consultation):
    """Queue AI drafting. Returns ``(job, created)``; ``(None, False)`` over the daily cap."""
    limit = current_app.config.get('CONSULTATION_DRAFTS_PER_DAY', 6)
    active = latest_job(JOB_DRAFT, consultation.id)
    if active is not None and active.is_active:
        return active, False
    owner = consultation.owner
    if not getattr(owner, 'is_admin', False) and drafts_used_today(consultation.owner_user_id) >= limit:
        return None, False
    return enqueue_job(
        JOB_DRAFT,
        consultation_id=consultation.id,
        user_id=consultation.owner_user_id,
        dedupe_key=f'{JOB_DRAFT}:{consultation.id}',
        timeout_seconds=_DRAFT_TIMEOUT_SECONDS,
    )


def drafting_state(consultation: Consultation) -> dict:
    """Where drafting stands, for the review screen: ``status`` is one of
    ``none``, ``working``, ``done`` or ``failed``."""
    job = latest_job(JOB_DRAFT, consultation.id)
    if job is None:
        return {'status': 'none'}
    if job.is_active:
        return {'status': 'working', 'attempt': job.attempts or 0}
    if job.status == BackgroundJob.STATUS_COMPLETED and not (job.result or {}).get('error'):
        return {'status': 'done', 'added': (job.result or {}).get('added', 0)}
    return {'status': 'failed'}


@job_handler(JOB_DRAFT)
def _draft_statements(job):
    from app.consultations.drafting import draft_statements

    consultation = _consultation_for(job)
    if consultation is None or not consultation.is_draft:
        return {'added': 0}
    # Everything the consultation has seen, so the model does not bring back
    # a statement the host removed.
    existing = [
        s.content for s in Statement.query.filter_by(discussion_id=consultation.discussion_id).all()
    ]
    try:
        drafted = draft_statements(consultation, existing=existing)
    except LLMError as exc:
        if exc.retryable:
            raise
        # Retrying cannot help (no key, declined, malformed): tell the host now.
        emails.notify_drafting_failed(consultation)
        return {'added': 0, 'error': str(exc)}

    added = 0
    for item in drafted:
        try:
            with db.session.begin_nested():
                service.add_statement(
                    consultation, item['content'], source=service.SOURCE_AI,
                    stance=item['stance'], commit=False,
                )
            added += 1
        except (service.ConsultationError, IntegrityError):
            continue
    db.session.commit()
    if added == 0:
        emails.notify_drafting_failed(consultation)
        return {'added': 0, 'error': 'The model returned no usable statements.'}
    return {'added': added}


@on_dead_letter(JOB_DRAFT)
def _drafting_gave_up(job):
    consultation = _consultation_for(job)
    if consultation is not None:
        emails.notify_drafting_failed(consultation)


# ── Report ──────────────────────────────────────────────────────────────────

def enqueue_report(consultation: Consultation, *, kind: str = ConsultationReport.KIND_FINAL):
    return enqueue_job(
        JOB_REPORT,
        consultation_id=consultation.id,
        payload={'kind': kind},
        dedupe_key=f'{JOB_REPORT}:{consultation.id}:{kind}',
        timeout_seconds=_REPORT_TIMEOUT_SECONDS,
    )


def report_state(consultation: Consultation) -> str:
    """``none``, ``working`` or ``failed`` for the newest report job."""
    job = latest_job(JOB_REPORT, consultation.id)
    if job is None:
        return 'none'
    if job.is_active:
        return 'working'
    return 'none' if job.status == BackgroundJob.STATUS_COMPLETED else 'failed'


@job_handler(JOB_REPORT)
def _build_report(job):
    from app.consultations.narrative import ai_narrative
    from app.consultations.pdf import report_pdf
    from app.consultations.report import create_report

    consultation = _consultation_for(job)
    if consultation is None:
        return {'report_id': None}
    kind = (job.payload or {}).get('kind') or ConsultationReport.KIND_FINAL

    # A retried job continues with the report it already froze.
    report_id = (job.result or {}).get('report_id')
    report = db.session.get(ConsultationReport, report_id) if report_id else None
    with force_locale(resolve_user_locale(consultation.owner)):
        if report is None:
            report = create_report(consultation, kind=kind)
            job.result = {'report_id': report.id}
            db.session.commit()

        narrative = ai_narrative(report.data, consultation_id=consultation.id)
        if narrative is not None:
            report.narrative = narrative
            report.narrative_source = ConsultationReport.NARRATIVE_AI
            db.session.commit()

        try:
            report_pdf(report)
        except Exception:
            db.session.rollback()
            logger.exception('PDF rendering failed for report %s', report.id)

    if kind == ConsultationReport.KIND_FINAL:
        emails.notify_report_ready(consultation)
    return {'report_id': report.id, 'narrative': report.narrative_source}


@on_dead_letter(JOB_REPORT)
def _report_gave_up(job):
    """Last resort: freeze a template-only report so the host is never left without one."""
    from app.consultations.report import create_report, latest_report

    consultation = _consultation_for(job)
    if consultation is None:
        return
    kind = (job.payload or {}).get('kind') or ConsultationReport.KIND_FINAL
    # The job may have frozen its report before failing; an older report from
    # before a reopen does not count.
    newest = latest_report(consultation, kind=kind)
    if newest is None or newest.created_at < job.created_at:
        with force_locale(resolve_user_locale(consultation.owner)):
            create_report(consultation, kind=kind)
    if kind == ConsultationReport.KIND_FINAL:
        emails.notify_report_ready(consultation)


# ── Audience suggestions ────────────────────────────────────────────────────

def enqueue_screening(consultation: Consultation, statement: Statement):
    return enqueue_job(
        JOB_SCREEN,
        consultation_id=consultation.id,
        payload={'statement_id': statement.id},
        dedupe_key=f'{JOB_SCREEN}:{statement.id}',
        timeout_seconds=_SCREEN_TIMEOUT_SECONDS,
    )


def screening_notes(consultation: Consultation) -> dict:
    """``{statement_id: {'result', 'concern'}}`` from finished screening jobs."""
    notes = {}
    jobs = BackgroundJob.query.filter_by(
        consultation_id=consultation.id, kind=JOB_SCREEN, status=BackgroundJob.STATUS_COMPLETED,
    ).all()
    for job in jobs:
        statement_id = (job.payload or {}).get('statement_id')
        if statement_id and job.result:
            notes[statement_id] = job.result
    return notes


def _notify_host_of_pending(consultation: Consultation) -> None:
    now = utcnow_naive()
    last = consultation.moderation_notified_at
    if last is not None and (now - last) < _MODERATION_NOTICE_INTERVAL:
        return
    waiting = len(service.pending_statements(consultation))
    if not waiting:
        return
    consultation.moderation_notified_at = now
    db.session.commit()
    emails.notify_statements_waiting(consultation, waiting)


@job_handler(JOB_SCREEN)
def _screen_statement(job):
    from app.consultations.screening import RESULT_REJECT, screen_statement

    consultation = _consultation_for(job)
    statement = db.session.get(Statement, (job.payload or {}).get('statement_id'))
    if consultation is None or statement is None or statement.mod_status != ModStatus.PENDING:
        return {'result': 'skipped', 'concern': 'none'}
    existing = [s.content for s in service.published_statements(consultation)]
    verdict = screen_statement(consultation, statement.content, existing)
    if verdict['result'] == RESULT_REJECT:
        statement.mod_status = ModStatus.REJECTED
        db.session.commit()
    else:
        _notify_host_of_pending(consultation)
    return verdict


@on_dead_letter(JOB_SCREEN)
def _screening_gave_up(job):
    # The suggestion is still pending; the host simply reviews it unscreened.
    consultation = _consultation_for(job)
    if consultation is not None:
        _notify_host_of_pending(consultation)


# ── The sweep ───────────────────────────────────────────────────────────────

def close_and_report(consultation: Consultation) -> None:
    """Close voting and start the final report."""
    service.close(consultation)
    enqueue_report(consultation, kind=ConsultationReport.KIND_FINAL)


def run_sweep() -> dict:
    """Close consultations that are due and send time-based notices.

    Called every few minutes by the scheduler. Safe to run concurrently with
    itself: each action is guarded by a state check or a once-only timestamp.
    """
    closed = 0
    for consultation_id in [c.id for c in service.due_to_close()]:
        try:
            consultation = db.session.get(Consultation, consultation_id)
            if consultation is not None and consultation.is_live:
                close_and_report(consultation)
                closed += 1
        except Exception:
            # One consultation in trouble must not hold up the rest.
            db.session.rollback()
            logger.exception('Sweep could not close consultation %s', consultation_id)

    # Access can end before the closing date (a trial or a pass runs out, or a
    # plan stops). Close those too, and build the report.
    from app.consultations.billing import access_lapsed, mark_passes_in_use
    live_ids_for_access = [
        c.id for c in Consultation.query.filter_by(status=Consultation.STATUS_LIVE).all()
    ]
    for consultation_id in live_ids_for_access:
        try:
            consultation = db.session.get(Consultation, consultation_id)
            if consultation is not None and consultation.is_live and mark_passes_in_use(consultation.owner):
                db.session.commit()
            if consultation is not None and access_lapsed(consultation):
                close_and_report(consultation)
                closed += 1
        except Exception:
            db.session.rollback()
            logger.exception('Sweep could not close consultation %s after access ended', consultation_id)

    notices = 0
    live_ids = [c.id for c in Consultation.query.filter_by(status=Consultation.STATUS_LIVE).all()]
    for consultation_id in live_ids:
        try:
            consultation = db.session.get(Consultation, consultation_id)
            if consultation is not None and consultation.is_live:
                notices += _send_due_notices(consultation)
        except Exception:
            db.session.rollback()
            logger.exception('Sweep could not send notices for consultation %s', consultation_id)

    from app.consultations.billing import settle_pending_refunds, warn_expiring_access

    try:
        warn_expiring_access()
    except Exception:
        db.session.rollback()
        logger.exception('Sweep could not warn hosts that access is ending')
    try:
        refunds = settle_pending_refunds()
    except Exception:
        db.session.rollback()
        logger.exception('Sweep could not settle pending refunds')
        refunds = 0
    return {'closed': closed, 'notices': notices, 'refunds': refunds}


def _closing_soon_window(consultation: Consultation) -> timedelta:
    """A day before closing, or the second half of a shorter consultation, so
    a one-day consultation is not called quiet minutes after it opens."""
    opened = consultation.published_at
    if opened is None or consultation.closes_at is None:
        return _CLOSING_SOON_WINDOW
    return min(_CLOSING_SOON_WINDOW, (consultation.closes_at - opened) / 2)


def _send_due_notices(consultation: Consultation) -> int:
    notices = 0
    now = utcnow_naive()
    counts = service.participation(consultation)
    if consultation.first_response_notified_at is None and counts['participants'] > 0:
        consultation.first_response_notified_at = now
        db.session.commit()
        emails.notify_first_responses(consultation, counts['participants'])
        notices += 1
    if (
        consultation.low_turnout_notified_at is None
        and consultation.closes_at is not None
        and consultation.closes_at - now <= _closing_soon_window(consultation)
        and counts['is_low_turnout']
    ):
        consultation.low_turnout_notified_at = now
        db.session.commit()
        emails.notify_closing_soon(
            consultation, counts['participants'], counts['recommended_participants'],
        )
        notices += 1
    return notices
