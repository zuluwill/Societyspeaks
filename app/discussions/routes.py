from flask import abort, render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app
from flask_login import login_required, current_user
from app import db, limiter, talisman
from app.discussions.forms import CreateDiscussionForm, EditDiscussionForm
from app.models import Discussion, DiscussionParticipant, Programme, TrendingTopic, DiscussionSourceArticle, NewsArticle, NewsSource, Statement
from app.storage_utils import get_recent_activity
from app.middleware import track_discussion_view 
from app.email_utils import create_discussion_notification
from app.webhook_security import webhook_required, webhook_with_timestamp
from app.discussions.consensus import build_consensus_ui_state, PARTICIPATION_THRESHOLD
from app.api.utils import is_partner_origin_allowed, get_partner_allowed_origins, get_discussion_participant_count
from app.trending.conversion_tracking import track_social_click
from app.lib.time import utcnow_naive
from app.programmes.permissions import can_add_discussion_to_programme
from app.programmes.permissions import can_view_programme
from app.programmes.utils import render_safe_information_markdown, safe_information_links, validate_cohort_for_discussion
from app.discussions.sorting import apply_statement_sort
from app.discussions.thresholds import consensus_thresholds_dict
from app.lib.db_utils import retry_on_db_disconnect
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy import func
import json
import os
import re
try:
    import posthog
except ImportError:
    posthog = None


discussions_bp = Blueprint('discussions', __name__)


def _exclude_test_discussions(query):
    return query.filter(Discussion.partner_env != 'test')


def _statement_queries_for_discussion(discussion):
    """Build filtered statement queries used by HTML + API read paths."""
    from app.models import Response

    base_query = Statement.query.filter_by(
        discussion_id=discussion.id,
        is_deleted=False
    )
    query = Statement.query.options(
        joinedload(Statement.user),
        joinedload(Statement.responses).joinedload(Response.user)
    ).filter_by(
        discussion_id=discussion.id,
        is_deleted=False
    )

    if not (current_user.is_authenticated and (current_user.id == discussion.creator_id or current_user.is_admin)):
        query = query.filter(Statement.mod_status >= 0)
        base_query = base_query.filter(Statement.mod_status >= 0)

    return base_query, query


def _build_user_votes_map(statement_ids):
    """Return {statement_id: vote} for the current authenticated user."""
    if not current_user.is_authenticated or not statement_ids:
        return {}

    from app.models import StatementVote as SVModel
    rows = db.session.query(SVModel.statement_id, SVModel.vote).filter(
        SVModel.user_id == current_user.id,
        SVModel.statement_id.in_(statement_ids)
    ).all()
    return {row.statement_id: row.vote for row in rows}


@discussions_bp.route('/news')
def news_feed():
    """Display discussions generated from trending news topics."""
    from app.models import NewsSource
    from sqlalchemy import or_
    from sqlalchemy.orm import load_only
    from collections import defaultdict
    
    page = request.args.get('page', 1, type=int)
    topic_filter = request.args.get('topic', None)
    search_term = request.args.get('q', '').strip()
    view_mode = request.args.get('view', 'latest')  # 'latest' (default), 'topics', or filtered by topic
    
    news_discussion_ids = db.session.query(TrendingTopic.discussion_id).filter(
        TrendingTopic.discussion_id.isnot(None)
    ).subquery()
    
    # Get active news sources for transparency
    news_sources = NewsSource.query.filter_by(is_active=True).order_by(NewsSource.name).all()
    
    # If searching, always use flat view
    if search_term:
        view_mode = 'latest'
    
    if view_mode == 'topics' and not topic_filter:
        # Optimized: Fetch news discussions in a single query and group by topic in Python
        # This eliminates N+1 queries (one per topic)
        # Limit to 150 total to prevent unbounded loading (6 per topic * ~15 active topics = 90)
        all_news_discussions = _exclude_test_discussions(
            Discussion.query.options(
            load_only(
                Discussion.id, Discussion.title, Discussion.description,
                Discussion.topic, Discussion.slug, Discussion.created_at,
                Discussion.participant_count, Discussion.has_native_statements,
                Discussion.is_featured, Discussion.geographic_scope, Discussion.country,
                Discussion.city
            )
        )).filter(
            Discussion.id.in_(news_discussion_ids)
        ).order_by(Discussion.created_at.desc()).limit(150).all()
        
        # Group by topic and limit to 6 per topic
        topics_with_discussions = defaultdict(list)
        for discussion in all_news_discussions:
            if len(topics_with_discussions[discussion.topic]) < 6:
                topics_with_discussions[discussion.topic].append(discussion)
        
        # Convert to regular dict and filter empty topics
        topics_with_discussions = {k: v for k, v in topics_with_discussions.items() if v}
        
        return render_template(
            'discussions/news_feed.html',
            topics_with_discussions=topics_with_discussions,
            news_sources=news_sources,
            topics=Discussion.TOPICS,
            topic_filter=None,
            view_mode=view_mode,
            search_term='',
            discussions=None
        )
    else:
        # Flat paginated view for single topic or 'all' view
        # Use load_only to avoid loading unnecessary columns (only load what templates need)
        query = _exclude_test_discussions(
            Discussion.query.options(
            load_only(
                Discussion.id, Discussion.title, Discussion.description,
                Discussion.topic, Discussion.slug, Discussion.created_at,
                Discussion.participant_count, Discussion.has_native_statements,
                Discussion.is_featured, Discussion.geographic_scope, Discussion.country,
                Discussion.city
            )
        )).filter(
            Discussion.id.in_(news_discussion_ids)
        )
        
        if topic_filter:
            query = query.filter(Discussion.topic == topic_filter)
        
        # Apply search filter
        if search_term:
            query = query.filter(
                or_(
                    Discussion.title.ilike(f"%{search_term}%"),
                    Discussion.description.ilike(f"%{search_term}%")
                )
            )
        
        discussions = query.order_by(Discussion.created_at.desc()).paginate(
            page=page, per_page=12, error_out=False
        )
        
        return render_template(
            'discussions/news_feed.html',
            discussions=discussions,
            news_sources=news_sources,
            topics=Discussion.TOPICS,
            topic_filter=topic_filter,
            view_mode=view_mode,
            search_term=search_term,
            topics_with_discussions=None
        )

@discussions_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_discussion():
    from app.models import Statement

    if not current_user.profile_type:
        flash("Please complete your profile before creating a discussion.", "info")
        return redirect(url_for('profiles.select_profile_type'))

    form = CreateDiscussionForm()
    editable_programmes = []
    for programme in Programme.query.filter_by(status='active').order_by(Programme.name.asc()).all():
        if can_add_discussion_to_programme(programme, current_user):
            editable_programmes.append(programme)

    form.programme_id.choices = [(0, 'No programme')] + [
        (programme.id, programme.name) for programme in editable_programmes
    ]
    programme_meta = [
        {
            "id": programme.id,
            "themes": programme.themes or [],
            "phases": programme.phases or [],
        }
        for programme in editable_programmes
    ]

    selected_programme = None
    selected_programme_id = (
        form.programme_id.data
        or request.form.get('programme_id', type=int)
        or request.args.get('programme_id', type=int)
    )
    if selected_programme_id:
        selected_programme = next((p for p in editable_programmes if p.id == selected_programme_id), None)
        if selected_programme:
            if request.method == 'GET':
                form.programme_id.data = selected_programme.id
            form.programme_theme.choices = [('', 'No theme')] + [
                (theme, theme) for theme in (selected_programme.themes or [])
            ]
            form.programme_phase.choices = [('', 'No phase')] + [
                (phase, phase) for phase in (selected_programme.phases or [])
            ]
            if request.method == 'GET':
                preselected_theme = (request.args.get('programme_theme') or '').strip()
                preselected_phase = (request.args.get('programme_phase') or '').strip()
                if preselected_theme and preselected_theme in (selected_programme.themes or []):
                    form.programme_theme.data = preselected_theme
                if preselected_phase and preselected_phase in (selected_programme.phases or []):
                    form.programme_phase.data = preselected_phase
        else:
            form.programme_theme.choices = [('', 'No theme')]
            form.programme_phase.choices = [('', 'No phase')]

    if form.validate_on_submit():
        chosen_programme = None
        if form.programme_id.data:
            chosen_programme = next((p for p in editable_programmes if p.id == form.programme_id.data), None)
            if not chosen_programme:
                form.programme_id.errors.append('Selected programme is invalid or not editable.')
                return render_template('discussions/create_discussion.html', form=form, programme_meta=programme_meta)

            if form.programme_theme.data and form.programme_theme.data not in (chosen_programme.themes or []):
                form.programme_theme.errors.append('Selected theme is not valid for this programme.')
                return render_template('discussions/create_discussion.html', form=form, programme_meta=programme_meta)

            if form.programme_phase.data and form.programme_phase.data not in (chosen_programme.phases or []):
                form.programme_phase.errors.append('Selected phase is not valid for this programme.')
                return render_template('discussions/create_discussion.html', form=form, programme_meta=programme_meta)

        information_links = []
        raw_information_links = (form.information_links.data or '').strip()
        if raw_information_links:
            for line in raw_information_links.splitlines():
                cleaned = line.strip()
                if not cleaned or '|' not in cleaned:
                    continue
                label, url = cleaned.split('|', 1)
                information_links.append({"label": label.strip(), "url": url.strip()})
            information_links = safe_information_links(information_links)

        # Create a new discussion
        discussion = Discussion(
            # Phase 1: Support both native statements and pol.is embeds
            embed_code=form.embed_code.data if not form.use_native_statements.data else None,
            has_native_statements=form.use_native_statements.data,
            title=form.title.data,
            description=form.description.data,
            topic=form.topic.data,
            country=form.country.data,
            city=form.city.data,
            keywords=form.keywords.data,
            geographic_scope=form.geographic_scope.data,
            creator_id=current_user.id,
            individual_profile_id=current_user.individual_profile.id if (current_user.profile_type == 'individual' and current_user.individual_profile) else None,
            company_profile_id=current_user.company_profile.id if (current_user.profile_type == 'company' and current_user.company_profile) else None,
            programme_id=chosen_programme.id if chosen_programme else None,
            programme_theme=(form.programme_theme.data or None) if chosen_programme else None,
            programme_phase=(form.programme_phase.data or None) if chosen_programme else None,
            information_title=(form.information_title.data or '').strip() or None,
            information_body=(form.information_body.data or '').strip() or None,
            information_links=information_links
        )
        db.session.add(discussion)
        db.session.flush()  # Flush to get discussion.id before creating statements
        
        # Handle seed statements for native discussions
        statement_count = 0
        if form.use_native_statements.data:
            seed_statements_json = request.form.get('seed_statements')
            if seed_statements_json:
                try:
                    seed_statements = json.loads(seed_statements_json)
                    for stmt_text in seed_statements:
                        statement = Statement(
                            discussion_id=discussion.id,
                            user_id=current_user.id,
                            content=stmt_text.strip(),
                            statement_type='claim'  # Default type for seed statements
                        )
                        db.session.add(statement)
                    statement_count = len(seed_statements)
                except (json.JSONDecodeError, ValueError) as e:
                    current_app.logger.error(f"Error parsing seed statements: {e}")
        
        db.session.commit()
        if discussion.programme_id:
            from app.programmes.routes import invalidate_programme_summary_cache
            invalidate_programme_summary_cache(discussion.programme_id)
        
        # Track discussion creation with PostHog
        if posthog and getattr(posthog, 'project_api_key', None):
            try:
                posthog.capture(
                    distinct_id=str(current_user.id),
                    event='discussion_created',
                    properties={
                        'discussion_id': discussion.id,
                        'topic': discussion.topic,
                        'has_native_statements': discussion.has_native_statements,
                        'seed_statement_count': statement_count
                    }
                )
            except Exception as e:
                current_app.logger.warning(f"PostHog tracking error: {e}")
        
        flash(f"Discussion created successfully with {statement_count} seed statements!" if statement_count > 0 else "Discussion created successfully!", "success")

        # Redirect with both discussion_id and slug
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id, slug=discussion.slug))

    return render_template('discussions/create_discussion.html', form=form, programme_meta=programme_meta)


@discussions_bp.route('/<int:discussion_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_discussion(discussion_id):
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        abort(404)

    if discussion.creator_id != current_user.id and not current_user.is_admin:
        flash("You don't have permission to edit this discussion.", "error")
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id, slug=discussion.slug))

    # Build editable programmes list
    editable_programmes = []
    for programme in Programme.query.filter_by(status='active').order_by(Programme.name.asc()).all():
        if can_add_discussion_to_programme(programme, current_user):
            editable_programmes.append(programme)

    # If discussion has a programme not in editable list (e.g. user removed from org), include it
    current_programme = discussion.programme
    if current_programme and current_programme not in editable_programmes:
        editable_programmes_with_current = [current_programme] + editable_programmes
    else:
        editable_programmes_with_current = editable_programmes

    programme_choices = [(0, 'No programme')] + [
        (p.id, p.name) for p in editable_programmes_with_current
    ]
    programme_meta = [
        {"id": p.id, "themes": p.themes or [], "phases": p.phases or []}
        for p in editable_programmes_with_current
    ]

    if request.method == 'GET':
        form = EditDiscussionForm(obj=discussion)
        form.programme_id.choices = programme_choices
        form.programme_id.data = discussion.programme_id or 0

        # Set theme/phase choices based on current programme
        if current_programme:
            form.programme_theme.choices = [('', 'No theme')] + [
                (t, t) for t in (current_programme.themes or [])
            ]
            form.programme_phase.choices = [('', 'No phase')] + [
                (p, p) for p in (current_programme.phases or [])
            ]
        else:
            form.programme_theme.choices = [('', 'No theme')]
            form.programme_phase.choices = [('', 'No phase')]

        # Convert information_links JSON list → pipe-text for the textarea
        links = discussion.information_links or []
        if links:
            form.information_links.data = '\n'.join(
                f"{item.get('label', '')}|{item.get('url', '')}"
                for item in links
                if item.get('url')
            )
        else:
            form.information_links.data = ''

        return render_template(
            'discussions/edit_discussion.html',
            form=form,
            discussion=discussion,
            programme_meta=programme_meta,
        )

    # POST
    form = EditDiscussionForm()
    form.programme_id.choices = programme_choices
    selected_programme_id = request.form.get('programme_id', type=int) or 0
    selected_programme = next(
        (p for p in editable_programmes_with_current if p.id == selected_programme_id),
        None
    )
    if selected_programme:
        form.programme_theme.choices = [('', 'No theme')] + [
            (theme, theme) for theme in (selected_programme.themes or [])
        ]
        form.programme_phase.choices = [('', 'No phase')] + [
            (phase, phase) for phase in (selected_programme.phases or [])
        ]
    else:
        form.programme_theme.choices = [('', 'No theme')]
        form.programme_phase.choices = [('', 'No phase')]

    if not form.validate_on_submit():
        return render_template(
            'discussions/edit_discussion.html',
            form=form,
            discussion=discussion,
            programme_meta=programme_meta,
        )

    # Validate programme assignment
    chosen_programme_id = form.programme_id.data or 0
    chosen_programme = None
    if chosen_programme_id:
        chosen_programme = next(
            (p for p in editable_programmes_with_current if p.id == chosen_programme_id), None
        )
        if not chosen_programme:
            form.programme_id.errors.append('Selected programme is invalid or not editable.')
            return render_template(
                'discussions/edit_discussion.html',
                form=form,
                discussion=discussion,
                programme_meta=programme_meta,
            )

        if form.programme_theme.data and form.programme_theme.data not in (chosen_programme.themes or []):
            form.programme_theme.errors.append('Selected theme is not valid for this programme.')
            return render_template(
                'discussions/edit_discussion.html',
                form=form,
                discussion=discussion,
                programme_meta=programme_meta,
            )

        if form.programme_phase.data and form.programme_phase.data not in (chosen_programme.phases or []):
            form.programme_phase.errors.append('Selected phase is not valid for this programme.')
            return render_template(
                'discussions/edit_discussion.html',
                form=form,
                discussion=discussion,
                programme_meta=programme_meta,
            )

    # Parse information_links from pipe-text → safe JSON list
    raw_links = (form.information_links.data or '').strip()
    information_links = []
    if raw_links:
        for line in raw_links.splitlines():
            cleaned = line.strip()
            if not cleaned or '|' not in cleaned:
                continue
            label, url = cleaned.split('|', 1)
            information_links.append({"label": label.strip(), "url": url.strip()})
        information_links = safe_information_links(information_links)

    # Track old programme for cache invalidation
    old_programme_id = discussion.programme_id

    # Update fields in place
    discussion.title = form.title.data
    discussion.description = form.description.data
    discussion.topic = form.topic.data
    discussion.keywords = form.keywords.data or None
    discussion.geographic_scope = form.geographic_scope.data
    discussion.country = form.country.data or None
    discussion.city = form.city.data or None
    discussion.programme_id = chosen_programme.id if chosen_programme else None
    discussion.programme_theme = (form.programme_theme.data or None) if chosen_programme else None
    discussion.programme_phase = (form.programme_phase.data or None) if chosen_programme else None
    discussion.information_title = (form.information_title.data or '').strip() or None
    discussion.information_body = (form.information_body.data or '').strip() or None
    discussion.information_links = information_links

    # Update embed_code only for embed-mode discussions
    if not discussion.has_native_statements:
        discussion.embed_code = form.embed_code.data or discussion.embed_code

    # Regenerate slug from new title
    discussion.update_slug()

    db.session.commit()

    # Invalidate programme summary cache for old and new programmes
    from app.programmes.routes import invalidate_programme_summary_cache
    new_programme_id = discussion.programme_id
    if old_programme_id and old_programme_id != new_programme_id:
        invalidate_programme_summary_cache(old_programme_id)
    if new_programme_id:
        invalidate_programme_summary_cache(new_programme_id)

    # PostHog tracking
    if posthog and getattr(posthog, 'project_api_key', None):
        try:
            posthog.capture(
                distinct_id=str(current_user.id),
                event='discussion_edited',
                properties={
                    'discussion_id': discussion.id,
                    'topic': discussion.topic,
                    'programme_id': discussion.programme_id,
                }
            )
        except Exception as e:
            current_app.logger.warning(f"PostHog tracking error: {e}")

    flash("Discussion updated successfully.", "success")
    return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id, slug=discussion.slug))


@discussions_bp.route('/<int:discussion_id>', methods=['GET'])
def view_discussion_redirect(discussion_id):
    """Redirect discussion URLs without slug to the canonical URL with slug."""
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
        return render_template(
            'discussions/embed_unavailable.html',
            unavailable_reason='deleted',
            base_url=base_url
        ), 410
    if discussion.partner_env == 'test':
        abort(404)
    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(404)
    return redirect(url_for('discussions.view_discussion',
                          discussion_id=discussion.id,
                          slug=discussion.slug), code=301)


@discussions_bp.route('/<int:discussion_id>/embed', methods=['GET'])
@talisman(frame_options=None, content_security_policy=None)
def embed_discussion(discussion_id):
    """
    Partner embed view for voting on a discussion.

    This is a minimal, frameable page that shows:
    - Discussion title
    - Statement list with vote controls
    - Link to full consensus on Society Speaks

    Query Parameters:
        ref: Partner reference for analytics
        theme: Preset theme (default, dark, editorial, minimal, bold, muted)
        primary: Primary color hex (e.g., 1e40af)
        bg: Background color hex
        font: Font family from allowlist

    The route sets special CSP headers to allow framing from partner origins.
    """
    from flask import make_response
    # Check if embed feature is enabled
    if not current_app.config.get('EMBED_ENABLED', True):
        base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
        return render_template(
            'discussions/embed_unavailable.html',
            base_url=base_url
        ), 503

    # Get partner ref and check if this ref is disabled (kill switch)
    ref = request.args.get('ref', '')
    from app.api.utils import sanitize_partner_ref, append_ref_param, partner_ref_is_disabled
    ref_normalized = sanitize_partner_ref(ref)
    if ref_normalized and partner_ref_is_disabled(ref_normalized):
        base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
        return render_template(
            'discussions/embed_unavailable.html',
            unavailable_reason='disabled',
            base_url=base_url
        ), 403

    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        abort(404)

    # Enforce programme visibility — restricted programmes must not be embeddable
    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
        return render_template(
            'discussions/embed_unavailable.html',
            unavailable_reason='access_restricted',
            base_url=base_url
        ), 403

    # Restrict test embeds to verified test domains
    origin = request.headers.get('Origin')
    if origin and not is_partner_origin_allowed(origin, env=discussion.partner_env):
        base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
        return render_template(
            'discussions/embed_unavailable.html',
            unavailable_reason='domain_not_allowed',
            base_url=base_url
        ), 403

    # Get theme parameters
    theme = request.args.get('theme', 'default')
    primary_color = request.args.get('primary', '')
    bg_color = request.args.get('bg', '')
    font = request.args.get('font', '')

    # Validate font/theme against allowlists (single source: app.partner.constants)
    from app.partner.constants import EMBED_ALLOWED_FONTS, EMBED_THEMES
    if font and font not in EMBED_ALLOWED_FONTS:
        font = ''
    theme_map = {t['id']: t for t in EMBED_THEMES}
    if theme not in theme_map:
        theme = 'default'

    # Apply theme preset defaults — explicit URL params always override
    theme_preset = theme_map[theme]
    if not primary_color:
        primary_color = theme_preset.get('primary', '1e40af')
    if not bg_color:
        bg_color = theme_preset.get('bg', 'ffffff')
    if not font:
        font = theme_preset.get('font', '')

    # Validate hex colors to avoid CSS injection
    hex_pattern = re.compile(r'^[0-9a-fA-F]{3,6}$')
    if primary_color and not hex_pattern.match(primary_color):
        primary_color = '1e40af'
    if bg_color and not hex_pattern.match(bg_color):
        bg_color = 'ffffff'

    # Build consensus URL
    base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
    consensus_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}/consensus"
    if ref_normalized:
        consensus_url = append_ref_param(consensus_url, ref_normalized)

    # Get statements for voting (paginated for large discussions)
    statements = []
    statement_page = None
    page = max(1, request.args.get('page', 1, type=int))
    per_page = current_app.config.get('EMBED_STATEMENTS_PER_PAGE', 25)
    total_statement_count = 0
    if discussion.has_native_statements:
        statement_page = Statement.query.filter(
            Statement.discussion_id == discussion.id,
            Statement.is_deleted == False
        ).order_by(Statement.created_at.asc(), Statement.id.asc()).paginate(
            page=page,
            per_page=per_page,
            error_out=False
        )
        statements = statement_page.items
        total_statement_count = statement_page.total

    # Track embed load event
    try:
        from app.api.utils import track_partner_event
        track_partner_event('partner_embed_loaded', {
            'discussion_id': discussion.id,
            'discussion_title': discussion.title,
            'statement_count': total_statement_count or len(statements),
            'theme': theme,
            'has_custom_colors': bool(primary_color or bg_color),
            'has_custom_font': bool(font)
        })
    except Exception as e:
        current_app.logger.debug(f"Embed tracking error: {e}")

    # Render template (pass base_url for "Powered by" and content policy link)
    response = make_response(render_template(
        'discussions/embed_discussion.html',
        discussion=discussion,
        statements=statements,
        consensus_url=consensus_url,
        base_url=base_url,
        ref=ref_normalized or '',
        theme=theme,
        primary_color=primary_color,
        bg_color=bg_color,
        font=font,
        is_closed=discussion.is_closed,
        statement_page=statement_page,
        total_statement_count=total_statement_count
    ))

    # Set CSP frame-ancestors header for partner allowlist
    partner_origins = get_partner_allowed_origins(env=discussion.partner_env)
    if partner_origins:
        frame_ancestors = "'self' " + " ".join(partner_origins)
    else:
        frame_ancestors = "'self' *" if current_app.config.get('ENV') == 'development' else "'self'"

    # Build a complete CSP that includes frame-ancestors + essential XSS protections.
    # We must override Talisman's CSP (which blocks framing) but keep other protections.
    response.headers['Content-Security-Policy'] = (
        f"frame-ancestors {frame_ancestors}; "
        f"default-src 'self'; "
        f"script-src 'self' 'unsafe-inline'; "
        f"style-src 'self' 'unsafe-inline'; "
        f"img-src 'self' data: https:; "
        f"connect-src 'self'; "
        f"object-src 'none'; "
        f"base-uri 'self'"
    )

    # Remove X-Frame-Options to allow framing (CSP frame-ancestors takes precedence)
    response.headers.pop('X-Frame-Options', None)

    return response


@discussions_bp.route('/<int:discussion_id>/<slug>', methods=['GET'])
@track_discussion_view
@retry_on_db_disconnect()
def view_discussion(discussion_id, slug):
    # Track social media clicks (conversion tracking)
    user_id = str(current_user.id) if current_user.is_authenticated else None
    track_social_click(request, user_id)
    
    # Eager load creator and source_article_links with nested article.source to prevent N+1 queries
    # Using selectinload for nested relationships to ensure proper eager loading
    discussion = Discussion.query.options(
        joinedload(Discussion.creator),
        selectinload(Discussion.source_article_links)
        .joinedload(DiscussionSourceArticle.article)
        .joinedload(NewsArticle.source)
    ).filter_by(id=discussion_id).first_or_404()
    # Block test discussions from public access
    if discussion.partner_env == 'test':
        abort(404)
    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(404)
    # Redirect if the slug in the URL doesn't match the discussion's slug
    if discussion.slug != slug:
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # For native discussions, fetch statements
    statements = []
    sort = 'progressive'
    form = None
    statements_pagination = None
    statement_metrics = {
        'statement_count': 0,
        'agree_votes': 0,
        'disagree_votes': 0,
        'unsure_votes': 0,
        'total_votes': 0,
    }
    
    if discussion.has_native_statements:
        from app.discussions.statement_forms import StatementForm
        form = StatementForm()
        sort = request.args.get('sort', 'progressive')
        page = max(1, request.args.get('page', 1, type=int))
        per_page = current_app.config.get('DISCUSSION_STATEMENTS_PER_PAGE', 20)
        
        base_query, query = _statement_queries_for_discussion(discussion)

        aggregates = base_query.with_entities(
            func.count(Statement.id),
            func.coalesce(func.sum(Statement.vote_count_agree), 0),
            func.coalesce(func.sum(Statement.vote_count_disagree), 0),
            func.coalesce(func.sum(Statement.vote_count_unsure), 0),
        ).first()
        if aggregates:
            statement_metrics['statement_count'] = int(aggregates[0] or 0)
            statement_metrics['agree_votes'] = int(aggregates[1] or 0)
            statement_metrics['disagree_votes'] = int(aggregates[2] or 0)
            statement_metrics['unsure_votes'] = int(aggregates[3] or 0)
            statement_metrics['total_votes'] = (
                statement_metrics['agree_votes'] +
                statement_metrics['disagree_votes'] +
                statement_metrics['unsure_votes']
            )
        
        # Apply sorting — all sort modes including 'controversial' handled in SQL.
        query = apply_statement_sort(query, sort, discussion_id, db.session)
        statements_pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        statements = statements_pagination.items

        can_view_unapproved = current_user.is_authenticated and (
            current_user.id == discussion.creator_id or getattr(current_user, 'is_admin', False)
        )
        discussion_participant_count = get_discussion_participant_count(
            discussion,
            include_deleted_statement_votes=False,
            min_mod_status=None if can_view_unapproved else 0,
        )
        consensus_ui_state = build_consensus_ui_state(
            discussion,
            precomputed_metrics=statement_metrics,
            participant_count=discussion_participant_count,
        )
    else:
        _thresholds = consensus_thresholds_dict()
        consensus_ui_state = {
            'user_vote_count': 0,
            'participation_threshold': int(PARTICIPATION_THRESHOLD),
            'is_consensus_unlocked': False,
            'consensus_progress': {
                'participant_count': int(discussion.participant_count or 0),
                'min_participants': int(_thresholds.get('min_participants', 7)),
                'total_votes': 0,
                'min_total_votes': int(_thresholds.get('min_total_votes', 20)),
                'statement_count': 0,
                'recommended_statements': int(_thresholds.get('recommended_statements', 7)),
            },
        }
        discussion_participant_count = consensus_ui_state['consensus_progress']['participant_count']

    # Build per-statement vote map for optimistic UI seeding (authenticated only)
    user_votes_map = _build_user_votes_map([s.id for s in statements])
    cohort_slug = (request.args.get('cohort') or '').strip() or None
    if cohort_slug and not validate_cohort_for_discussion(discussion, cohort_slug):
        cohort_slug = None

    safe_information_html = None
    safe_info_links = []
    if discussion.information_title or discussion.information_body or discussion.information_links:
        safe_information_html = render_safe_information_markdown(discussion.information_body)
        safe_info_links = safe_information_links(discussion.information_links)
    
    # Render the page
    return render_template('discussions/view_discussion.html',
                         discussion=discussion,
                         statements=statements,
                         statements_pagination=statements_pagination,
                         statement_metrics=statement_metrics,
                         sort=sort,
                         form=form,
                         user_vote_count=consensus_ui_state['user_vote_count'],
                         user_votes_map=user_votes_map,
                         discussion_participant_count=discussion_participant_count,
                         participation_threshold=consensus_ui_state['participation_threshold'],
                         consensus_thresholds=consensus_thresholds_dict(),
                         safe_information_html=safe_information_html,
                         safe_information_links=safe_info_links,
                         cohort_slug=cohort_slug)


@discussions_bp.route('/api/discussions/<int:discussion_id>/statements', methods=['GET'])
@retry_on_db_disconnect()
def api_discussion_statements(discussion_id):
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion or discussion.partner_env == 'test':
        return jsonify({'success': False, 'error': 'not_found'}), 404
    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'success': False, 'error': 'forbidden'}), 403
    if not discussion.has_native_statements:
        return jsonify({'success': False, 'error': 'native_statements_disabled'}), 400

    page = max(1, request.args.get('page', 1, type=int))
    sort = request.args.get('sort', 'progressive')
    per_page = current_app.config.get('DISCUSSION_STATEMENTS_PER_PAGE', 20)

    cohort_slug = (request.args.get('cohort') or '').strip() or None
    if cohort_slug and not validate_cohort_for_discussion(discussion, cohort_slug):
        cohort_slug = None

    _, query = _statement_queries_for_discussion(discussion)
    query = apply_statement_sort(query, sort, discussion.id, db.session)
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    statement_user_votes_map = _build_user_votes_map([s.id for s in pagination.items])

    html = ''.join(
        render_template(
            'discussions/_statement_card.html',
            statement=statement,
            discussion=discussion,
            cohort_slug=cohort_slug,
            statement_user_votes_map=statement_user_votes_map,
        )
        for statement in pagination.items
    )

    return jsonify({
        'success': True,
        'html': html,
        'pagination': {
            'page': pagination.page,
            'pages': pagination.pages,
            'per_page': per_page,
            'total': pagination.total,
            'has_next': pagination.has_next,
            'next_page': pagination.next_num if pagination.has_next else None,
            'loaded_count': min(pagination.page * per_page, pagination.total),
        }
    })


@discussions_bp.route('/<int:discussion_id>/information-continue', methods=['POST'])
def mark_information_viewed(discussion_id):
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion:
        abort(404)
    if discussion.partner_env == 'test':
        abort(404)
    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(404)

    user_id = current_user.id if current_user.is_authenticated else None
    participant_identifier = None
    if not user_id:
        from app.discussions.statements import get_statement_vote_fingerprint
        participant_identifier = get_statement_vote_fingerprint()

    cohort_slug = (request.form.get('cohort') or request.args.get('cohort') or '').strip() or None
    if cohort_slug and not validate_cohort_for_discussion(discussion, cohort_slug):
        cohort_slug = None

    participant = DiscussionParticipant.track_participant(
        discussion_id=discussion.id,
        user_id=user_id,
        participant_identifier=participant_identifier,
        commit=False
    )
    participant.viewed_information_at = participant.viewed_information_at or utcnow_naive()
    if cohort_slug:
        participant.cohort_slug = cohort_slug
    db.session.commit()

    return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id, slug=discussion.slug, cohort=cohort_slug))



def fetch_discussions(search, country, city, topic, keywords, programme_id, page, per_page=9, sort='recent'):
    from sqlalchemy import and_, or_
    query = _exclude_test_discussions(Discussion.query).outerjoin(
        Programme, Discussion.programme_id == Programme.id
    ).filter(
        or_(
            Discussion.programme_id.is_(None),
            and_(Programme.status == 'active', Programme.visibility == 'public')
        )
    )

    # Apply filters if provided - search both title and description
    if search:
        query = query.filter(
            or_(
                Discussion.title.ilike(f"%{search}%"),
                Discussion.description.ilike(f"%{search}%")
            )
        )
    if country:
        query = query.filter_by(country=country)
    if city:
        query = query.filter_by(city=city)
    if topic:
        query = query.filter_by(topic=topic)
    if programme_id:
        query = query.filter(Discussion.programme_id == programme_id)

    # Apply sorting
    if sort == 'recent':
        query = query.order_by(Discussion.created_at.desc())
    elif sort == 'popular':
        query = query.order_by(Discussion.participant_count.desc())  # Example for popular sorting

    return query.paginate(page=page, per_page=per_page, error_out=False)




@discussions_bp.route('/search', methods=['GET'])
def search_discussions():
    # Use cached cities data from app config (loaded at startup)
    cities_by_country = current_app.config.get('CITIES_BY_COUNTRY', {})
    countries = list(cities_by_country.keys())

    # Get search parameters
    search_term = request.args.get('q', '')
    topic = request.args.get('topic')
    country = request.args.get('country')
    city = request.args.get('city')
    keywords = request.args.get('keywords', '')
    programme_id = request.args.get('programme_id', type=int)
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'popular')
    programmes = Programme.query.filter_by(status='active', visibility='public').order_by(Programme.name.asc()).all()

    # Use modified fetch_discussions to include sorting
    discussions = fetch_discussions(
        search=search_term,
        country=country,
        city=city,
        topic=topic,
        keywords=keywords,
        programme_id=programme_id,
        page=page,
        sort=sort
    )

    return render_template(
        'discussions/search_discussions.html',
        discussions=discussions,
        search_term=search_term,
        countries=countries,
        cities_by_country=cities_by_country,
        programmes=programmes
    )



@discussions_bp.route('/api/search', methods=['GET'])
def api_search_discussions():
    try:
        # Get search parameters with defaults
        search = request.args.get('search', '')
        country = request.args.get('country', '')
        city = request.args.get('city', '')
        topic = request.args.get('topic', '')
        keywords = request.args.get('keywords', '')
        programme_id = request.args.get('programme_id', type=int)
        programme_phase = request.args.get('programme_phase', '')
        programme_theme = request.args.get('programme_theme', '')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 12, type=int)  # Allow customizable page size

        # Validate page number
        if page < 1:
            return jsonify({
                'error': 'Invalid page number',
                'message': 'Page number must be greater than 0'
            }), 400

        # Get paginated discussions
        pagination = Discussion.search_discussions(
            search=search,
            country=country,
            city=city,
            topic=topic,
            keywords=keywords,
            programme_id=programme_id,
            programme_phase=programme_phase,
            programme_theme=programme_theme,
            page=page,
            per_page=per_page
        )

        # Prepare response
        response = {
            'status': 'success',
            'data': {
                'discussions': [d.to_dict() for d in pagination.items],
                'pagination': {
                    'total_items': pagination.total,
                    'total_pages': pagination.pages,
                    'current_page': pagination.page,
                    'per_page': per_page,
                    'has_next': pagination.has_next,
                    'has_prev': pagination.has_prev
                }
            },
            'meta': {
                'filters': {
                    'search': search,
                    'country': country,
                    'city': city,
                    'topic': topic,
                    'keywords': keywords,
                    'programme_id': programme_id,
                    'programme_phase': programme_phase,
                    'programme_theme': programme_theme
                }
            }
        }

        return jsonify(response), 200

    except ValueError as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'error': 'Invalid parameter'
        }), 400

    except Exception as e:
        # Log the error here
        current_app.logger.error(f"Error in API search: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'An internal server error occurred',
            'error': 'Internal server error'
        }), 500

country_mapping = {
    "UK": "United Kingdom",
    "US": "United States",
    "AF": "Afghanistan",
    "AL": "Albania",
    "DZ": "Algeria",
    "AD": "Andorra",
    "AO": "Angola",
    "AG": "Antigua and Barbuda",
    "AR": "Argentina",
    "AM": "Armenia",
    "AU": "Australia",
    "AT": "Austria",
    "AZ": "Azerbaijan",
    "BS": "Bahamas",
    "BH": "Bahrain",
    "BD": "Bangladesh",
    "BB": "Barbados",
    "BY": "Belarus",
    "BE": "Belgium",
    "BZ": "Belize",
    "BJ": "Benin",
    "BT": "Bhutan",
    "BO": "Bolivia",
    "BA": "Bosnia and Herzegovina",
    "BW": "Botswana",
    "BR": "Brazil",
    "BN": "Brunei",
    "BG": "Bulgaria",
    "BF": "Burkina Faso",
    "BI": "Burundi",
    "CV": "Cabo Verde",
    "KH": "Cambodia",
    "CM": "Cameroon",
    "CA": "Canada",
    "CF": "Central African Republic",
    "TD": "Chad",
    "CL": "Chile",
    "CN": "China",
    "CO": "Colombia",
    "KM": "Comoros",
    "CG": "Congo",
    "CD": "Congo (DRC)",
    "CR": "Costa Rica",
    "CI": "Côte d'Ivoire",
    "HR": "Croatia",
    "CU": "Cuba",
    "CY": "Cyprus",
    "CZ": "Czech Republic",
    "DK": "Denmark",
    "DJ": "Djibouti",
    "DM": "Dominica",
    "DO": "Dominican Republic",
    "EC": "Ecuador",
    "EG": "Egypt",
    "SV": "El Salvador",
    "GQ": "Equatorial Guinea",
    "ER": "Eritrea",
    "EE": "Estonia",
    "SZ": "Eswatini",
    "ET": "Ethiopia",
    "FJ": "Fiji",
    "FI": "Finland",
    "FR": "France",
    "GA": "Gabon",
    "GM": "Gambia",
    "GE": "Georgia",
    "DE": "Germany",
    "GH": "Ghana",
    "GR": "Greece",
    "GD": "Grenada",
    "GT": "Guatemala",
    "GN": "Guinea",
    "GW": "Guinea-Bissau",
    "GY": "Guyana",
    "HT": "Haiti",
    "HN": "Honduras",
    "HU": "Hungary",
    "IS": "Iceland",
    "IN": "India",
    "ID": "Indonesia",
    "IR": "Iran",
    "IQ": "Iraq",
    "IE": "Ireland",
    "IL": "Israel",
    "IT": "Italy",
    "JM": "Jamaica",
    "JP": "Japan",
    "JO": "Jordan",
    "KZ": "Kazakhstan",
    "KE": "Kenya",
    "KI": "Kiribati",
    "KW": "Kuwait",
    "KG": "Kyrgyzstan",
    "LA": "Laos",
    "LV": "Latvia",
    "LB": "Lebanon",
    "LS": "Lesotho",
    "LR": "Liberia",
    "LY": "Libya",
    "LI": "Liechtenstein",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "MG": "Madagascar",
    "MW": "Malawi",
    "MY": "Malaysia",
    "MV": "Maldives",
    "ML": "Mali",
    "MT": "Malta",
    "MH": "Marshall Islands",
    "MR": "Mauritania",
    "MU": "Mauritius",
    "MX": "Mexico",
    "FM": "Micronesia",
    "MD": "Moldova",
    "MC": "Monaco",
    "MN": "Mongolia",
    "ME": "Montenegro",
    "MA": "Morocco",
    "MZ": "Mozambique",
    "MM": "Myanmar",
    "NA": "Namibia",
    "NR": "Nauru",
    "NP": "Nepal",
    "NL": "Netherlands",
    "NZ": "New Zealand",
    "NI": "Nicaragua",
    "NE": "Niger",
    "NG": "Nigeria",
    "NO": "Norway",
    "OM": "Oman",
    "PK": "Pakistan",
    "PW": "Palau",
    "PA": "Panama",
    "PG": "Papua New Guinea",
    "PY": "Paraguay",
    "PE": "Peru",
    "PH": "Philippines",
    "PL": "Poland",
    "PT": "Portugal",
    "QA": "Qatar",
    "RO": "Romania",
    "RU": "Russia",
    "RW": "Rwanda",
    "KN": "Saint Kitts and Nevis",
    "LC": "Saint Lucia",
    "VC": "Saint Vincent and the Grenadines",
    "WS": "Samoa",
    "SM": "San Marino",
    "ST": "Sao Tome and Principe",
    "SA": "Saudi Arabia",
    "SN": "Senegal",
    "RS": "Serbia",
    "SC": "Seychelles",
    "SL": "Sierra Leone",
    "SG": "Singapore",
    "SK": "Slovakia",
    "SI": "Slovenia",
    "SB": "Solomon Islands",
    "SO": "Somalia",
    "ZA": "South Africa",
    "KR": "South Korea",
    "SS": "South Sudan",
    "ES": "Spain",
    "LK": "Sri Lanka",
    "SD": "Sudan",
    "SR": "Suriname",
    "SE": "Sweden",
    "CH": "Switzerland",
    "SY": "Syria",
    "TW": "Taiwan",
    "TJ": "Tajikistan",
    "TZ": "Tanzania",
    "TH": "Thailand",
    "TL": "Timor-Leste",
    "TG": "Togo",
    "TO": "Tonga",
    "TT": "Trinidad and Tobago",
    "TN": "Tunisia",
    "TR": "Turkey",
    "TM": "Turkmenistan",
    "TV": "Tuvalu",
    "UG": "Uganda",
    "UA": "Ukraine",
    "AE": "United Arab Emirates",
    "UY": "Uruguay",
    "UZ": "Uzbekistan",
    "VU": "Vanuatu",
    "VE": "Venezuela",
    "VN": "Vietnam",
    "YE": "Yemen",
    "ZM": "Zambia",
    "ZW": "Zimbabwe"
}


@discussions_bp.route('/api/cities/<country_code>')
def get_cities_by_country(country_code):
    try:
        country_name = country_mapping.get(country_code, country_code)
        cities_by_country = current_app.config.get('CITIES_BY_COUNTRY', {})
        cities = cities_by_country.get(country_name, [])
        return jsonify(cities)
    except Exception as e:
        current_app.logger.error(f"Error in get_cities_by_country: {str(e)}")
        return jsonify({"error": str(e)}), 500


# Notification and Activity Tracking Endpoints

@discussions_bp.route('/api/discussions/<int:discussion_id>/activity', methods=['POST'])
@limiter.limit("10 per minute")
@webhook_with_timestamp('X-Timestamp', 300)
def track_discussion_activity(discussion_id):
    """
    Webhook endpoint for Pol.is to report activity
    Can be called when there's new participant or response activity
    """
    try:
        discussion = db.get_or_404(Discussion, discussion_id)
        
        # Get activity data from request
        activity_data = request.get_json()
        activity_type = activity_data.get('type')  # 'new_participant' or 'new_response'
        participant_id = activity_data.get('participant_id')
        user_id = activity_data.get('user_id')  # If the participant is a registered user
        
        # Track the participant if it's a new participant
        if activity_type == 'new_participant':
            participant = DiscussionParticipant.track_participant(
                discussion_id=discussion_id,
                user_id=user_id,
                participant_identifier=participant_id
            )
            
            # Create notification for discussion creator
            if discussion.creator_id:
                create_discussion_notification(
                    user_id=discussion.creator_id,
                    discussion_id=discussion_id,
                    notification_type='new_participant',
                    additional_data={'participant_count': discussion.participant_count}
                )
        
        elif activity_type == 'new_response':
            # Update participant activity if we can identify them
            if participant_id:
                participant = DiscussionParticipant.query.filter_by(
                    discussion_id=discussion_id,
                    participant_identifier=participant_id
                ).first()

                if participant:
                    participant.increment_response_count(commit=True)
            
            # Create notification for discussion creator
            if discussion.creator_id:
                create_discussion_notification(
                    user_id=discussion.creator_id,
                    discussion_id=discussion_id,
                    notification_type='new_response',
                    additional_data={'response_count': activity_data.get('response_count', 0)}
                )
        
        return jsonify({
            'status': 'success',
            'message': 'Activity tracked successfully'
        }), 200
        
    except Exception as e:
        current_app.logger.error(f"Error tracking discussion activity: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to track activity'
        }), 500


@discussions_bp.route('/api/discussions/<int:discussion_id>/participants/track', methods=['POST'])
@limiter.limit("10 per minute")
@webhook_with_timestamp('X-Timestamp', 300)
def track_new_participant(discussion_id):
    """
    Manually track a new participant in a discussion
    Useful for integration testing or manual triggers
    """
    try:
        discussion = db.get_or_404(Discussion, discussion_id)
        
        # Get participant data
        participant_data = request.get_json()
        user_id = participant_data.get('user_id')
        participant_identifier = participant_data.get('participant_identifier')
        
        # Track the participant
        participant = DiscussionParticipant.track_participant(
            discussion_id=discussion_id,
            user_id=user_id,
            participant_identifier=participant_identifier
        )
        
        # Create notification for discussion creator
        if discussion.creator_id and discussion.creator_id != user_id:
            notification = create_discussion_notification(
                user_id=discussion.creator_id,
                discussion_id=discussion_id,
                notification_type='new_participant',
                additional_data={'participant_count': discussion.participant_count}
            )
            
            return jsonify({
                'status': 'success',
                'message': 'Participant tracked and notification sent',
                'participant_id': participant.id,
                'notification_id': notification.id if notification else None
            }), 200
        else:
            return jsonify({
                'status': 'success', 
                'message': 'Participant tracked',
                'participant_id': participant.id
            }), 200
            
    except Exception as e:
        current_app.logger.error(f"Error tracking participant: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to track participant'
        }), 500


