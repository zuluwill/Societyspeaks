import csv
import json
import re
from io import StringIO

from flask import Response
from sqlalchemy import distinct, func

from app import db
from app.lib.time import utcnow_naive
from app.models import ConsensusAnalysis, Discussion, StatementVote


def _participant_count_for_cohort(discussion_id, cohort_slug):
    if not cohort_slug:
        return None

    user_count = db.session.query(
        func.count(distinct(StatementVote.user_id))
    ).filter(
        StatementVote.discussion_id == discussion_id,
        StatementVote.cohort_slug == cohort_slug,
        StatementVote.user_id.isnot(None)
    ).scalar() or 0

    anon_count = db.session.query(
        func.count(distinct(StatementVote.session_fingerprint))
    ).filter(
        StatementVote.discussion_id == discussion_id,
        StatementVote.cohort_slug == cohort_slug,
        StatementVote.user_id.is_(None),
        StatementVote.session_fingerprint.isnot(None)
    ).scalar() or 0
    return user_count + anon_count


def build_discussion_export_payload(discussion, cohort_slug=None):
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion.id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()

    cluster_data = analysis.cluster_data if analysis else {}
    if cohort_slug:
        participant_count = _participant_count_for_cohort(discussion.id, cohort_slug)
    else:
        from app.api.utils import get_discussion_participant_count
        participant_count = get_discussion_participant_count(discussion)

    return {
        "discussion_id": discussion.id,
        "title": discussion.title,
        "programme_theme": discussion.programme_theme,
        "programme_phase": discussion.programme_phase,
        "participant_count": participant_count,
        "analysis_date": analysis.created_at.isoformat() if analysis else None,
        "consensus_statements": cluster_data.get("consensus_statements", []),
        "bridge_statements": cluster_data.get("bridge_statements", []),
        "divisive_statements": cluster_data.get("divisive_statements", []),
    }


def _export_filename(programme_slug, cohort_slug, extension):
    safe_slug = re.sub(r'[^a-zA-Z0-9_-]+', '-', (programme_slug or 'programme')).strip('-') or 'programme'
    ts = utcnow_naive().strftime('%Y%m%d-%H%M%S')
    parts = [safe_slug]
    if cohort_slug:
        safe_cohort = re.sub(r'[^a-zA-Z0-9_-]+', '-', cohort_slug).strip('-')
        if safe_cohort:
            parts.append(safe_cohort)
    parts.append(ts)
    return f"{'-'.join(parts)}.{extension}"


def stream_programme_export_json(programme, cohort_slug=None, chunk_size=50):
    def generate():
        yield '{"programme_id":'
        yield json.dumps(programme.id)
        yield ',"programme_slug":'
        yield json.dumps(programme.slug)
        yield ',"programme_name":'
        yield json.dumps(programme.name)
        if cohort_slug:
            yield ',"cohort_slug":'
            yield json.dumps(cohort_slug)
        yield ',"discussions":['

        first = True
        page = 1
        while True:
            pagination = Discussion.query.filter(
                Discussion.programme_id == programme.id,
                Discussion.partner_env != 'test'
            ).order_by(Discussion.created_at.asc()).paginate(
                page=page,
                per_page=chunk_size,
                error_out=False
            )

            if not pagination.items:
                break

            for discussion in pagination.items:
                payload = build_discussion_export_payload(discussion, cohort_slug=cohort_slug)
                if not first:
                    yield ","
                yield json.dumps(payload)
                first = False

            if not pagination.has_next:
                break
            page += 1

        yield "]}"

    response = Response(generate(), mimetype='application/json')
    response.headers['Content-Disposition'] = (
        f'attachment; filename="{_export_filename(programme.slug, cohort_slug, "json")}"'
    )
    return response


def stream_programme_export_csv(programme, cohort_slug=None, chunk_size=200):
    headers = [
        'programme_id',
        'programme_slug',
        'programme_name',
        'cohort_slug',
        'discussion_id',
        'discussion_title',
        'programme_theme',
        'programme_phase',
        'participant_count',
        'analysis_date',
        'consensus_statement_count',
        'bridge_statement_count',
        'divisive_statement_count',
        'consensus_statements_json',
        'bridge_statements_json',
        'divisive_statements_json',
    ]

    def serialize_row(row):
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow([row.get(col, '') for col in headers])
        return buf.getvalue()

    def generate():
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(headers)
        yield buf.getvalue()

        page = 1
        while True:
            pagination = Discussion.query.filter(
                Discussion.programme_id == programme.id,
                Discussion.partner_env != 'test'
            ).order_by(Discussion.created_at.asc()).paginate(
                page=page,
                per_page=chunk_size,
                error_out=False
            )
            if not pagination.items:
                break

            for discussion in pagination.items:
                payload = build_discussion_export_payload(discussion, cohort_slug=cohort_slug)
                row = {
                    'programme_id': programme.id,
                    'programme_slug': programme.slug,
                    'programme_name': programme.name,
                    'cohort_slug': cohort_slug or '',
                    'discussion_id': payload.get('discussion_id'),
                    'discussion_title': payload.get('title') or '',
                    'programme_theme': payload.get('programme_theme') or '',
                    'programme_phase': payload.get('programme_phase') or '',
                    'participant_count': payload.get('participant_count') or 0,
                    'analysis_date': payload.get('analysis_date') or '',
                    'consensus_statement_count': len(payload.get('consensus_statements') or []),
                    'bridge_statement_count': len(payload.get('bridge_statements') or []),
                    'divisive_statement_count': len(payload.get('divisive_statements') or []),
                    'consensus_statements_json': json.dumps(payload.get('consensus_statements') or []),
                    'bridge_statements_json': json.dumps(payload.get('bridge_statements') or []),
                    'divisive_statements_json': json.dumps(payload.get('divisive_statements') or []),
                }
                yield serialize_row(row)

            if not pagination.has_next:
                break
            page += 1

    response = Response(generate(), mimetype='text/csv')
    response.headers['Content-Disposition'] = (
        f'attachment; filename="{_export_filename(programme.slug, cohort_slug, "csv")}"'
    )
    return response
