"""Notify users who follow (save) a discussion — single place for DRY follower loops."""
from datetime import timedelta

from app import db
from app.email_utils import create_discussion_notification
from app.lib.time import utcnow_naive
from app.models import DiscussionFollow, Notification


def notify_discussion_followers(
    discussion,
    notification_type,
    *,
    actor_user_id=None,
    skip_discussion_creator=False,
    cooldown_hours=None,
):
    """Notify each follower. Optionally skip the actor, skip the host, and throttle by cooldown.

    When ``cooldown_hours`` is set, users who already received the same
    ``notification_type`` for this discussion within that window are skipped.
    """
    if not discussion:
        return

    follow_rows = DiscussionFollow.query.filter_by(discussion_id=discussion.id).all()
    if not follow_rows:
        return

    recently_notified = set()
    if cooldown_hours is not None:
        cutoff = utcnow_naive() - timedelta(hours=cooldown_hours)
        follower_ids = [f.user_id for f in follow_rows]
        rows = (
            db.session.query(Notification.user_id)
            .filter(
                Notification.user_id.in_(follower_ids),
                Notification.discussion_id == discussion.id,
                Notification.type == notification_type,
                Notification.created_at >= cutoff,
            )
            .all()
        )
        recently_notified = {row.user_id for row in rows}

    for follow in follow_rows:
        uid = follow.user_id
        if actor_user_id is not None and uid == actor_user_id:
            continue
        if skip_discussion_creator and uid == discussion.creator_id:
            continue
        if uid in recently_notified:
            continue
        create_discussion_notification(
            user_id=uid,
            discussion_id=discussion.id,
            notification_type=notification_type,
        )
