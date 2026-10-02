"""Build a consultation report.

``build_report_data`` computes every number from the votes and freezes it.
Nothing downstream (the page, the PDF, the AI narrative) may introduce a
number that is not in that data.
"""
import hashlib
import json
from typing import Optional

from flask import current_app

from app import db
from app.lib.statement_results import VERDICT_ORDER, results_for_discussion
from app.lib.time import utcnow_naive
from app.models import ConsultationReport, Statement

REPORT_VERSION = 1


def _iso(value) -> Optional[str]:
    return value.replace(microsecond=0).isoformat() if value else None


def build_report_data(
    discussion,
    *,
    question: str,
    organisation_name: str,
    audience_label: Optional[str] = None,
    audience_size: Optional[int] = None,
    opened_at=None,
    closed_at=None,
) -> dict:
    """The findings for one discussion, as plain JSON-serialisable data."""
    summary = results_for_discussion(discussion)
    statements = {
        s.id: s
        for s in Statement.query.filter(
            Statement.id.in_([r.statement_id for r in summary.results] or [0])
        ).all()
    }
    rows = []
    for result in summary.results:
        statement = statements.get(result.statement_id)
        if statement is None:
            continue
        row = result.to_dict()
        row['content'] = statement.content
        row['source'] = statement.source
        rows.append(row)

    recommended = current_app.config.get('CONSULTATION_RECOMMENDED_PARTICIPANTS', 30)
    response_rate = None
    if audience_size and audience_size > 0:
        response_rate = round(min(1.0, summary.participant_count / audience_size), 4)

    return {
        'version': REPORT_VERSION,
        'question': question,
        'organisation_name': organisation_name,
        'audience_label': audience_label,
        'audience_size': audience_size,
        'opened_at': _iso(opened_at),
        'closed_at': _iso(closed_at),
        'generated_at': _iso(utcnow_naive()),
        'participant_count': summary.participant_count,
        'vote_count': summary.vote_count,
        'statement_count': len(rows),
        'response_rate': response_rate,
        'recommended_participants': recommended,
        'is_low_turnout': summary.participant_count < recommended,
        'counts': summary.counts_by_verdict(),
        'statements': rows,
    }


def data_hash(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def statements_by_verdict(data: dict) -> list:
    """``[(verdict, [statement rows])]`` in presentation order, empty groups included."""
    grouped = {verdict.value: [] for verdict in VERDICT_ORDER}
    for row in data.get('statements') or []:
        grouped.setdefault(row['verdict'], []).append(row)
    return [(verdict.value, grouped[verdict.value]) for verdict in VERDICT_ORDER]


def report_view_context(data: dict, narrative: dict, narrative_source: str, *, is_interim: bool = False) -> dict:
    """What ``_report_body.html`` needs, however it is being rendered."""
    from datetime import datetime

    from flask_babel import format_date

    from app.lib.url_utils import route_url
    from app.storage_utils import get_base_url

    def _day(iso):
        return format_date(datetime.fromisoformat(iso), 'd MMMM y') if iso else None

    opened, closed = _day(data.get('opened_at')), _day(data.get('closed_at'))
    return {
        'data': data,
        # Dates in the reader's language; a one-day consultation shows one date.
        'period_label': opened if closed in (None, opened) else f'{opened} – {closed}',
        'generated_label': _day(data.get('generated_at')),
        'narrative': narrative,
        'narrative_source': narrative_source,
        'groups': statements_by_verdict(data),
        'is_interim': is_interim,
        'product_url': route_url(get_base_url(), 'consultations.landing'),
    }


def create_report(consultation, *, kind: str = ConsultationReport.KIND_FINAL) -> ConsultationReport:
    """Freeze the current results as a report, with the template narrative.

    The report is usable from this moment. The AI narrative, when it passes
    validation, replaces the template afterwards.
    """
    from app.consultations.narrative import template_narrative

    data = build_report_data(
        consultation.discussion,
        question=consultation.question,
        organisation_name=consultation.organisation_name,
        audience_label=consultation.audience_label,
        audience_size=consultation.audience_size,
        opened_at=consultation.published_at,
        closed_at=consultation.closed_at,
    )
    report = ConsultationReport(
        consultation_id=consultation.id,
        kind=kind,
        data=data,
        data_hash=data_hash(data),
        narrative=template_narrative(data),
        narrative_source=ConsultationReport.NARRATIVE_TEMPLATE,
    )
    db.session.add(report)
    db.session.commit()
    return report


def latest_report(consultation, *, kind: Optional[str] = None) -> Optional[ConsultationReport]:
    query = ConsultationReport.query.filter_by(consultation_id=consultation.id)
    if kind:
        query = query.filter_by(kind=kind)
    return query.order_by(ConsultationReport.id.desc()).first()


def report_csv_rows(data: dict) -> list:
    """Header plus one row per statement, for the CSV download."""
    header = [
        'statement', 'result', 'agree', 'disagree', 'unsure', 'votes',
        'agree_share', 'disagree_share', 'unsure_share', 'written_by',
    ]
    rows = [header]
    for row in data.get('statements') or []:
        rows.append([
            row['content'], row['verdict'], row['agree'], row['disagree'], row['unsure'],
            row['total'], row['agree_share'], row['disagree_share'], row['unsure_share'],
            'audience' if row.get('source') == 'user_submitted' else 'organiser',
        ])
    return rows
