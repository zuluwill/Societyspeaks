"""
Rank discussion topics by engagement for guided-journey curriculum design.

Used by `flask journey-theme-analytics` and importable for admin tooling.
"""
from __future__ import annotations

from typing import Any, List

from sqlalchemy import func

from app import db
from app.models import Discussion, StatementVote, TrendingTopic


def compute_topic_rankings(limit: int = 15) -> List[dict[str, Any]]:
    """
    Rank Discussion.topic by vote volume and participant breadth, with optional
    civic/quality signals from published TrendingTopic rows on the same primary_topic.
    """
    vote_rows = (
        db.session.query(
            Discussion.topic.label("topic"),
            func.count(StatementVote.id).label("vote_count"),
            func.count(func.distinct(StatementVote.user_id)).label("distinct_users"),
        )
        .join(StatementVote, StatementVote.discussion_id == Discussion.id)
        .filter(
            Discussion.topic.isnot(None),
            Discussion.partner_env != "test",
        )
        .group_by(Discussion.topic)
        .all()
    )

    disc_counts = dict(
        db.session.query(Discussion.topic, func.count(Discussion.id))
        .filter(
            Discussion.topic.isnot(None),
            Discussion.partner_env != "test",
        )
        .group_by(Discussion.topic)
        .all()
    )

    topic_meta = {}
    for row in (
        db.session.query(
            TrendingTopic.primary_topic,
            func.avg(TrendingTopic.civic_score),
            func.avg(TrendingTopic.quality_score),
        )
        .filter(
            TrendingTopic.primary_topic.isnot(None),
            TrendingTopic.status == "published",
        )
        .group_by(TrendingTopic.primary_topic)
        .all()
    ):
        topic_meta[row[0]] = (row[1], row[2])

    out: List[dict[str, Any]] = []
    for topic, vote_count, distinct_users in vote_rows:
        votes = int(vote_count or 0)
        users = int(distinct_users or 0)
        dcount = int(disc_counts.get(topic, 0))
        meta = topic_meta.get(topic)
        civic = float(meta[0] or 0) if meta else 0.0
        quality = float(meta[1] or 0) if meta else 0.0
        composite = votes * 1.0 + users * 2.0 + dcount * 3.0 + civic * 50 + quality * 30
        out.append(
            {
                "topic": topic,
                "vote_count": votes,
                "distinct_voters": users,
                "discussion_count": dcount,
                "avg_trending_civic": round(civic, 3),
                "avg_trending_quality": round(quality, 3),
                "composite_score": round(composite, 2),
            }
        )

    seen = {r["topic"] for r in out}
    for topic, cnt in disc_counts.items():
        if topic not in seen:
            out.append(
                {
                    "topic": topic,
                    "vote_count": 0,
                    "distinct_voters": 0,
                    "discussion_count": int(cnt),
                    "avg_trending_civic": 0.0,
                    "avg_trending_quality": 0.0,
                    "composite_score": float(cnt),
                }
            )

    out.sort(key=lambda x: x["composite_score"], reverse=True)
    return out[:limit]
