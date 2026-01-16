from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db
from app.models import User
from .forms import ChangePasswordForm  # Import the form

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def view_settings():
    form = ChangePasswordForm()  # Initialize the form
    
    # Handle notification settings update
    if request.method == 'POST' and 'update_notifications' in request.form:
        try:
            current_user.email_notifications = 'email_notifications' in request.form
            current_user.discussion_participant_notifications = 'discussion_participant_notifications' in request.form
            current_user.discussion_response_notifications = 'discussion_response_notifications' in request.form
            current_user.weekly_digest_enabled = 'weekly_digest_enabled' in request.form
            
            db.session.commit()
            flash('Notification preferences updated successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Failed to update notification preferences. Please try again.', 'danger')
        
        return redirect(url_for('settings.view_settings'))

    return render_template('settings/settings.html', form=form)

@settings_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    form = ChangePasswordForm(request.form)

    if form.validate_on_submit():
        current_password = form.current_password.data
        new_password = form.new_password.data
        confirm_password = form.confirm_password.data

        if not check_password_hash(current_user.password, current_password):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('settings.view_settings'))

        if new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('settings.view_settings'))

        # Update user's password
        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Password updated successfully.', 'success')
        return redirect(url_for('settings.view_settings'))

    flash('Please correct the errors in the form.', 'danger')
    return redirect(url_for('settings.view_settings'))


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
        # Briefing system models
        Briefing, BriefRun, BriefRunItem, BriefRecipient, BriefingSource,
        InputSource, IngestedItem, SendingDomain
    )
    
    user = User.query.get(current_user.id)
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
        # Delete briefings owned by user (cascades to BriefRun, BriefRunItem, BriefRecipient, BriefingSource)
        user_briefing_ids = [b.id for b in Briefing.query.filter_by(owner_type='user', owner_id=user_id).all()]
        for briefing_id in user_briefing_ids:
            # Delete BriefRunItems first (child of BriefRun)
            brief_run_ids = [r.id for r in BriefRun.query.filter_by(briefing_id=briefing_id).all()]
            if brief_run_ids:
                BriefRunItem.query.filter(BriefRunItem.brief_run_id.in_(brief_run_ids)).delete(synchronize_session=False)
            # Delete BriefRuns
            BriefRun.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
            # Delete BriefRecipients
            BriefRecipient.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
            # Delete BriefingSources
            BriefingSource.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
        # Delete the briefings themselves
        Briefing.query.filter_by(owner_type='user', owner_id=user_id).delete(synchronize_session=False)

        # Delete InputSources owned by user (cascades to IngestedItem)
        user_source_ids = [s.id for s in InputSource.query.filter_by(owner_type='user', owner_id=user_id).all()]
        if user_source_ids:
            # Clear references from BriefRunItem to IngestedItem before deleting
            ingested_ids = [i.id for i in IngestedItem.query.filter(IngestedItem.source_id.in_(user_source_ids)).all()]
            if ingested_ids:
                BriefRunItem.query.filter(BriefRunItem.ingested_item_id.in_(ingested_ids)).update(
                    {'ingested_item_id': None}, synchronize_session=False
                )
            # Delete IngestedItems
            IngestedItem.query.filter(IngestedItem.source_id.in_(user_source_ids)).delete(synchronize_session=False)
            # Clear BriefingSource references before deleting InputSources
            BriefingSource.query.filter(BriefingSource.source_id.in_(user_source_ids)).delete(synchronize_session=False)
        # Delete the InputSources
        InputSource.query.filter_by(owner_type='user', owner_id=user_id).delete(synchronize_session=False)

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
            # Delete briefings owned by org (cascades to BriefRun, BriefRunItem, BriefRecipient, BriefingSource)
            org_briefing_ids = [b.id for b in Briefing.query.filter_by(owner_type='org', owner_id=org_id).all()]
            for briefing_id in org_briefing_ids:
                brief_run_ids = [r.id for r in BriefRun.query.filter_by(briefing_id=briefing_id).all()]
                if brief_run_ids:
                    BriefRunItem.query.filter(BriefRunItem.brief_run_id.in_(brief_run_ids)).delete(synchronize_session=False)
                BriefRun.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
                BriefRecipient.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
                BriefingSource.query.filter_by(briefing_id=briefing_id).delete(synchronize_session=False)
            Briefing.query.filter_by(owner_type='org', owner_id=org_id).delete(synchronize_session=False)

            # Delete org-owned InputSources
            org_source_ids = [s.id for s in InputSource.query.filter_by(owner_type='org', owner_id=org_id).all()]
            if org_source_ids:
                ingested_ids = [i.id for i in IngestedItem.query.filter(IngestedItem.source_id.in_(org_source_ids)).all()]
                if ingested_ids:
                    BriefRunItem.query.filter(BriefRunItem.ingested_item_id.in_(ingested_ids)).update(
                        {'ingested_item_id': None}, synchronize_session=False
                    )
                IngestedItem.query.filter(IngestedItem.source_id.in_(org_source_ids)).delete(synchronize_session=False)
                BriefingSource.query.filter(BriefingSource.source_id.in_(org_source_ids)).delete(synchronize_session=False)
            InputSource.query.filter_by(owner_type='org', owner_id=org_id).delete(synchronize_session=False)

            # Delete SendingDomains (CASCADE will handle this, but explicit is safer)
            SendingDomain.query.filter_by(org_id=org_id).delete(synchronize_session=False)

            db.session.delete(user.company_profile)
        
        # 5. Finally delete the user
        db.session.delete(user)
        db.session.commit()
        
        current_app.logger.info(f"User deleted their account (ID: {user_id})")
        flash('Your account has been deleted successfully.', 'success')
        return redirect(url_for('auth.logout'))
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting user account {user_id}: {str(e)}")
        flash('Account deletion failed. Please try again.', 'error')
        return redirect(url_for('settings.view_settings'))