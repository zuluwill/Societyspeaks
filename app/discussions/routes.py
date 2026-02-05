from flask import render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app
from flask_login import login_required, current_user
from app import db, limiter
from app.discussions.forms import CreateDiscussionForm
from app.models import Discussion, DiscussionParticipant, TrendingTopic, DiscussionSourceArticle, NewsArticle, NewsSource
from app.storage_utils import get_recent_activity
from app.middleware import track_discussion_view 
from app.email_utils import create_discussion_notification
from app.webhook_security import webhook_required, webhook_with_timestamp
from app.discussions.consensus import get_user_vote_count, PARTICIPATION_THRESHOLD
from app.trending.conversion_tracking import track_social_click
from sqlalchemy.orm import joinedload, selectinload
import json
import os
try:
    import posthog
except ImportError:
    posthog = None


discussions_bp = Blueprint('discussions', __name__)


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
        all_news_discussions = Discussion.query.options(
            load_only(
                Discussion.id, Discussion.title, Discussion.description,
                Discussion.topic, Discussion.slug, Discussion.created_at,
                Discussion.participant_count, Discussion.has_native_statements,
                Discussion.is_featured, Discussion.geographic_scope, Discussion.country
            )
        ).filter(
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
        query = Discussion.query.options(
            load_only(
                Discussion.id, Discussion.title, Discussion.description,
                Discussion.topic, Discussion.slug, Discussion.created_at,
                Discussion.participant_count, Discussion.has_native_statements,
                Discussion.is_featured, Discussion.geographic_scope, Discussion.country
            )
        ).filter(
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
    
    form = CreateDiscussionForm()
    if form.validate_on_submit():
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
            individual_profile_id=current_user.individual_profile.id if current_user.profile_type == 'individual' else None,
            company_profile_id=current_user.company_profile.id if current_user.profile_type == 'company' else None
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

    return render_template('discussions/create_discussion.html', form=form)


@discussions_bp.route('/<int:discussion_id>', methods=['GET'])
def view_discussion_redirect(discussion_id):
    """Redirect discussion URLs without slug to the canonical URL with slug."""
    discussion = Discussion.query.get_or_404(discussion_id)
    return redirect(url_for('discussions.view_discussion',
                          discussion_id=discussion.id,
                          slug=discussion.slug), code=301)


@discussions_bp.route('/<int:discussion_id>/embed', methods=['GET'])
def embed_discussion(discussion_id):
    """
    Partner embed view for voting on a discussion.

    This is a minimal, frameable page that shows:
    - Discussion title
    - Statement list with vote controls
    - Link to full consensus on Society Speaks

    Query Parameters:
        ref: Partner reference for analytics
        theme: Preset theme (observer, time, ted, or default)
        primary: Primary color hex (e.g., 1e40af)
        bg: Background color hex
        font: Font family from allowlist

    The route sets special CSP headers to allow framing from partner origins.
    """
    from flask import make_response
    from app.models import Statement

    # Check if embed feature is enabled
    if not current_app.config.get('EMBED_ENABLED', True):
        return render_template('discussions/embed_unavailable.html'), 503

    discussion = Discussion.query.get_or_404(discussion_id)

    # Get partner ref for analytics
    ref = request.args.get('ref', '')

    # Get theme parameters
    theme = request.args.get('theme', 'default')
    primary_color = request.args.get('primary', '')
    bg_color = request.args.get('bg', '')
    font = request.args.get('font', '')

    # Validate font against allowlist (single source: app.partner.constants)
    from app.partner.constants import EMBED_ALLOWED_FONTS
    if font and font not in EMBED_ALLOWED_FONTS:
        font = ''

    # Build consensus URL
    base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
    consensus_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}/consensus"
    if ref:
        consensus_url = f"{consensus_url}?ref={ref}"

    # Get statements for voting
    statements = []
    if discussion.has_native_statements:
        statements = Statement.query.filter(
            Statement.discussion_id == discussion.id,
            Statement.is_deleted == False
        ).order_by(Statement.created_at.asc()).all()

    # Track embed load event
    try:
        from app.api.utils import track_partner_event
        track_partner_event('partner_embed_loaded', {
            'discussion_id': discussion.id,
            'discussion_title': discussion.title,
            'statement_count': len(statements),
            'theme': theme,
            'has_custom_colors': bool(primary_color or bg_color),
            'has_custom_font': bool(font)
        })
    except Exception as e:
        current_app.logger.debug(f"Embed tracking error: {e}")

    # Render template
    response = make_response(render_template(
        'discussions/embed_discussion.html',
        discussion=discussion,
        statements=statements,
        consensus_url=consensus_url,
        ref=ref,
        theme=theme,
        primary_color=primary_color,
        bg_color=bg_color,
        font=font
    ))

    # Set CSP frame-ancestors header for partner allowlist
    partner_origins = current_app.config.get('PARTNER_ORIGINS', [])
    if partner_origins:
        frame_ancestors = "'self' " + " ".join(partner_origins)
    else:
        # In development, allow any origin for testing
        frame_ancestors = "'self' *" if current_app.config.get('ENV') == 'development' else "'self'"

    response.headers['Content-Security-Policy'] = f"frame-ancestors {frame_ancestors}"

    # Remove X-Frame-Options to allow framing (CSP frame-ancestors takes precedence)
    response.headers.pop('X-Frame-Options', None)

    return response


@discussions_bp.route('/<int:discussion_id>/<slug>', methods=['GET'])
@track_discussion_view
def view_discussion(discussion_id, slug):
    # Track social media clicks (conversion tracking)
    user_id = str(current_user.id) if current_user.is_authenticated else None
    track_social_click(request, user_id)
    
    from app.models import Statement
    from sqlalchemy import desc, func
    
    # Eager load creator and source_article_links with nested article.source to prevent N+1 queries
    # Using selectinload for nested relationships to ensure proper eager loading
    discussion = Discussion.query.options(
        joinedload(Discussion.creator),
        selectinload(Discussion.source_article_links)
        .joinedload(DiscussionSourceArticle.article)
        .joinedload(NewsArticle.source)
    ).get_or_404(discussion_id)
    # Redirect if the slug in the URL doesn't match the discussion's slug
    if discussion.slug != slug:
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # For native discussions, fetch statements
    statements = []
    sort = 'progressive'
    form = None
    
    if discussion.has_native_statements:
        from app.discussions.statement_forms import StatementForm
        form = StatementForm()
        sort = request.args.get('sort', 'progressive')
        
        # Base query with eager loading of user data and responses (with their users) to prevent N+1 queries
        from app.models import Response
        query = Statement.query.options(
            joinedload(Statement.user),
            joinedload(Statement.responses).joinedload(Response.user)
        ).filter_by(
            discussion_id=discussion_id,
            is_deleted=False
        )
        
        # Apply moderation filter for non-owners
        if not (current_user.is_authenticated and 
                (current_user.id == discussion.creator_id or current_user.is_admin)):
            query = query.filter(Statement.mod_status >= 0)
        
        # Apply sorting
        if sort == 'progressive':
            # Prioritize statements with fewer votes (pol.is pattern)
            query = query.order_by(
                (Statement.vote_count_agree + 
                 Statement.vote_count_disagree + 
                 Statement.vote_count_unsure).asc(),
                func.random()
            )
        elif sort == 'best':
            query = query.order_by(desc(Statement.vote_count_agree))
        elif sort == 'recent':
            query = query.order_by(desc(Statement.created_at))
        elif sort == 'most_voted':
            query = query.order_by(
                desc(Statement.vote_count_agree + 
                     Statement.vote_count_disagree + 
                     Statement.vote_count_unsure))
        elif sort == 'controversial':
            # Fetch all and sort by controversy score in Python
            statements = query.all()
            statements.sort(key=lambda s: s.controversy_score, reverse=True)
            user_vote_count, _ = get_user_vote_count(discussion_id)
            return render_template('discussions/view_discussion.html', 
                                 discussion=discussion,
                                 statements=statements,
                                 sort=sort,
                                 form=form,
                                 user_vote_count=user_vote_count,
                                 participation_threshold=PARTICIPATION_THRESHOLD)
        
        # Default pagination
        statements = query.limit(20).all()
    
    # Get user's vote count for participation gate display
    user_vote_count, _ = get_user_vote_count(discussion_id)
    
    # Render the page
    return render_template('discussions/view_discussion.html', 
                         discussion=discussion,
                         statements=statements,
                         sort=sort,
                         form=form,
                         user_vote_count=user_vote_count,
                         participation_threshold=PARTICIPATION_THRESHOLD)



def fetch_discussions(search, country, city, topic, keywords, page, per_page=9, sort='recent'):
    from sqlalchemy import or_
    query = Discussion.query

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
    page = request.args.get('page', 1, type=int)
    sort = request.args.get('sort', 'popular')

    # Use modified fetch_discussions to include sorting
    discussions = fetch_discussions(
        search=search_term,
        country=country,
        city=city,
        topic=topic,
        keywords=keywords,
        page=page,
        sort=sort
    )

    return render_template(
        'discussions/search_discussions.html',
        discussions=discussions,
        search_term=search_term,
        countries=countries,
        cities_by_country=cities_by_country
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
                    'keywords': keywords
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
        discussion = Discussion.query.get_or_404(discussion_id)
        
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
        discussion = Discussion.query.get_or_404(discussion_id)
        
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


@discussions_bp.route('/api/discussions/<int:discussion_id>/simulate-activity', methods=['POST'])
@limiter.limit("10 per minute")
def simulate_discussion_activity(discussion_id):
    """
    Simulate discussion activity for testing notifications
    """
    try:
        discussion = Discussion.query.get_or_404(discussion_id)
        
        # Get simulation type
        activity_data = request.get_json()
        simulation_type = activity_data.get('type', 'new_participant')
        
        if simulation_type == 'new_participant':
            # Simulate a new participant
            import time
            participant = DiscussionParticipant.track_participant(
                discussion_id=discussion_id,
                user_id=None,
                participant_identifier=f"sim_participant_{int(time.time())}"
            )
            
            # Create notification if discussion has a creator
            notification_created = False
            notification_error = None
            if discussion.creator_id:
                try:
                    notification = create_discussion_notification(
                        user_id=discussion.creator_id,
                        discussion_id=discussion_id,
                        notification_type='new_participant',
                        additional_data={'participant_count': discussion.participant_count}
                    )
                    notification_created = notification is not None
                except Exception as e:
                    notification_error = str(e)
                    current_app.logger.error(f"Failed to create notification in simulation: {e}")
            
            # Return success for participant creation regardless of notification result
            response_data = {
                'status': 'success',
                'message': 'New participant activity simulated',
                'participant_created': True,
                'notification_created': notification_created
            }
            
            if notification_error:
                response_data['notification_error'] = notification_error
            
            return jsonify(response_data), 200
        
        elif simulation_type == 'new_response':
            # Simulate new response activity
            notification_created = False
            notification_error = None
            if discussion.creator_id:
                try:
                    notification = create_discussion_notification(
                        user_id=discussion.creator_id,
                        discussion_id=discussion_id,
                        notification_type='new_response',
                        additional_data={'response_count': 1}
                    )
                    notification_created = notification is not None
                except Exception as e:
                    notification_error = str(e)
                    current_app.logger.error(f"Failed to create notification in simulation: {e}")
            
            response_data = {
                'status': 'success',
                'message': 'New response activity simulated',
                'notification_created': notification_created
            }
            
            if notification_error:
                response_data['notification_error'] = notification_error
                
            return jsonify(response_data), 200
        
        return jsonify({
            'status': 'error',
            'message': 'Invalid simulation type'
        }), 400
        
    except Exception as e:
        current_app.logger.error(f"Error simulating activity: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': 'Failed to simulate activity'
        }), 500
