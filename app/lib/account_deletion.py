"""Detach audit rows that must outlive an account before the user row is deleted."""


def release_user_event_references(user_id: int) -> None:
    """Keep analytics and email logs, but drop the link to the deleted account.

    Both foreign keys are NO ACTION, so deleting the user fails while any
    row still points at them. The events themselves stay for the audit trail.
    """
    from app.models import AnalyticsEvent, EmailEvent

    AnalyticsEvent.query.filter_by(user_id=user_id).update(
        {'user_id': None}, synchronize_session=False
    )
    EmailEvent.query.filter_by(user_id=user_id).update(
        {'user_id': None}, synchronize_session=False
    )
