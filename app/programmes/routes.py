from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for, jsonify, send_file
from flask_login import current_user, login_required
try:
    import posthog as _posthog
except ImportError:
    _posthog = None
from sqlalchemy import distinct, func
from sqlalchemy.orm import load_only, joinedload
from io import BytesIO

from app import cache, csrf, db, limiter
from app.lib.auth_utils import normalize_email
from app.lib.time import utcnow_naive
from app.models import (
    AnalyticsDailyAggregate,
    AnalyticsEvent,
    CompanyProfile,
    Discussion,
    JourneyReminderSubscription,
    Programme,
    ProgrammeAccessGrant,
    ProgrammeExportJob,
    ProgrammeSteward,
    StatementVote,
)
from app.programmes.access import editable_company_profiles, programme_access_labels, query_accessible_programmes
from app.programmes.export_jobs import (
    enqueue_programme_export_job,
    generate_export_download_token,
    verify_export_download_token,
    read_export_artifact_bytes,
)
from app.programmes.forms import InviteProgrammeAccessForm, InviteStewardForm, ProgrammeForm
from app.programmes.permissions import can_edit_programme, can_steward_programme, can_view_programme
from app.programmes.utils import (
    get_programme_cohort_slugs,
    parse_cohorts_csv,
    parse_csv_list,
    validate_cohort_for_discussion,
)
from app.programmes.journey import (
    build_journey_progress,
    build_programme_recap_payload,
    is_guided_journey_programme,
    ordered_journey_discussions,
    user_statement_votes_detail_batch,
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


def _programme_nsp_dashboard_payload(programme):
    tracked_events = ['discussion_viewed', 'statement_voted', 'response_created', 'analysis_generated']

    timeseries_rows = db.session.query(
        AnalyticsDailyAggregate.event_date,
        AnalyticsDailyAggregate.event_name,
        func.sum(AnalyticsDailyAggregate.event_count).label('event_count')
    ).filter(
        AnalyticsDailyAggregate.programme_id == programme.id,
        AnalyticsDailyAggregate.event_name.in_(tracked_events)
    ).group_by(
        AnalyticsDailyAggregate.event_date,
        AnalyticsDailyAggregate.event_name
    ).order_by(AnalyticsDailyAggregate.event_date.asc()).all()

    participation_by_time = {}
    for row in timeseries_rows:
        day = row.event_date.isoformat()
        if day not in participation_by_time:
            participation_by_time[day] = {'date': day}
        participation_by_time[day][row.event_name] = int(row.event_count or 0)

    geography_rows = db.session.query(
        AnalyticsDailyAggregate.country,
        func.sum(AnalyticsDailyAggregate.event_count)
    ).filter(
        AnalyticsDailyAggregate.programme_id == programme.id,
        AnalyticsDailyAggregate.event_name == 'statement_voted',
        AnalyticsDailyAggregate.country.isnot(None)
    ).group_by(AnalyticsDailyAggregate.country).all()

    cohort_rows = db.session.query(
        AnalyticsDailyAggregate.cohort_slug,
        func.sum(AnalyticsDailyAggregate.event_count)
    ).filter(
        AnalyticsDailyAggregate.programme_id == programme.id,
        AnalyticsDailyAggregate.event_name == 'statement_voted',
        AnalyticsDailyAggregate.cohort_slug.isnot(None)
    ).group_by(AnalyticsDailyAggregate.cohort_slug).all()

    vote_rows = db.session.query(
        func.date(func.coalesce(StatementVote.updated_at, StatementVote.created_at)).label('event_date'),
        StatementVote.vote,
        func.count(StatementVote.id).label('vote_count')
    ).join(
        Discussion, Discussion.id == StatementVote.discussion_id
    ).filter(
        Discussion.programme_id == programme.id
    ).group_by(
        func.date(func.coalesce(StatementVote.updated_at, StatementVote.created_at)),
        StatementVote.vote
    ).order_by(func.date(func.coalesce(StatementVote.updated_at, StatementVote.created_at)).asc()).all()

    trend_map = {}
    for row in vote_rows:
        day = row.event_date.isoformat()
        if day not in trend_map:
            trend_map[day] = {'agree': 0, 'disagree': 0, 'unsure': 0}
        if row.vote == 1:
            trend_map[day]['agree'] += int(row.vote_count or 0)
        elif row.vote == -1:
            trend_map[day]['disagree'] += int(row.vote_count or 0)
        else:
            trend_map[day]['unsure'] += int(row.vote_count or 0)

    consensus_vs_divisive_trends = []
    for day in sorted(trend_map.keys()):
        agree = trend_map[day]['agree']
        disagree = trend_map[day]['disagree']
        total_decisive = agree + disagree
        divisive_index = 0.0
        if total_decisive > 0:
            divisive_index = 1.0 - (abs(agree - disagree) / total_decisive)
        consensus_vs_divisive_trends.append({
            'date': day,
            'agree': agree,
            'disagree': disagree,
            'unsure': trend_map[day]['unsure'],
            'divisive_index': round(divisive_index, 4)
        })

    confidence_rows = db.session.query(
        StatementVote.confidence,
        func.count(StatementVote.id)
    ).join(
        Discussion, Discussion.id == StatementVote.discussion_id
    ).filter(
        Discussion.programme_id == programme.id,
        StatementVote.confidence.isnot(None)
    ).group_by(StatementVote.confidence).all()

    confidence_distribution = []
    for confidence, count in sorted(confidence_rows, key=lambda item: int(item[0] or 0)):
        confidence_distribution.append({
            'confidence': int(confidence or 0),
            'count': int(count or 0),
        })

    # Single query for all three funnel counts — avoids 3 separate table scans.
    funnel_events = ['discussion_viewed', 'statement_voted', 'response_created']
    funnel_rows = db.session.query(
        AnalyticsEvent.event_name,
        func.count(distinct(AnalyticsEvent.user_id)).label('unique_users'),
    ).filter(
        AnalyticsEvent.programme_id == programme.id,
        AnalyticsEvent.event_name.in_(funnel_events),
        AnalyticsEvent.user_id.isnot(None)
    ).group_by(AnalyticsEvent.event_name).all()

    funnel_counts = {row.event_name: int(row.unique_users or 0) for row in funnel_rows}
    viewer_count = funnel_counts.get('discussion_viewed', 0)
    voter_count = funnel_counts.get('statement_voted', 0)
    responder_count = funnel_counts.get('response_created', 0)

    return {
        'participation_by_time': [participation_by_time[day] for day in sorted(participation_by_time.keys())],
        'participation_by_geography': [
            {'country': row[0], 'vote_count': int(row[1] or 0)}
            for row in geography_rows
        ],
        'participation_by_cohort': [
            {'cohort_slug': row[0], 'vote_count': int(row[1] or 0)}
            for row in cohort_rows
        ],
        'consensus_vs_divisive_trends': consensus_vs_divisive_trends,
        'statement_confidence_distribution': confidence_distribution,
        'discussion_completion_funnel': {
            'viewers_authenticated': int(viewer_count),
            'voters_authenticated': int(voter_count),
            'responders_authenticated': int(responder_count),
        }
    }



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
    programme.visibility = form.visibility.data or 'public'


@programmes_bp.route('/')
def list_programmes():
    page = request.args.get('page', 1, type=int)
    programmes = Programme.query.options(
        joinedload(Programme.company_profile)
    ).filter(
        Programme.status == 'active',
        Programme.visibility == 'public',
    ).order_by(Programme.created_at.desc()).paginate(page=page, per_page=12, error_out=False)
    return render_template('programmes/list.html', programmes=programmes)


@programmes_bp.route('/workspace')
@login_required
def workspace_programmes():
    page = request.args.get('page', 1, type=int)
    workspace_pagination = query_accessible_programmes(current_user).options(
        load_only(
            Programme.id,
            Programme.slug,
            Programme.name,
            Programme.description,
            Programme.visibility,
            Programme.status,
            Programme.created_at,
            Programme.updated_at
        )
    ).order_by(
        func.coalesce(Programme.updated_at, Programme.created_at).desc()
    ).paginate(
        page=page,
        per_page=12,
        error_out=False
    )

    access_labels = programme_access_labels()
    programmes = []
    for programme, access_rank in workspace_pagination.items:
        rank = int(access_rank or 1)
        programmes.append(
            {
                "programme": programme,
                "access_label": access_labels.get(rank, "Invited participant"),
                "access_rank": rank,
                "can_manage_settings": rank >= 3,
            }
        )
    return render_template(
        'programmes/workspace.html',
        programmes=programmes,
        programmes_pagination=workspace_pagination
    )


@programmes_bp.route('/new', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per hour", methods=["POST"])
def create_programme():
    form = ProgrammeForm()
    orgs = editable_company_profiles(current_user)
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
    if not can_view_programme(programme, current_user):
        visibility = getattr(programme, 'visibility', 'public')
        if visibility == 'invite_only' and not current_user.is_authenticated:
            flash('Please log in to access this programme.', 'info')
            return redirect(url_for('auth.login'))
        abort(404)

    jrt = request.args.get('jrt', '').strip() or None
    if jrt:
        sub = JourneyReminderSubscription.verify_resume_token(jrt)
        if sub and sub.programme_id == programme.id:
            session['journey_resume_sub_id'] = sub.id
            flash('Welcome back! Pick up where you left off.', 'success')
        return redirect(url_for('programmes.view_programme', slug=slug))

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
    journey_mode = is_guided_journey_programme(programme)
    journey_progress = None
    journey_reminder_subscription = None
    if journey_mode:
        uid = current_user.id if current_user.is_authenticated else None
        ordered = ordered_journey_discussions(programme)
        journey_progress = build_journey_progress(programme, uid, discussions=ordered)
        if uid:
            journey_reminder_subscription = JourneyReminderSubscription.query.filter_by(
                programme_id=programme.id, user_id=uid
            ).first()
        elif 'journey_resume_sub_id' in session:
            # Anonymous user arrived via magic link — show their subscription status
            sub_id = session.get('journey_resume_sub_id')
            candidate = db.session.get(JourneyReminderSubscription, sub_id)
            if candidate and candidate.programme_id == programme.id:
                journey_reminder_subscription = candidate

        # PostHog: fire journey_started once per session per journey
        if _posthog and getattr(_posthog, 'project_api_key', None):
            _start_key = f'ph_journey_started_{programme.id}'
            if not session.get(_start_key):
                try:
                    import uuid as _uuid
                    if current_user.is_authenticated:
                        _ph_id = str(current_user.id)
                    else:
                        _ph_id = (
                            session.get('statement_vote_fingerprint')
                            or session.get('journey_anon_id')
                        )
                        if not _ph_id:
                            _ph_id = str(_uuid.uuid4())
                            session['journey_anon_id'] = _ph_id
                    _journey_type = 'global' if getattr(programme, 'geographic_scope', 'global') == 'global' else 'country'
                    _posthog.capture(
                        distinct_id=_ph_id,
                        event='journey_started',
                        properties={
                            'journey_id': programme.id,
                            'journey_type': _journey_type,
                            'journey_slug': programme.slug,
                            'journey_name': programme.name,
                            'total_steps': len(ordered),
                            'is_authenticated': current_user.is_authenticated,
                        },
                    )
                    _posthog.flush()
                    session[_start_key] = True
                    session.modified = True
                except Exception as _e:
                    current_app.logger.warning(f"PostHog journey_started error: {_e}")

    return render_template(
        'programmes/view.html',
        programme=programme,
        discussions=discussions,
        selected_theme=theme,
        selected_phase=phase,
        can_edit=can_edit,
        can_steward=can_steward,
        summary=summary,
        journey_mode=journey_mode,
        journey_progress=journey_progress,
        journey_reminder_subscription=journey_reminder_subscription,
    )


@programmes_bp.route('/<slug>/recap')
def programme_journey_recap(slug):
    """
    Programme-level recap for guided flagship journeys: per-theme participation,
    aggregate vote mix, and optional signed-in vote detail (not a single cross-topic PCA).
    """
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_view_programme(programme, current_user):
        visibility = getattr(programme, 'visibility', 'public')
        if visibility == 'invite_only' and not current_user.is_authenticated:
            flash('Please log in to access this programme.', 'info')
            return redirect(url_for('auth.login'))
        abort(404)
    if not is_guided_journey_programme(programme):
        flash('This recap view is only available for guided flagship programmes.', 'info')
        return redirect(url_for('programmes.view_programme', slug=programme.slug))

    uid = current_user.id if current_user.is_authenticated else None
    ordered_discussions = ordered_journey_discussions(programme)
    recap = build_programme_recap_payload(programme, uid, discussions=ordered_discussions)
    personal_by_discussion = {}
    if uid:
        disc_ids = [d.id for d in ordered_discussions]
        personal_by_discussion = user_statement_votes_detail_batch(uid, disc_ids)
    recap_share_url = url_for(
        'programmes.programme_journey_recap',
        slug=programme.slug,
        _external=True,
    )

    # PostHog: fire journey_completed once per session when user reaches the recap page
    if _posthog and getattr(_posthog, 'project_api_key', None):
        _complete_key = f'ph_journey_completed_{programme.id}'
        if not session.get(_complete_key):
            try:
                import uuid as _uuid
                if current_user.is_authenticated:
                    _ph_id = str(current_user.id)
                else:
                    _ph_id = (
                        session.get('statement_vote_fingerprint')
                        or session.get('journey_anon_id')
                    )
                    if not _ph_id:
                        _ph_id = str(_uuid.uuid4())
                        session['journey_anon_id'] = _ph_id
                _ordered = ordered_discussions
                _journey_type = 'global' if getattr(programme, 'geographic_scope', 'global') == 'global' else 'country'
                _posthog.capture(
                    distinct_id=_ph_id,
                    event='journey_completed',
                    properties={
                        'journey_id': programme.id,
                        'journey_type': _journey_type,
                        'journey_slug': programme.slug,
                        'journey_name': programme.name,
                        'total_steps': len(_ordered),
                        'is_authenticated': current_user.is_authenticated,
                    },
                )
                _posthog.flush()
                session[_complete_key] = True
                session.modified = True
            except Exception as _e:
                current_app.logger.warning(f"PostHog journey_completed error: {_e}")

    return render_template(
        'programmes/journey_recap.html',
        programme=programme,
        recap=recap,
        personal_by_discussion=personal_by_discussion,
        recap_share_url=recap_share_url,
    )


@programmes_bp.route('/<slug>/journey-reminder', methods=['POST'])
@limiter.limit("10 per hour")
def journey_reminder_subscribe(slug):
    """
    Save a journey reminder cadence preference for authenticated or anonymous users.
    Accepts JSON: {cadence: 'weekly'|'weekend'|'twice_weekly', timezone: '...', preferred_hour: 0-23, preferred_minute: 0-59, email: '...' (anon only)}
    Returns JSON: {success: true} or {success: false, error: '...'}
    """
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_view_programme(programme, current_user):
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    from app.lib.auth_utils import normalize_email as _normalize
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    data = request.get_json(silent=True) or {}
    cadence = (data.get('cadence') or '').strip()
    if cadence not in JourneyReminderSubscription.VALID_CADENCES:
        return jsonify({'success': False, 'error': 'invalid_cadence'}), 400

    # Validate timezone — must be a real IANA zone; fall back to UTC silently
    raw_tz = (data.get('timezone') or 'UTC').strip()[:50]
    try:
        ZoneInfo(raw_tz)
        tz_value = raw_tz
    except (ZoneInfoNotFoundError, KeyError):
        tz_value = 'UTC'

    # preferred_hour: 0–23, preferred_minute: 0–59 — user's exact local time
    try:
        preferred_hour = int(data.get('preferred_hour', 8))
        if not 0 <= preferred_hour <= 23:
            preferred_hour = 8
    except (TypeError, ValueError):
        preferred_hour = 8

    try:
        preferred_minute = int(data.get('preferred_minute', 0))
        if not 0 <= preferred_minute <= 59:
            preferred_minute = 0
    except (TypeError, ValueError):
        preferred_minute = 0

    if current_user.is_authenticated:
        email = current_user.email
        user_id = current_user.id
    else:
        raw_email = (data.get('email') or '').strip()
        email = _normalize(raw_email) if raw_email else None
        if not email:
            return jsonify({'success': False, 'error': 'email_required'}), 400
        user_id = None

    try:
        existing = None
        if user_id:
            existing = JourneyReminderSubscription.query.filter_by(
                programme_id=programme.id, user_id=user_id
            ).first()
        else:
            existing = JourneyReminderSubscription.query.filter_by(
                programme_id=programme.id, email=email, user_id=None
            ).first()

        if existing:
            existing.cadence = cadence
            existing.timezone = tz_value
            existing.preferred_hour = preferred_hour
            existing.preferred_minute = preferred_minute
            existing.unsubscribed_at = None
            existing.set_next_send_at()
            sub = existing
        else:
            sub = JourneyReminderSubscription(
                programme_id=programme.id,
                user_id=user_id,
                email=email,
                cadence=cadence,
                timezone=tz_value,
                preferred_hour=preferred_hour,
                preferred_minute=preferred_minute,
            )
            sub.set_next_send_at()
            db.session.add(sub)

        db.session.flush()

        # Human-readable cadence labels for emails
        _cadence_labels = {
            'weekly': 'once a week',
            'weekend': 'on Saturday mornings',
            'twice_weekly': 'twice a week (Tue & Thu)',
            'commute': 'twice a week (Tue & Thu)',
        }
        h12 = preferred_hour % 12 or 12
        ampm = 'am' if preferred_hour < 12 else 'pm'
        m_str = f'{preferred_minute:02d}'
        time_label = f'at {h12}:{m_str}{ampm}'
        cadence_label = f"{_cadence_labels.get(cadence, cadence)}, {time_label}"

        if not user_id:
            token = sub.generate_resume_token(expires_hours=72)
            db.session.commit()
            from app.resend_client import get_resend_client
            from flask import render_template as _rt
            client = get_resend_client()
            base_url = client.base_url
            confirm_url = f"{base_url}/programmes/{programme.slug}?jrt={token}"
            html = _rt(
                'emails/journey_reminder_confirm.html',
                programme_name=programme.name,
                confirm_url=confirm_url,
                cadence_label=cadence_label,
                base_url=base_url,
            )
            email_data = {
                'from': client.from_email,
                'to': [email],
                'subject': f"Your journey reminders are set — Society Speaks",
                'html': html,
            }
            client._send_with_retry(email_data, use_rate_limit=False)
        else:
            db.session.commit()

        return jsonify({'success': True, 'cadence': cadence, 'preferred_hour': preferred_hour, 'preferred_minute': preferred_minute})

    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to save journey reminder subscription')
        return jsonify({'success': False, 'error': 'server_error'}), 500


@programmes_bp.route('/<slug>/journey-reminder/unsubscribe', methods=['GET'])
def journey_reminder_unsubscribe(slug):
    """One-click unsubscribe from journey reminders via token or login."""
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    token = request.args.get('token', '').strip() or None

    sub = None
    if token:
        # Use the no-expiry lookup — unsubscribe links must work indefinitely
        # regardless of the 72-hour magic-link window (CAN-SPAM / GDPR compliance).
        sub = JourneyReminderSubscription.find_by_unsubscribe_token(token)
    elif current_user.is_authenticated:
        sub = JourneyReminderSubscription.query.filter_by(
            programme_id=programme.id, user_id=current_user.id
        ).first()

    if sub and sub.programme_id == programme.id:
        sub.unsubscribed_at = utcnow_naive()
        db.session.commit()
        # Clear the session reference so anonymous users stop seeing the "set" pill
        session.pop('journey_resume_sub_id', None)
        flash('You\'ve been unsubscribed from journey reminders.', 'success')
    else:
        flash('Could not find that subscription — it may have already been removed.', 'info')

    return redirect(url_for('programmes.view_programme', slug=slug))


@programmes_bp.route('/<slug>/edit', methods=['GET', 'POST'])
@login_required
def edit_programme(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to edit this programme.", "danger")
        return redirect(url_for('programmes.view_programme', slug=programme.slug))

    form = ProgrammeForm(obj=programme)
    orgs = editable_company_profiles(current_user)
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

    access_page = request.args.get('access_page', 1, type=int)
    invite_form = InviteStewardForm()
    invite_access_form = InviteProgrammeAccessForm()
    stewards = ProgrammeSteward.query.filter_by(programme_id=programme.id).order_by(
        ProgrammeSteward.created_at.desc()
    ).all()
    access_grants_pagination = ProgrammeAccessGrant.query.filter_by(
        programme_id=programme.id,
        status='active'
    ).order_by(ProgrammeAccessGrant.created_at.desc()).paginate(
        page=access_page,
        per_page=50,
        error_out=False
    )
    return render_template(
        'programmes/settings.html',
        programme=programme,
        stewards=stewards,
        invite_form=invite_form,
        invite_access_form=invite_access_form,
        access_grants=access_grants_pagination.items,
        access_grants_pagination=access_grants_pagination
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


def _send_pending_steward_invite_email(programme, email, invite_url, inviter_name):
    from app.resend_client import get_resend_client

    client = get_resend_client()
    email_data = {
        'from': f"Society Speaks <noreply@{current_app.config.get('RESEND_DOMAIN', 'societyspeaks.io')}>",
        'to': [email],
        'subject': f"You're invited to steward programme: {programme.name}",
        'html': render_template(
            'emails/programme_steward_invite_pending.html',
            programme=programme,
            invite_url=invite_url,
            inviter_name=inviter_name,
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
        # User not registered yet — create a pending steward record
        existing_pending = ProgrammeSteward.query.filter_by(
            programme_id=programme.id,
            pending_email=email,
        ).first()
        token = ProgrammeSteward.generate_invite_token()
        if existing_pending:
            existing_pending.invite_token = token
            existing_pending.invited_by_id = current_user.id
            existing_pending.invited_at = utcnow_naive()
            existing_pending.status = 'pending'
        else:
            pending_steward = ProgrammeSteward(
                programme_id=programme.id,
                user_id=None,
                pending_email=email,
                status='pending',
                invited_by_id=current_user.id,
                invited_at=utcnow_naive(),
                invite_token=token,
            )
            db.session.add(pending_steward)
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()
            current_app.logger.exception('Failed to save pending steward invite')
            flash('Could not create steward invite.', 'danger')
            return redirect(url_for('programmes.programme_settings', slug=programme.slug))
        invite_url = url_for('programmes.accept_steward_invite', token=token, _external=True)
        try:
            _send_pending_steward_invite_email(programme, email, invite_url, current_user.username)
        except Exception:
            current_app.logger.exception('Failed to send pending steward invite email')
            flash('Invite saved but email failed. Please retry.', 'warning')
            return redirect(url_for('programmes.programme_settings', slug=programme.slug))
        flash(f'Invite sent to {email}. They will need to register an account first.', 'success')
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


def _send_access_grant_email(programme, email, programme_url):
    from app.resend_client import get_resend_client

    client = get_resend_client()
    email_data = {
        'from': f"Society Speaks <noreply@{current_app.config.get('RESEND_DOMAIN', 'societyspeaks.io')}>",
        'to': [email],
        'subject': f"You've been invited to join: {programme.name}",
        'html': render_template(
            'emails/programme_access_invite.html',
            programme=programme,
            programme_url=programme_url,
            inviter_name=current_user.username,
        ),
    }
    return client._send_with_retry(email_data)


@programmes_bp.route('/<slug>/access/invite', methods=['POST'])
@login_required
@limiter.limit("20 per hour")
def invite_programme_access(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to invite participants.", "danger")
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))
    if programme.visibility == 'private':
        flash(
            "Private programmes only allow owner/steward access. Invite as steward or switch visibility to invite-only.",
            "warning"
        )
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    form = InviteProgrammeAccessForm()
    if not form.validate_on_submit():
        flash('Please provide a valid participant email.', 'danger')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    email = normalize_email(form.email.data)
    from app.models import User
    user = User.query.filter(db.func.lower(User.email) == email).first()
    if not user:
        flash('No existing user found with that email. They must register first.', 'warning')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    if can_steward_programme(programme, user):
        flash('That user already has steward or owner access.', 'info')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    grant = ProgrammeAccessGrant.query.filter_by(programme_id=programme.id, user_id=user.id).first()
    if grant and grant.status == 'active':
        flash('That user already has participant access.', 'info')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    if grant:
        grant.status = 'active'
        grant.invited_by_id = current_user.id
    else:
        grant = ProgrammeAccessGrant(
            programme_id=programme.id,
            user_id=user.id,
            invited_by_id=current_user.id,
            status='active'
        )
        db.session.add(grant)

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to save programme access grant')
        flash('Could not grant participant access.', 'danger')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    programme_url = url_for('programmes.view_programme', slug=programme.slug, _external=True)
    email_delivery_failed = False
    try:
        _send_access_grant_email(programme, email, programme_url)
    except Exception:
        current_app.logger.exception('Failed to send programme access invite email')
        email_delivery_failed = True

    flash(f'Participant access granted to {email}.', 'success')
    if email_delivery_failed:
        flash("Invite email could not be delivered. Access is active, but you may need to share the programme link manually.", 'warning')
    return redirect(url_for('programmes.programme_settings', slug=programme.slug))


@programmes_bp.route('/<slug>/access/<int:grant_id>/revoke', methods=['POST'])
@login_required
def revoke_programme_access(slug, grant_id):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to revoke participant access.", "danger")
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    grant = ProgrammeAccessGrant.query.filter_by(id=grant_id, programme_id=programme.id).first_or_404()
    grant.status = 'revoked'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to revoke programme access grant')
        flash('Could not revoke participant access. Please try again.', 'danger')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))
    flash('Participant access revoked.', 'success')
    return redirect(url_for('programmes.programme_settings', slug=programme.slug))


@programmes_bp.route('/<slug>/stewards/<int:steward_id>/remove', methods=['POST'])
@login_required
def remove_steward(slug, steward_id):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_edit_programme(programme, current_user):
        flash("You don't have permission to remove stewards.", "danger")
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))

    steward = ProgrammeSteward.query.filter_by(id=steward_id, programme_id=programme.id).first_or_404()
    db.session.delete(steward)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Failed to remove steward')
        flash('Could not remove steward. Please try again.', 'danger')
        return redirect(url_for('programmes.programme_settings', slug=programme.slug))
    flash('Steward removed.', 'success')
    return redirect(url_for('programmes.programme_settings', slug=programme.slug))


@programmes_bp.route('/stewards/accept/<token>', methods=['GET'])
def accept_steward_invite(token):
    steward = ProgrammeSteward.query.filter_by(invite_token=token, status='pending').first_or_404()

    if not current_user.is_authenticated:
        session['pending_steward_invite_token'] = token
        flash('Please log in or register to accept the steward invitation.', 'info')
        return redirect(url_for('auth.login'))

    if steward.user_id is not None:
        if steward.user_id != current_user.id:
            flash('This invite is for another user account.', 'danger')
            return redirect(url_for('main.index'))
    else:
        # Pending invite for an unregistered email
        if not steward.pending_email or current_user.email.lower() != steward.pending_email.lower():
            flash('This invite is for a different email address.', 'danger')
            return redirect(url_for('main.index'))
        steward.user_id = current_user.id
        steward.pending_email = None

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

    export_format = (request.args.get('format') or 'csv').strip().lower()
    if export_format not in ('csv', 'json'):
        export_format = 'csv'

    job, created, message = enqueue_programme_export_job(
        programme_id=programme.id,
        requested_by_user_id=current_user.id,
        export_format=export_format,
        cohort_slug=cohort_slug
    )

    if request.args.get('json') == '1':
        return jsonify({
            'success': True,
            'queued': bool(created),
            'message': message,
            'job_id': job.id,
            'status_url': url_for('programmes.export_job_status', slug=programme.slug, job_id=job.id, _external=True)
        }), 202

    flash(message or "Export queued.", "success" if created else "info")
    return redirect(url_for('programmes.view_programme', slug=programme.slug))


@programmes_bp.route('/<slug>/export/jobs/<int:job_id>', methods=['GET'])
@login_required
def export_job_status(slug, job_id):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_steward_programme(programme, current_user):
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    job = ProgrammeExportJob.query.filter_by(id=job_id, programme_id=programme.id).first()
    if not job:
        return jsonify({'success': False, 'error': 'not_found'}), 404

    download_url = None
    if job.status == ProgrammeExportJob.STATUS_COMPLETED and job.storage_key:
        ttl = int(current_app.config.get('EXPORT_DOWNLOAD_TOKEN_MAX_AGE_SECONDS', 3600))
        token = generate_export_download_token(current_app.config['SECRET_KEY'], job.id, current_user.id)
        download_url = url_for('programmes.download_export_artifact', token=token, _external=True)

    return jsonify({
        'success': True,
        'job': {
            'id': job.id,
            'status': job.status,
            'export_format': job.export_format,
            'cohort_slug': job.cohort_slug,
            'attempts': job.attempts,
            'max_attempts': job.max_attempts,
            'error_message': job.error_message,
            'artifact_filename': job.artifact_filename,
            'artifact_size_bytes': job.artifact_size_bytes,
            'queued_at': job.queued_at.isoformat() if job.queued_at else None,
            'started_at': job.started_at.isoformat() if job.started_at else None,
            'completed_at': job.completed_at.isoformat() if job.completed_at else None,
            'download_url': download_url,
            'download_expires_in_seconds': ttl if download_url else None,
        }
    })


@programmes_bp.route('/export/download/<token>', methods=['GET'])
@login_required
def download_export_artifact(token):
    max_age = int(current_app.config.get('EXPORT_DOWNLOAD_TOKEN_MAX_AGE_SECONDS', 3600))
    payload, error = verify_export_download_token(
        current_app.config['SECRET_KEY'],
        token,
        max_age_seconds=max_age
    )
    if error:
        abort(403)

    job_id = int(payload.get('job_id', 0))
    user_id = int(payload.get('user_id', 0))
    if not job_id or not user_id or current_user.id != user_id:
        abort(403)

    job = ProgrammeExportJob.query.filter_by(id=job_id, requested_by_user_id=current_user.id).first()
    if not job or job.status != ProgrammeExportJob.STATUS_COMPLETED:
        abort(404)

    programme = db.session.get(Programme, job.programme_id)
    if not programme or not can_steward_programme(programme, current_user):
        abort(403)

    data = read_export_artifact_bytes(job)
    if not data:
        abort(404)

    return send_file(
        BytesIO(data),
        mimetype=job.content_type or 'application/octet-stream',
        as_attachment=True,
        download_name=job.artifact_filename or f"programme-export-{job.id}.{job.export_format}"
    )


@programmes_bp.route('/journey/step-timing', methods=['POST'])
@csrf.exempt
@limiter.limit('120 per hour')
def journey_step_timing():
    """Receive client-side step timing data and fire a PostHog journey_step_timed event."""
    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return jsonify({'ok': True})
    try:
        data = request.get_json(silent=True, force=True) or {}
        programme_id = data.get('programme_id')
        discussion_id = data.get('discussion_id')
        time_on_step_ms = data.get('time_on_step_ms')
        if not (programme_id and discussion_id and isinstance(time_on_step_ms, (int, float)) and time_on_step_ms > 0):
            return jsonify({'ok': False}), 400
        programme = db.session.get(Programme, programme_id)
        discussion = db.session.get(Discussion, discussion_id)
        if not programme or not discussion:
            return jsonify({'ok': False}), 404
        from app.programmes.journey import is_guided_journey_programme, ordered_journey_discussions
        if not is_guided_journey_programme(programme):
            return jsonify({'ok': False}), 400
        ordered = ordered_journey_discussions(programme)
        step_num = next((i + 1 for i, d in enumerate(ordered) if d.id == discussion_id), None)
        if step_num is None:
            return jsonify({'ok': False}), 404
        if current_user.is_authenticated:
            ph_id = str(current_user.id)
        else:
            from app.discussions.statements import get_statement_vote_fingerprint
            ph_id = get_statement_vote_fingerprint()
        jtype = 'global' if getattr(programme, 'geographic_scope', 'global') == 'global' else 'country'
        _posthog.capture(
            distinct_id=ph_id,
            event='journey_step_timed',
            properties={
                'journey_id': programme.id,
                'journey_type': jtype,
                'journey_slug': programme.slug,
                'journey_name': programme.name,
                'step_number': step_num,
                'step_name': discussion.programme_theme or discussion.slug,
                'total_steps': len(ordered),
                'time_on_step_seconds': round(time_on_step_ms / 1000),
                'is_authenticated': current_user.is_authenticated,
            },
        )
        return jsonify({'ok': True})
    except Exception as e:
        current_app.logger.warning(f'PostHog journey_step_timed error: {e}')
        return jsonify({'ok': False}), 500


@programmes_bp.route('/journey/abandon', methods=['POST'])
@csrf.exempt
@limiter.limit('120 per hour')
def journey_abandon():
    """Receive client-side abandon signal and fire a PostHog journey_abandoned event."""
    if not _posthog or not getattr(_posthog, 'project_api_key', None):
        return jsonify({'ok': True})
    try:
        data = request.get_json(silent=True, force=True) or {}
        programme_id = data.get('programme_id')
        discussion_id = data.get('discussion_id')
        if not (programme_id and discussion_id):
            return jsonify({'ok': False}), 400
        programme = db.session.get(Programme, programme_id)
        if not programme:
            return jsonify({'ok': False}), 404
        from app.programmes.journey import is_guided_journey_programme, ordered_journey_discussions
        if not is_guided_journey_programme(programme):
            return jsonify({'ok': False}), 400
        if current_user.is_authenticated:
            ph_id = str(current_user.id)
        else:
            from app.discussions.statements import get_statement_vote_fingerprint
            ph_id = get_statement_vote_fingerprint()
        ordered = ordered_journey_discussions(programme)
        jtype = 'global' if getattr(programme, 'geographic_scope', 'global') == 'global' else 'country'
        props = {
            'journey_id': programme.id,
            'journey_type': jtype,
            'journey_slug': programme.slug,
            'journey_name': programme.name,
            'step_number': data.get('step_number'),
            'step_name': data.get('step_name', ''),
            'total_steps': len(ordered),
            'votes_cast': int(data.get('votes_cast', 0)),
            'total_statements': int(data.get('total_statements', 0)),
            'is_authenticated': current_user.is_authenticated,
        }
        time_on_step_ms = data.get('time_on_step_ms')
        if isinstance(time_on_step_ms, (int, float)) and time_on_step_ms > 0:
            props['time_on_step_seconds'] = round(time_on_step_ms / 1000)
        _posthog.capture(distinct_id=ph_id, event='journey_abandoned', properties=props)
        return jsonify({'ok': True})
    except Exception as e:
        current_app.logger.warning(f'PostHog journey_abandoned error: {e}')
        return jsonify({'ok': False}), 500


@programmes_bp.route('/<slug>/nsp-dashboard', methods=['GET'])
@login_required
def programme_nsp_dashboard(slug):
    programme = Programme.query.filter_by(slug=slug).first_or_404()
    if not can_steward_programme(programme, current_user):
        return jsonify({'success': False, 'error': 'forbidden'}), 403

    payload = _programme_nsp_dashboard_payload(programme)
    return jsonify({
        'success': True,
        'schema_version': '1.0.0',
        'programme': {'id': programme.id, 'slug': programme.slug, 'name': programme.name},
        'generated_at': utcnow_naive().isoformat(),
        'dashboard': payload,
    })
