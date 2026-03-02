import json

from flask import Response
from sqlalchemy import distinct, func

from app import db
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


def stream_programme_export(programme, cohort_slug=None, chunk_size=50):
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
            pagination = Discussion.query.filter_by(
                programme_id=programme.id
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

    return Response(generate(), mimetype='application/json')
