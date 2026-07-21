#!/usr/bin/env python3
"""
Backfill source_statement_id for brief-sourced daily questions and replay
daily_question_response rows into statement_vote.

Safe to re-run: skips questions already linked and responses already synced.

Usage:
    DATABASE_URL=... python3 scripts/backfill_brief_question_statement_links.py
    DATABASE_URL=... python3 scripts/backfill_brief_question_statement_links.py --apply
    DATABASE_URL=... python3 scripts/backfill_brief_question_statement_links.py --apply --since 2026-07-19
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.daily.auto_selection import BRIEF_SOURCE_TYPE, resolve_brief_primary_statement_id
from app.models import DailyQuestion, DailyQuestionResponse, Statement, StatementVote


def _existing_statement_vote(response, statement_id):
    if response.user_id:
        return StatementVote.query.filter_by(
            statement_id=statement_id,
            user_id=response.user_id,
        ).first()
    if response.session_fingerprint:
        return StatementVote.query.filter(
            StatementVote.statement_id == statement_id,
            StatementVote.user_id.is_(None),
            StatementVote.session_fingerprint == response.session_fingerprint,
        ).first()
    return None


def _increment_statement_counts(statement, vote_value):
    if vote_value == 1:
        statement.vote_count_agree = (statement.vote_count_agree or 0) + 1
    elif vote_value == -1:
        statement.vote_count_disagree = (statement.vote_count_disagree or 0) + 1
    else:
        statement.vote_count_unsure = (statement.vote_count_unsure or 0) + 1


def backfill(*, apply: bool, since=None):
    app = create_app()
    with app.app_context():
        query = DailyQuestion.query.filter(
            DailyQuestion.source_type == BRIEF_SOURCE_TYPE,
            DailyQuestion.source_discussion_id.isnot(None),
        )
        if since:
            query = query.filter(DailyQuestion.question_date >= since)

        questions = query.order_by(DailyQuestion.question_date.asc()).all()
        linked = 0
        replayed = 0
        skipped_votes = 0

        for question in questions:
            stmt_id = question.source_statement_id
            if not stmt_id:
                stmt_id = resolve_brief_primary_statement_id(
                    question.question_text, question.source_discussion_id
                )
                if stmt_id:
                    print(
                        f"  link Q#{question.question_number} ({question.question_date}) "
                        f"→ statement {stmt_id}"
                    )
                    if apply:
                        question.source_statement_id = stmt_id
                    linked += 1
                else:
                    print(
                        f"  skip Q#{question.question_number} ({question.question_date}): "
                        f"no matching seed in discussion {question.source_discussion_id}"
                    )
                    continue

            statement = db.session.get(Statement, stmt_id)
            if not statement:
                print(f"  skip Q#{question.id}: statement {stmt_id} missing")
                continue

            responses = DailyQuestionResponse.query.filter_by(
                daily_question_id=question.id
            ).all()
            for response in responses:
                if _existing_statement_vote(response, stmt_id):
                    skipped_votes += 1
                    continue
                print(
                    f"    replay response {response.id} vote={response.vote} "
                    f"user={response.user_id} fp={response.session_fingerprint!r}"
                )
                if apply:
                    db.session.add(
                        StatementVote(
                            statement_id=stmt_id,
                            discussion_id=question.source_discussion_id,
                            user_id=response.user_id,
                            session_fingerprint=(
                                response.session_fingerprint
                                if not response.user_id
                                else None
                            ),
                            vote=response.vote,
                        )
                    )
                    _increment_statement_counts(statement, response.vote)
                replayed += 1

        if apply:
            db.session.commit()
        else:
            db.session.rollback()

        mode = "APPLIED" if apply else "DRY RUN"
        print(
            f"\n{mode}: {linked} question(s) linked, "
            f"{replayed} vote(s) replayed, {skipped_votes} already synced"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist changes (default is dry-run)',
    )
    parser.add_argument(
        '--since',
        type=str,
        default='2026-07-19',
        help='Only process questions on/after this date (YYYY-MM-DD)',
    )
    args = parser.parse_args()
    from datetime import date

    since = date.fromisoformat(args.since) if args.since else None
    backfill(apply=args.apply, since=since)


if __name__ == '__main__':
    main()
