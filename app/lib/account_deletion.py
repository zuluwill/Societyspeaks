"""Detach rows that must outlive an account before the user row is deleted.

Production foreign keys on ``user.id`` are mostly NO ACTION. Cascade and
SET NULL constraints are left to the database. Everything else is cleared
here so admin delete and self-service delete hit the same rules.
"""


def release_user_event_references(user_id: int) -> None:
    """Drop NO ACTION links to this user without deleting the audit rows."""
    from app.models import (
        AdminSettings,
        AnalyticsEvent,
        BriefEdit,
        BriefRun,
        ConsensusJob,
        DailyBrief,
        DailyBriefSubscriber,
        DailyQuestionResponse,
        DailyQuestionResponseFlag,
        EmailEvent,
        Programme,
        ProgrammeAccessGrant,
        ProgrammeExportJob,
        ProgrammeSteward,
        UpcomingEvent,
    )

    AnalyticsEvent.query.filter_by(user_id=user_id).update(
        {'user_id': None}, synchronize_session=False
    )
    EmailEvent.query.filter_by(user_id=user_id).update(
        {'user_id': None}, synchronize_session=False
    )
    AdminSettings.query.filter_by(updated_by_id=user_id).update(
        {'updated_by_id': None}, synchronize_session=False
    )
    BriefRun.query.filter_by(approved_by_user_id=user_id).update(
        {'approved_by_user_id': None}, synchronize_session=False
    )
    ConsensusJob.query.filter_by(requested_by_user_id=user_id).update(
        {'requested_by_user_id': None}, synchronize_session=False
    )
    DailyBrief.query.filter_by(admin_edited_by=user_id).update(
        {'admin_edited_by': None}, synchronize_session=False
    )
    DailyBriefSubscriber.query.filter_by(user_id=user_id).update(
        {'user_id': None}, synchronize_session=False
    )
    DailyQuestionResponse.query.filter_by(reviewed_by_user_id=user_id).update(
        {'reviewed_by_user_id': None}, synchronize_session=False
    )
    DailyQuestionResponseFlag.query.filter_by(flagged_by_user_id=user_id).update(
        {'flagged_by_user_id': None}, synchronize_session=False
    )
    DailyQuestionResponseFlag.query.filter_by(reviewed_by_user_id=user_id).update(
        {'reviewed_by_user_id': None}, synchronize_session=False
    )
    Programme.query.filter_by(creator_id=user_id).update(
        {'creator_id': None}, synchronize_session=False
    )
    ProgrammeAccessGrant.query.filter_by(user_id=user_id).update(
        {'user_id': None}, synchronize_session=False
    )
    ProgrammeExportJob.query.filter_by(requested_by_user_id=user_id).update(
        {'requested_by_user_id': None}, synchronize_session=False
    )
    ProgrammeSteward.query.filter_by(user_id=user_id).update(
        {'user_id': None}, synchronize_session=False
    )
    UpcomingEvent.query.filter_by(created_by=user_id).update(
        {'created_by': None}, synchronize_session=False
    )
    # edited_by_user_id is NOT NULL, so the edit row cannot outlive the user.
    BriefEdit.query.filter_by(edited_by_user_id=user_id).delete(
        synchronize_session=False
    )
