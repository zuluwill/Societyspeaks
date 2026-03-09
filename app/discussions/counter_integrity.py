"""Statement vote counter drift metrics and reconciliation helpers."""

from sqlalchemy import case, func

from app import db
from app.models import Statement, StatementVote


def get_statement_counter_drift_metrics(sample_limit=25):
    """
    Compare denormalized statement counters with recomputed vote counts.
    Returns aggregate drift metrics and a small sample for debugging.
    """
    agree_count = func.sum(case((StatementVote.vote == 1, 1), else_=0))
    disagree_count = func.sum(case((StatementVote.vote == -1, 1), else_=0))
    unsure_count = func.sum(case((StatementVote.vote == 0, 1), else_=0))

    counts_subquery = db.session.query(
        StatementVote.statement_id.label('statement_id'),
        agree_count.label('actual_agree'),
        disagree_count.label('actual_disagree'),
        unsure_count.label('actual_unsure'),
    ).group_by(StatementVote.statement_id).subquery()

    rows = db.session.query(
        Statement.id.label('statement_id'),
        Statement.vote_count_agree,
        Statement.vote_count_disagree,
        Statement.vote_count_unsure,
        func.coalesce(counts_subquery.c.actual_agree, 0).label('actual_agree'),
        func.coalesce(counts_subquery.c.actual_disagree, 0).label('actual_disagree'),
        func.coalesce(counts_subquery.c.actual_unsure, 0).label('actual_unsure'),
    ).outerjoin(
        counts_subquery, counts_subquery.c.statement_id == Statement.id
    ).all()

    sample = []
    statements_with_drift = 0
    total_abs_drift = 0
    max_abs_drift = 0
    max_abs_drift_statement_id = None

    for row in rows:
        agree_drift = int(row.vote_count_agree or 0) - int(row.actual_agree or 0)
        disagree_drift = int(row.vote_count_disagree or 0) - int(row.actual_disagree or 0)
        unsure_drift = int(row.vote_count_unsure or 0) - int(row.actual_unsure or 0)
        statement_abs_drift = abs(agree_drift) + abs(disagree_drift) + abs(unsure_drift)
        if statement_abs_drift <= 0:
            continue

        statements_with_drift += 1
        total_abs_drift += statement_abs_drift
        if statement_abs_drift > max_abs_drift:
            max_abs_drift = statement_abs_drift
            max_abs_drift_statement_id = int(row.statement_id)

        if len(sample) < sample_limit:
            sample.append({
                'statement_id': int(row.statement_id),
                'agree_drift': agree_drift,
                'disagree_drift': disagree_drift,
                'unsure_drift': unsure_drift,
                'statement_abs_drift': statement_abs_drift,
            })

    return {
        'statement_count': len(rows),
        'statements_with_drift': statements_with_drift,
        'total_abs_drift': total_abs_drift,
        'max_abs_drift': max_abs_drift,
        'max_abs_drift_statement_id': max_abs_drift_statement_id,
        'sample': sample,
    }


def reconcile_statement_vote_counters():
    """
    Repair denormalized statement vote counters from authoritative vote rows.
    Returns number of statements that had drift before repair.
    """
    agree_count = func.sum(case((StatementVote.vote == 1, 1), else_=0))
    disagree_count = func.sum(case((StatementVote.vote == -1, 1), else_=0))
    unsure_count = func.sum(case((StatementVote.vote == 0, 1), else_=0))

    counts_subquery = db.session.query(
        StatementVote.statement_id.label('statement_id'),
        agree_count.label('actual_agree'),
        disagree_count.label('actual_disagree'),
        unsure_count.label('actual_unsure'),
    ).group_by(StatementVote.statement_id).subquery()

    drifted_statement_ids = db.session.query(Statement.id).outerjoin(
        counts_subquery, counts_subquery.c.statement_id == Statement.id
    ).filter(
        (Statement.vote_count_agree != func.coalesce(counts_subquery.c.actual_agree, 0)) |
        (Statement.vote_count_disagree != func.coalesce(counts_subquery.c.actual_disagree, 0)) |
        (Statement.vote_count_unsure != func.coalesce(counts_subquery.c.actual_unsure, 0))
    ).all()

    drifted_count = len(drifted_statement_ids)
    if drifted_count == 0:
        return 0

    db.session.query(Statement).update({
        Statement.vote_count_agree: db.session.query(
            func.coalesce(func.sum(case((StatementVote.vote == 1, 1), else_=0)), 0)
        ).filter(StatementVote.statement_id == Statement.id).scalar_subquery(),
        Statement.vote_count_disagree: db.session.query(
            func.coalesce(func.sum(case((StatementVote.vote == -1, 1), else_=0)), 0)
        ).filter(StatementVote.statement_id == Statement.id).scalar_subquery(),
        Statement.vote_count_unsure: db.session.query(
            func.coalesce(func.sum(case((StatementVote.vote == 0, 1), else_=0)), 0)
        ).filter(StatementVote.statement_id == Statement.id).scalar_subquery(),
    }, synchronize_session=False)
    db.session.commit()
    return drifted_count
