from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import distinct, func

from app import cache, db, limiter
from app.lib.auth_utils import normalize_email
from app.lib.time import utcnow_naive
from app.models import CompanyProfile, Discussion, OrganizationMember, Programme, ProgrammeSteward, StatementVote
from app.programmes.export import stream_programme_export
from app.programmes.forms import InviteStewardForm, ProgrammeForm
from app.programmes.permissions import can_edit_programme, can_steward_programme
from app.programmes.utils import (
    get_programme_cohort_slugs,
    parse_cohorts_csv,
    parse_csv_list,
    validate_cohort_for_discussion,
)


programmes_bp = Blueprint('programmes', __name__, template_folder='../templates/programmes')


def _programme_summary_cache_key(programme_id):
    return f"programme_summary_{programme_id}"


def invalidate_programme_summary_cache(programme_id):
    try:
        cache.delete(_programme_summary_cache_key(programme_id))
    except Exception:
        current_app.logger.warning("Failed to invalidate programme summary cache", exc_info=True)


def get_programme_summary(programme_id):
    cache_key = _programme_summary_cache_key(programme_id)

    try:
        cached_summary = cache.get(cache_key)
        if cached_summary is not None:
            return cached_summary
    except Exception:
        current_app.logger.warning("Failed to read programme summary cache", exc_info=True)

    discussion_ids_subquery = db.session.query(Discussion.id).filter(
        Discussion.programme_id == programme_id
    )

    discussion_count = db.session.query(func.count(Discussion.id)).filter(
        Discussion.programme_id == programme_id
    ).scalar() or 0

    authenticated_count = db.session.query(
        func.count(distinct(StatementVote.user_id))
    ).filter(
        StatementVote.discussion_id.in_(discussion_ids_subquery),
        StatementVote.user_id.isnot(None)
    ).scalar() or 0

    anonymous_count = db.session.query(
        func.count(distinct(StatementVote.session_fingerprint))
    ).filter(
        StatementVote.discussion_id.in_(discussion_ids_subquery),
        StatementVote.user_id.is_(None),
        StatementVote.session_fingerprint.isnot(None)
    ).scalar() or 0

    summary = {
        "discussion_count": int(discussion_count),
        "participant_count": int(authenticated_count + anonymous_count),
    }

    try:
        cache.set(cache_key, summary, timeout=300)
    except Exception:
        current_app.logger.warning("Failed to write programme summary cache", exc_info=True)

    return summary


def _editable_company_profiles(user):
    if not user.is_authenticated:
        return []

    editable_org_ids = {
        row.org_id
        for row in OrganizationMember.query.filter_by(user_id=user.id, status='active').all()
        if row.can_edit
    }
    if user.company_profile:
        editable_org_ids.add(user.company_profile.id)

    if not editable_org_ids:
        return []

    return CompanyProfile.query.filter(CompanyProfile.id.in_(list(editable_org_ids))).order_by(
        CompanyProfile.company_name.asc()
    ).all()


def _assign_programme_fields(programme, form):
    programme.name = (form.name.data or '').strip()
    programme.update_slug()
    programme.description = (form.description.data or '').strip() or None
    programme.geographic_scope = form.geographic_scope.data or 'global'
    programme.country = form.country.data if programme.geographic_scope == 'country' else None
    programme.logo_url = (form.logo_url.data or '').strip() or None
    programme.themes = parse_csv_list(form.themes_csv.data)
    programme.phases = parse_csv_list(form.phases_csv.data)
    programme.cohorts = parse_cohorts_csv(form.cohorts_text.data)


@programmes_bp.route('/')
def list_programmes():
    page = request.args.get('page', 1, type=int)
    programmes = Programme.query.filter_by(status='active').order_by(
        Programme.created_at.desc()
    ).paginate(page=page, per_page=12, error_out=False)
    return render_template('programmes/list.html', programmes=programmes)


@programmes_bp.route('/new', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per hour", methods=["POST"])
def create_programme():
    form = ProgrammeForm()
    orgs = _editable_company_profiles(current_user)
    form.company_profile_id.choices = [(0, 'Select organization')] + [
        (org.id, org.company_name) for org in orgs
    ]

    if form.validate_on_submit():
        programme = Programme()
        programme.status = 'active'
        _assign_programme_fields(programme, form)

        owner_type = form.owner_type.data
        selected_company_id = form.company_profile_id.data or 0

        if owner_type == 'company':
            if not selected_company_id:
                form.company_profile_id.errors.append('Please select an organization owner.')
                return render_template('programmes/create.html', form=form, orgs=orgs)
            company = db.session.get(CompanyProfile, selected_company_id)
            if not company or company.id not in {org.id for org in orgs}:
                form.company_profile_id.errors.append('You do not have permission to use that organization.')
                return render_template('programmes/create.html', form=form, orgs=orgs)
            programme.company_profile_id = company.id
            programme.creator_id = None
        else:
            programme.creator_id = current_user.id
            programme.company_profile_id = None

        db.session.add(programme)
        try:
            db.session.commit()
            invalidate_programme_summary_cache(programme.id)
            flash('Programme created successfully.', 'success')
            return redirect(url_for('programmes.view_programme', slug=programme.slug))
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to create programme')
            flash('Could not create programme. Please try again.', 'danger')

    return render_template('programmes/create.html', form=form, orgs=orgs)


@programmes_bp.route('/<slug>')
def view_programme(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    theme = request.args.get('theme', '').strip() or None
    phase = request.args.get('phase', '').strip() or None
    page = request.args.get('page', 1, type=int)

    query = Discussion.query.filter_by(programme_id=programme.id)
    if theme:
        query = query.filter_by(programme_theme=theme)
    if phase:
        query = query.filter_by(programme_phase=phase)

    discussions = query.order_by(Discussion.created_at.desc()).paginate(page=page, per_page=12, error_out=False)
    can_edit = can_edit_programme(programme, current_user)
    can_steward = can_steward_programme(programme, current_user)
    summary = get_programme_summary(programme.id)
    return render_template(
        'programmes/view.html',
        programme=programme,
        discussions=discussions,
        selected_theme=theme,
        selected_phase=phase,
        can_edit=can_edit,
        can_steward=can_steward,
        summary=summary
    )


@programmes_bp.route('/<slug>/edit', methods=['GET', 'POST'])
@login_required
def edit_programme(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to edit this programme.", "danger")
        return redirect(url_for('programmes.view_programme', slug=programme.slug))

    form = ProgrammeForm(obj=programme)
    orgs = _editable_company_profiles(current_user)
    form.company_profile_id.choices = [(0, 'Select organization')] + [
        (org.id, org.company_name) for org in orgs
    ]
    if request.method == 'GET':
        form.themes_csv.data = ", ".join(programme.themes or [])
        form.phases_csv.data = ", ".join(programme.phases or [])
        form.cohorts_text.data = "\n".join(
            f"{item.get('slug', '')}|{item.get('label', '')}"
            for item in (programme.cohorts or [])
            if isinstance(item, dict)
        )
        if programme.company_profile_id:
            form.owner_type.data = 'company'
            form.company_profile_id.data = programme.company_profile_id
        else:
            form.owner_type.data = 'user'
            form.company_profile_id.data = 0

    if form.validate_on_submit():
        _assign_programme_fields(programme, form)
        owner_type = form.owner_type.data
        selected_company_id = form.company_profile_id.data or 0
        if owner_type == 'company':
            company = db.session.get(CompanyProfile, selected_company_id) if selected_company_id else None
            if not company or company.id not in {org.id for org in orgs}:
                form.company_profile_id.errors.append('You do not have permission to use that organization.')
                return render_template('programmes/edit.html', form=form, programme=programme, orgs=orgs)
            programme.company_profile_id = company.id
            programme.creator_id = None
        else:
            programme.creator_id = current_user.id
            programme.company_profile_id = None

        try:
            db.session.commit()
            invalidate_programme_summary_cache(programme.id)
            flash('Programme updated successfully.', 'success')
            return redirect(url_for('programmes.view_programme', slug=programme.slug))
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to update programme')
            flash('Could not update programme. Please try again.', 'danger')

    return render_template('programmes/edit.html', form=form, programme=programme, orgs=orgs)


@programmes_bp.route('/<slug>/settings', methods=['GET'])
@login_required
def programme_settings(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to access settings.", "danger")
        return redirect(url_for('programmes.view_programme', slug=programme.slug))

    invite_form = InviteStewardForm()
    stewards = ProgrammeSteward.query.filter_by(programme_id=programme.id).order_by(
        ProgrammeSteward.created_at.desc()
    ).all()
    return render_template(
        'programmes/settings.html',
        programme=programme,
        stewards=stewards,
        invite_form=invite_form
    )


@programmes_bp.route('/<slug>/archive', methods=['POST'])
@login_required
def archive_programme(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to archive this programme.", "danger")
        return redirect(url_for('programmes.view_programme', slug=programme.slug))

    programme.status = 'archived'
    db.session.commit()
    invalidate_programme_summary_cache(programme.id)
    flash('Programme archived.', 'success')
    return redirect(url_for('programmes.programme_settings', slug=programme.slug))


@programmes_bp.route('/<slug>/unarchive', methods=['POST'])
@login_required
def unarchive_programme(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to unarchive this programme.", "danger")
        return redirect(url_for('programmes.view_programme', slug=programme.slug))

    programme.status = 'active'
    db.session.commit()
    invalidate_programme_summary_cache(programme.id)
    flash('Programme restored to active.', 'success')
    return redirect(url_for('programmes.programme_settings', slug=programme.slug))


def _send_steward_invite_email(programme, email, invite_url):
    from app.resend_client import get_resend_client

    client = get_resend_client()
    email_data = {
        'from': f"Society Speaks <noreply@{current_app.config.get('RESEND_DOMAIN', 'societyspeaks.io')}>",
        'to': [email],
        'subject': f"You're invited to steward programme: {programme.name}",
        'html': render_template(
            'emails/programme_steward_invite.html',
            programme=programme,
            invite_url=invite_url,
            inviter_name=current_user.username
        ),
    }
    return client._send_with_retry(email_data)


@programmes_bp.route('/<slug>/stewards/invite', methods=['POST'])
@login_required
@limiter.limit("10 per hour")
def invite_steward(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to invite stewards.", "danger")
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    form = InviteStewardForm()
    if not form.validate_on_submit():
        flash('Please provide a valid email.', 'danger')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    email = normalize_email(form.email.data)
    from app.models import User
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user:
        flash('No existing user found with that email. They must register first.', 'warning')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    active_steward = ProgrammeSteward.query.filter_by(
        programme_id=programme.id,
        user_id=user.id,
        status='active'
    ).first()
    if active_steward:
        flash('That user is already a steward.', 'info')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    steward = ProgrammeSteward.query.filter_by(programme_id=programme.id, user_id=user.id).first()
    token = ProgrammeSteward.generate_invite_token()
    if steward:
        steward.status = 'pending'
        steward.invited_by_id = current_user.id
        steward.invited_at = utcnow_naive()
        steward.invite_token = token
    else:
        steward = ProgrammeSteward(
            programme_id=programme.id,
            user_id=user.id,
            status='pending',
            invited_by_id=current_user.id,
            invited_at=utcnow_naive(),
            invite_token=token
        )
        db.session.add(steward)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to save steward invite')
        flash('Could not create steward invite.', 'danger')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    invite_url = url_for('programmes.accept_steward_invite', token=token, _external=True)
    try:
        _send_steward_invite_email(programme, email, invite_url)
    except Exception:
        current_app.logger.exception('Failed to send steward invite email')
        flash('Invite saved but email failed. Please retry.', 'warning')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    flash(f'Invite sent to {email}.', 'success')
    return redirect(url_for('programmes.programme_settings', slug=programme.slug))


@programmes_bp.route('/stewards/accept/<token>', methods=['GET'])
@login_required
def accept_steward_invite(token):
    steward = ProgrammeSteward.query.filter_by(invite_token=token, status='pending').first_or_404()
    if steward.user_id != current_user.id:
        flash('This invite is for another user account.', 'danger')
        return redirect(url_for('main.index'))

    steward.status = 'active'
    steward.accepted_at = utcnow_naive()
    steward.invite_token = None
    db.session.commit()
    flash('Steward access granted.', 'success')
    return redirect(url_for('programmes.view_programme', slug=steward.programme.slug))


@programmes_bp.route('/<slug>/export', methods=['GET'])
@login_required
def export_programme(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_steward_programme(programme, current_user):
        flash("You don't have permission to export this programme.", "danger")
        return redirect(url_for('programmes.view_programme', slug=programme.slug))

    cohort_slug = (request.args.get('cohort') or '').strip() or None
    if cohort_slug:
        if cohort_slug not in get_programme_cohort_slugs(programme):
            flash('Unknown cohort slug for this programme.', 'danger')
            return redirect(url_for('programmes.view_programme', slug=programme.slug))

    return stream_programme_export(programme, cohort_slug=cohort_slug)
