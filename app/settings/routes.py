from flask import Blueprint, render_template, redirect, url_for, flash, request, current_app, session
from flask_login import login_required, current_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db
from app.models import User
from .forms import ChangePasswordForm, NotificationPreferencesForm, DeleteAccountForm
from app.billing.service import get_active_subscription
from app.lib.locale_utils import language_preference_cookie_params

settings_bp = Blueprint('settings', __name__)


def _pluck_ids(query, column):
    """Return scalar IDs from a SQLAlchemy query."""
    return [value for (value,) in query.with_entities(column).all()]


def _delete_briefing_data(owner_type, owner_id):
    """
    Delete all briefing/input-source records for an owner.

    Kept as a module-level helper to keep delete_account() focused and testable.
    """
    from app.models import (
        Briefing, BriefRun, BriefRunItem, BriefRecipient, BriefingSource,
        InputSource, IngestedItem,
    )

    briefing_ids = _pluck_ids(
        Briefing.query.filter_by(owner_type=owner_type, owner_id=owner_id),
        Briefing.id,
    )
    for briefing_id in briefing_ids:
        brief_run_ids = _pluck_ids(BriefRun.query.filter_by(briefing_id=briefing_id), BriefRun.id)
        if brief_run_ids:
            BriefRunItem.query.filter(BriefRunItem.brief_run_id.in_(brief_run_ids)).delete(
                synchronize_session=False
            )
        BriefRun.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
        BriefRecipient.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
        BriefingSource.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
    Briefing.query.filter_by(owner_type=owner_type, owner_id=owner_id).delete(synchronize_session=False)

    source_ids = _pluck_ids(
        InputSource.query.filter_by(owner_type=owner_type, owner_id=owner_id),
        InputSource.id,
    )
    if source_ids:
        ingested_ids = _pluck_ids(
            IngestedItem.query.filter(IngestedItem.source_id.in_(source_ids)),
            IngestedItem.id,
        )
        if ingested_ids:
            BriefRunItem.query.filter(BriefRunItem.ingested_item_id.in_(ingested_ids)).update(
                {'ingested_item_id': None}, synchronize_session=False
            )
        IngestedItem.query.filter(IngestedItem.source_id.in_(source_ids)).delete(synchronize_session=False)
        BriefingSource.query.filter(BriefingSource.source_id.in_(source_ids)).delete(synchronize_session=False)
    InputSource.query.filter_by(owner_type=owner_type, owner_id=owner_id).delete(synchronize_session=False)


@settings_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def view_settings():
    password_form = ChangePasswordForm(prefix='password')
    notif_form = NotificationPreferencesForm(prefix='notif')
    delete_form = DeleteAccountForm(prefix='delete')

    if request.method == 'POST' and 'update_notifications' in request.form:
        if notif_form.validate_on_submit():
            try:
                current_user.email_notifications = notif_form.email_notifications.data
                current_user.discussion_participant_notifications = notif_form.discussion_participant_notifications.data
                current_user.discussion_response_notifications = notif_form.discussion_response_notifications.data
                current_user.discussion_update_notifications = notif_form.discussion_update_notifications.data
                current_user.weekly_digest_enabled = notif_form.weekly_digest_enabled.data
                db.session.commit()
                flash('Notification preferences updated successfully.', 'success')
            except Exception:
                db.session.rollback()
                flash('Failed to update notification preferences. Please try again.', 'danger')
        else:
            flash('Failed to update notification preferences. Please try again.', 'danger')
        return redirect(url_for('settings.view_settings'))

    # Pre-populate notification form with current user values on GET
    if request.method == 'GET':
        notif_form.email_notifications.data = current_user.email_notifications
        notif_form.discussion_participant_notifications.data = current_user.discussion_participant_notifications
        notif_form.discussion_response_notifications.data = current_user.discussion_response_notifications
        notif_form.discussion_update_notifications.data = current_user.discussion_update_notifications
        notif_form.weekly_digest_enabled.data = current_user.weekly_digest_enabled

    active_subscription = get_active_subscription(current_user)

    return render_template('settings/settings.html',
                           form=password_form,
                           notif_form=notif_form,
                           delete_form=delete_form,
                           active_subscription=active_subscription)

@settings_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    form = ChangePasswordForm(request.form)

    if form.validate_on_submit():
        current_password = form.current_password.data
        new_password = form.new_password.data

        if not check_password_hash(current_user.password, current_password):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('settings.view_settings'))

        # Update user's password
        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Password updated successfully.', 'success')
        return redirect(url_for('settings.view_settings'))

    flash('Please correct the errors in the form.', 'danger')
    return redirect(url_for('settings.view_settings'))


@settings_bp.route('/settings/language', methods=['POST'])
@login_required
def update_language():
    """Save authenticated user's language preference to DB."""
    from app.lib.locale_utils import SUPPORTED_LANGUAGES
    lang = request.form.get('language', '').strip().lower()[:10]
    if lang not in SUPPORTED_LANGUAGES:
        flash('Invalid language selection.', 'danger')
        return redirect(url_for('settings.view_settings'))
    current_user.language = lang if lang != 'en' else None
    db.session.commit()
    flash('Language preference saved.', 'success')
    response = redirect(request.referrer or url_for('settings.view_settings'))
    response.set_cookie('ss_lang', lang, **language_preference_cookie_params())
    return response


@settings_bp.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    """Delete user account and all related data (handles foreign keys properly)"""
    from app.models import (
        IndividualProfile, CompanyProfile, Discussion, Notification,
        DiscussionParticipant, Statement, StatementVote, Response,
        StatementFlag, ApiKey, DailyQuestionSubscriber, DailyQuestionResponse,
        ProfileView, DiscussionView, StatementEvidence, ConsensusAnalysis,
        DiscussionSourceArticle, TrendingTopic, BriefItem, DailyQuestion,
        DailyQuestionSelection,
        SendingDomain
    )
    
    user = db.session.get(User, current_user.id)
    if not user:
        flash('Account deletion failed. Please try again.', 'error')
        return redirect(url_for('settings.view_settings'))

    user_id = user.id

    try:
        # 1. Clear nullable FK references (set to NULL instead of delete)
        # These reference the user but can exist without them
        DiscussionView.query.filter_by(viewer_id=user_id).update(
            {'viewer_id': None}, synchronize_session=False
        )
        ProfileView.query.filter_by(viewer_id=user_id).update(
            {'viewer_id': None}, synchronize_session=False
        )
        DiscussionParticipant.query.filter_by(user_id=user_id).update(
            {'user_id': None}, synchronize_session=False
        )
        Statement.query.filter_by(user_id=user_id).update(
            {'user_id': None}, synchronize_session=False
        )
        StatementVote.query.filter_by(user_id=user_id).update(
            {'user_id': None}, synchronize_session=False
        )
        StatementEvidence.query.filter_by(added_by_user_id=user_id).update(
            {'added_by_user_id': None}, synchronize_session=False
        )
        StatementFlag.query.filter_by(reviewed_by_user_id=user_id).update(
            {'reviewed_by_user_id': None}, synchronize_session=False
        )
        TrendingTopic.query.filter_by(reviewed_by_id=user_id).update(
            {'reviewed_by_id': None}, synchronize_session=False
        )
        DailyQuestion.query.filter_by(created_by_id=user_id).update(
            {'created_by_id': None}, synchronize_session=False
        )
        DailyQuestionResponse.query.filter_by(user_id=user_id).update(
            {'user_id': None}, synchronize_session=False
        )
        DailyQuestionSubscriber.query.filter_by(user_id=user_id).update(
            {'user_id': None}, synchronize_session=False
        )

        # 1b. Clean up Briefing system data owned by user
        _delete_briefing_data('user', user_id)

        # 2. Delete user's created content that can't exist without them
        # Delete responses (requires user_id)
        Response.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # Delete flags created by user
        StatementFlag.query.filter_by(flagger_user_id=user_id).delete(synchronize_session=False)
        
        # Delete notifications
        Notification.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # Delete API keys
        ApiKey.query.filter_by(user_id=user_id).delete(synchronize_session=False)
        
        # 3. Handle user's discussions (delete them completely)
        user_discussion_ids = [d.id for d in Discussion.query.filter_by(creator_id=user_id).all()]
        for disc_id in user_discussion_ids:
            # Clear references to this discussion
            TrendingTopic.query.filter_by(merged_into_discussion_id=disc_id).update(
                {'merged_into_discussion_id': None}, synchronize_session=False
            )
            TrendingTopic.query.filter_by(discussion_id=disc_id).update(
                {'discussion_id': None}, synchronize_session=False
            )
            BriefItem.query.filter_by(discussion_id=disc_id).update(
                {'discussion_id': None}, synchronize_session=False
            )
            DailyQuestion.query.filter_by(source_discussion_id=disc_id).update(
                {'source_discussion_id': None}, synchronize_session=False
            )
            DailyQuestionSelection.query.filter_by(source_discussion_id=disc_id).update(
                {'source_discussion_id': None}, synchronize_session=False
            )
            
            # Delete discussion's children
            stmt_ids = [s.id for s in Statement.query.filter_by(discussion_id=disc_id).all()]
            if stmt_ids:
                StatementFlag.query.filter(StatementFlag.statement_id.in_(stmt_ids)).delete(synchronize_session=False)
                StatementEvidence.query.filter(StatementEvidence.statement_id.in_(stmt_ids)).delete(synchronize_session=False)
                Response.query.filter(Response.statement_id.in_(stmt_ids)).delete(synchronize_session=False)
                StatementVote.query.filter(StatementVote.statement_id.in_(stmt_ids)).delete(synchronize_session=False)
            
            Statement.query.filter_by(discussion_id=disc_id).delete(synchronize_session=False)
            StatementVote.query.filter_by(discussion_id=disc_id).delete(synchronize_session=False)
            ConsensusAnalysis.query.filter_by(discussion_id=disc_id).delete(synchronize_session=False)
            DiscussionSourceArticle.query.filter_by(discussion_id=disc_id).delete(synchronize_session=False)
            DiscussionParticipant.query.filter_by(discussion_id=disc_id).delete(synchronize_session=False)
            DiscussionView.query.filter_by(discussion_id=disc_id).delete(synchronize_session=False)
            Notification.query.filter_by(discussion_id=disc_id).delete(synchronize_session=False)
        
        Discussion.query.filter_by(creator_id=user_id).delete(synchronize_session=False)
        
        # 4. Delete profiles
        if user.individual_profile:
            ProfileView.query.filter_by(individual_profile_id=user.individual_profile.id).delete(synchronize_session=False)
            db.session.delete(user.individual_profile)
        if user.company_profile:
            org_id = user.company_profile.id
            ProfileView.query.filter_by(company_profile_id=org_id).delete(synchronize_session=False)

            # Clean up org-owned briefing data before deleting company_profile
            _delete_briefing_data('org', org_id)

            # Delete SendingDomains (CASCADE will handle this, but explicit is safer)
            SendingDomain.query.filter_by(org_id=org_id).delete(synchronize_session=False)

            db.session.delete(user.company_profile)
        
        # 5. Finally delete the user
        db.session.delete(user)
        db.session.commit()
        
        current_app.logger.info(f"User deleted their account (ID: {user_id})")
        logout_user()
        session.clear()
        flash('Your account has been successfully deleted.', 'success')
        return redirect(url_for('main.index'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting user account {user_id}: {str(e)}")
        flash('Account deletion failed. Please try again.', 'error')
        return redirect(url_for('settings.view_settings'))