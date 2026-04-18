import stripe
from flask import Blueprint, render_template, request, jsonify, Response, current_app, url_for, abort, send_file, make_response, send_from_directory, redirect, flash
from flask_login import login_required, current_user
from app.models import Discussion, IndividualProfile, CompanyProfile, DailyQuestion, DailyBrief, Programme
from app.programmes.journey import (
    guided_journey_slug_set,
    infer_journey_country_from_accept_language,
    journey_programme_country_lookup_key,
)
from app import cache, db, limiter
from datetime import datetime, date
from slugify import slugify
from app.seo import generate_sitemap
try:
    from replit.object_storage import Client
    from replit.object_storage.errors import ObjectNotFoundError
except (ImportError, ModuleNotFoundError, AttributeError):
    Client = None
    class ObjectNotFoundError(Exception):
        pass
from sqlalchemy.orm import joinedload
from app.lib.time import utcnow_naive
import io
import mimetypes
import os

main_bp = Blueprint('main', __name__)
asset_client = Client() if Client is not None else None

def init_routes(app):
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_globals():
        from app.brief.sections import SECTIONS
        return {
            'year': utcnow_naive().year,
            'topics': Discussion.TOPICS,
            'now': utcnow_naive,
            'SECTIONS': SECTIONS
        }


def get_base_url():
    """Get the base URL depending on environment"""
    if request.headers.get('X-Forwarded-Proto'):
        return f"{request.scheme}://{request.headers['Host']}"
    return 'https://societyspeaks.io'



@main_bp.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    country = request.args.get('country', '')
    city = request.args.get('city', '')
    topic = request.args.get('topic', '')

    # Get featured discussions - this will now always return up to 6 discussions
    featured_discussions = Discussion.get_featured()

    # Get filtered discussions with pagination for the rest of the page
    pagination = Discussion.search_discussions(
        search=search,
        country=country,
        city=city,
        topic=topic,
        page=page
    )
    discussions = pagination.items

    # Total discussion count for the trust strip (cached hourly)
    total_discussion_count_display = cache.get('trust_strip_discussion_count')
    if total_discussion_count_display is None:
        try:
            from sqlalchemy import func as _sqlfunc
            raw = db.session.query(_sqlfunc.count(Discussion.id)).scalar() or 0
            floor_hundred = (raw // 100) * 100
            total_discussion_count_display = f"{floor_hundred:,}+" if floor_hundred else "1,000+"
        except Exception:
            total_discussion_count_display = "1,000+"
        cache.set('trust_strip_discussion_count', total_discussion_count_display, timeout=3600)

    # Get today's daily question for the homepage preview
    daily_question = DailyQuestion.query.options(
        joinedload(DailyQuestion.source_discussion)
    ).filter_by(
        question_date=date.today(),
        status='published'
    ).first()
    
    # Get today's or most recent daily brief for the homepage preview
    daily_brief = DailyBrief.get_today()
    if not daily_brief:
        # Fall back to most recent published brief
        daily_brief = DailyBrief.query.filter_by(status='published').order_by(DailyBrief.date.desc()).first()
    brief_items = []
    if daily_brief:
        brief_items = daily_brief.items.order_by(db.text('position')).limit(5).all()

    journey_slugs = guided_journey_slug_set()
    _jp_cache_key = "homepage_journey_programmes"
    _slug_fp = ",".join(sorted(journey_slugs))
    all_journey_programmes = None
    try:
        _cached = cache.get(_jp_cache_key)
        if isinstance(_cached, tuple) and len(_cached) == 2:
            _fp, _rows = _cached
            if _fp == _slug_fp:
                all_journey_programmes = _rows
    except Exception:
        pass
    if all_journey_programmes is None:
        all_journey_programmes = (
            Programme.query.filter(
                Programme.slug.in_(journey_slugs),
                Programme.status == 'active',
            ).order_by(Programme.name.asc()).all()
            if journey_slugs else []
        )
        try:
            cache.set(_jp_cache_key, (_slug_fp, all_journey_programmes), timeout=300)
        except Exception:
            pass

    # Geo-prioritise: show the visitor's country journey first if we have one.
    # We do not use IP geolocation (VPN-safe). Priority order:
    # explicit ?journey= / ?edition= slug → profile country → Accept-Language → global fallback.
    # Profile country is stored as ISO-style codes (e.g. UK, US) on IndividualProfile / CompanyProfile;
    # Programme.country uses full names — journey_programme_country_lookup_key bridges the two.
    _by_country = {(p.country or '').lower(): p for p in all_journey_programmes}
    _global_journey = next((p for p in all_journey_programmes if not p.country), None)

    guided_journey_programme = None
    # journey_personalisation: 'chosen' | 'profile' | 'language' | 'fallback'
    # Used in the template to set the right recommendation label.
    journey_personalisation = "fallback"

    # Explicit edition (bookmark / share / VPN or wrong browser language).
    explicit_slug = (request.args.get("journey") or request.args.get("edition") or "").strip().lower()
    if explicit_slug and explicit_slug in journey_slugs:
        guided_journey_programme = next(
            (p for p in all_journey_programmes if p.slug and p.slug.lower() == explicit_slug),
            None,
        )
        if guided_journey_programme:
            journey_personalisation = "chosen"

    if current_user.is_authenticated and not guided_journey_programme:
        profile_country = None
        pt = getattr(current_user, "profile_type", None)
        if pt == "company" and getattr(current_user, "company_profile", None):
            profile_country = current_user.company_profile.country
        elif getattr(current_user, "individual_profile", None):
            profile_country = current_user.individual_profile.country
        elif getattr(current_user, "company_profile", None):
            profile_country = current_user.company_profile.country
        country_key = journey_programme_country_lookup_key(profile_country)
        if country_key:
            guided_journey_programme = _by_country.get(country_key)
            if guided_journey_programme:
                journey_personalisation = "profile"

    if not guided_journey_programme:
        accept_lang = request.headers.get("Accept-Language", "")
        inferred_key = infer_journey_country_from_accept_language(accept_lang)
        if inferred_key:
            guided_journey_programme = _by_country.get(inferred_key)
            if guided_journey_programme:
                journey_personalisation = "language"

    if not guided_journey_programme:
        guided_journey_programme = _global_journey or (all_journey_programmes[0] if all_journey_programmes else None)

    return render_template('index.html',
                         featured_discussions=featured_discussions,
                         discussions=discussions,
                         pagination=pagination,
                         search=search,
                         country=country,
                         city=city,
                         topic=topic,
                         daily_question=daily_question,
                         daily_brief=daily_brief,
                         brief_items=brief_items,
                         guided_journey_programme=guided_journey_programme,
                         journey_personalisation=journey_personalisation,
                         all_journey_programmes=all_journey_programmes,
                         total_discussion_count_display=total_discussion_count_display)


@main_bp.route('/about')
def about():
    return render_template('about.html')


@main_bp.route('/platform')
def platform():
    demo_discussion = db.session.get(Discussion, 25)
    featured_discussions = Discussion.get_featured(limit=3)
    return render_template('platform.html', demo_discussion=demo_discussion, featured_discussions=featured_discussions)


@main_bp.route('/donate')
def donate():
    return render_template('donate.html')


@main_bp.route('/donate/success')
@limiter.limit("30 per minute")
def donate_success():
    from app.billing.service import get_stripe

    session_id = request.args.get('session_id', '')
    if not session_id or not session_id.startswith('cs_'):
        flash("No valid donation session found.", 'error')
        return redirect(url_for('main.donate'))

    # Confirm with Stripe that this is a completed donation — do not trust the URL alone.
    # Note: only card payments are currently enabled (payment_method_types=['card']),
    # so payment_status is 'paid' immediately on success. If async payment methods
    # (BACS, SEPA) are ever added, this check must accommodate 'unpaid' + webhook confirmation.
    try:
        s = get_stripe()
        checkout_session = s.checkout.Session.retrieve(session_id)
        metadata = getattr(checkout_session, 'metadata', None) or {}
        payment_status = getattr(checkout_session, 'payment_status', None)
        if metadata.get('purpose') != 'donation' or payment_status != 'paid':
            flash("Your donation is being confirmed. Please check back in a moment.", 'info')
            return redirect(url_for('main.donate'))
    except stripe.error.InvalidRequestError:
        # Unknown or test session ID — don't leak detail to the user.
        flash("No valid donation session found.", 'error')
        return redirect(url_for('main.donate'))
    except stripe.error.StripeError as e:
        current_app.logger.warning(f"Stripe verification failed for donation success session {session_id}: {e}")
        flash("We could not verify your donation yet. Please check back in a moment.", 'info')
        return redirect(url_for('main.donate'))
    except Exception as e:
        current_app.logger.warning(f"Unexpected donation success verification error for session {session_id}: {e}")
        flash("We could not verify your donation yet. Please check back in a moment.", 'info')
        return redirect(url_for('main.donate'))

    return render_template('donate_success.html')


def _is_scanner_or_bogus_asset_path(filename: str) -> bool:
    """
    Return True if the path looks like a vulnerability scanner (e.g. .php probes, .env probes),
    not a real asset. Avoids blocking legitimate filenames that contain 'php' (e.g. php-tutorial.pdf).
    """
    lower = filename.lower()
    # Block path segments ending in .php (e.g. m.php, c99.php), not names that merely contain 'php'
    if lower.endswith('.php') or '/.php' in lower or '.php/' in lower:
        return True
    if any(x in lower for x in ('/filemanager/', '/server/php/', '/c99.php', '/fk2e3')):
        return True
    if filename.endswith('/') or '//' in filename:
        return True
    # Block attempts to probe for sensitive config/env files
    basename = os.path.basename(lower)
    if basename in ('.env', '.env.local', '.env.production', '.env.example', '.htaccess',
                    'web.config', 'wp-config.php', 'config.php'):
        return True
    if basename.startswith('.env.'):
        return True
    return False


def _serve_object_storage_asset(filename):
    """Serve static assets from object storage to avoid disk I/O."""
    if '..' in filename or filename.startswith('/'):
        current_app.logger.warning(f"Blocked path traversal attempt for asset: {filename}")
        abort(404)

    if _is_scanner_or_bogus_asset_path(filename):
        abort(404)

    storage_path = f"static_assets/{filename}"

    try:
        file_data = asset_client.download_as_bytes(storage_path)
    except ObjectNotFoundError:
        current_app.logger.warning(f"Asset not found in storage: {storage_path}")
        abort(404)
    except Exception as error:
        error_msg = str(error)
        if 'not found' in error_msg.lower() or 'does not exist' in error_msg.lower() or 'could not be found' in error_msg.lower():
            current_app.logger.warning(f"Asset not found in storage: {storage_path}")
            abort(404)
        current_app.logger.error(f"Error fetching asset {storage_path}: {error}")
        return Response("Service unavailable", status=503)

    if not file_data:
        current_app.logger.info(f"Asset not found in storage: {storage_path}")
        abort(404)

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = 'application/octet-stream'

    response = make_response(
        send_file(
            io.BytesIO(file_data),
            mimetype=mime_type,
            as_attachment=False,
            download_name=os.path.basename(filename)
        )
    )
    response.headers['Cache-Control'] = 'public, max-age=3600'
    return response


@main_bp.route('/favicon.ico')
def favicon():
    """Serve favicon from static files."""
    return send_from_directory(
        os.path.join(current_app.root_path, 'static'),
        'favicon.png',
        mimetype='image/png'
    )


@main_bp.route('/assets/<path:filename>')
def serve_asset(filename):
    """Serve static assets from object storage."""
    return _serve_object_storage_asset(filename)


@main_bp.route('/images/<path:filename>')
def serve_static_image(filename):
    """Back-compat image route served from object storage."""
    return _serve_object_storage_asset(f"images/{filename}")




@main_bp.route('/profile/<slug>')
def view_profile(slug):
    # Logic to check if slug corresponds to an individual or company
    individual = IndividualProfile.query.filter_by(slug=slug).first()
    company = CompanyProfile.query.filter_by(slug=slug).first()

    if individual:
        return render_template('individual_profile.html', profile=individual)
    elif company:
        return render_template('company_profile.html', profile=company)
    else:
        abort(404)


@main_bp.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy-policy.html')

@main_bp.route('/terms-and-conditions')
def terms_and_conditions():
    return render_template('terms-and-conditions.html')


@main_bp.route('/content-policy')
def content_policy():
    """Short content policy for partners: what we allow and remove. Linked from partner hub and embed footer."""
    return render_template('content-policy.html')


@main_bp.route('/faq')
def faq():
    return render_template('faq.html')



@main_bp.route('/sitemap.xml')
def sitemap():
    """Serve the sitemap.xml file"""
    try:
        sitemap_xml = generate_sitemap()
        response = Response(sitemap_xml, mimetype='application/xml')
        response.headers['X-Robots-Tag'] = 'noarchive'  # Allow Google to crawl but not cache
        response.headers['Cache-Control'] = 'public, max-age=3600'  # Cache for 1 hour
        return response
    except Exception as e:
        current_app.logger.error(f"Error generating sitemap: {e}")
        return Response("Error generating sitemap", status=500)



@main_bp.route('/test-sitemap')
@login_required
def test_sitemap():
    """Test route to view sitemap content - admin only"""
    if not current_user.is_admin:
        abort(403)
    try:
        sitemap_xml = generate_sitemap()
        return f"""
        <html>
        <head>
            <title>Sitemap Test</title>
        </head>
        <body>
            <h1>Sitemap Test</h1>
            <p>Base URL: {get_base_url()}</p>
            <pre style="background:#f5f5f5; padding:15px;">
{sitemap_xml}
            </pre>
        </body>
        </html>
        """
    except Exception as e:
        return f"Error generating sitemap: {str(e)}"


@main_bp.route('/robots.txt')
def robots():
    """Serve the robots.txt file with LLM crawler support for GEO/AI discovery"""
    try:
        base_url = get_base_url()
        robots_txt = f"""# Society Speaks - robots.txt
# Optimized for search engines and LLM/AI crawlers

# Search Engine Crawlers
User-agent: Googlebot
Allow: /
Crawl-delay: 1

User-agent: Bingbot
Allow: /
Crawl-delay: 1

# LLM/AI Crawlers - Explicitly allowed for GEO/AI discovery
User-agent: GPTBot
Allow: /

User-agent: ChatGPT-User
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: Claude-Web
Allow: /

User-agent: Anthropic-AI
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Cohere-ai
Allow: /

User-agent: Meta-ExternalAgent
Allow: /

# Default rules for all other crawlers
User-agent: *
Allow: /
Allow: /news
Allow: /news/
Allow: /discussions
Allow: /discussions/
Allow: /help
Allow: /help/
Allow: /about
Allow: /sitemap.xml

# Block private/auth areas
Disallow: /account/
Disallow: /user/settings
Disallow: /api/
Disallow: /admin/
Disallow: /login
Disallow: /register
Disallow: /auth/
Disallow: /*/*/edit
Disallow: /*/edit

# Sitemaps and LLM Context
Sitemap: {base_url}/sitemap.xml

# LLM Context File (emerging standard for AI discoverability)
# See: https://llmstxt.org
LLMsTXT: {base_url}/llms.txt"""
        return Response(robots_txt, mimetype='text/plain')
    except Exception as e:
        current_app.logger.error(f"Error serving robots.txt: {str(e)}")
        return Response("Error generating robots.txt", status=500)


@main_bp.route('/test-robots')
@login_required
def test_robots():
    """Test route to verify robots.txt - admin only"""
    if not current_user.is_admin:
        abort(403)
    try:
        base_url = get_base_url()

        # Get the content that would be served by the route
        with current_app.test_client() as client:
            response = client.get('/robots.txt')
            robots_content = response.data.decode('utf-8')

        return f"""
        <html>
            <head>
                <title>Robots.txt Test</title>
                <style>
                    pre {{ background: #f5f5f5; padding: 15px; overflow-x: auto; }}
                    .info {{ color: green; }}
                    .error {{ color: red; }}
                </style>
            </head>
            <body>
                <h1>Robots.txt Validation</h1>
                <div class="info">
                    <p>Base URL: {base_url}</p>
                    <p>Robots.txt URL: <a href="/robots.txt" target="_blank">{base_url}/robots.txt</a></p>
                </div>
                <h2>Current robots.txt Content:</h2>
                <pre>{robots_content}</pre>
                <p>
                    <a href="https://www.google.com/webmasters/tools/robots-testing-tool" target="_blank">
                        Test robots.txt with Google's Robot Testing Tool
                    </a>
                </p>
            </body>
        </html>
        """
    except Exception as e:
        return f"Error testing robots.txt: {str(e)}"


@main_bp.route('/llms.txt')
def llms_txt():
    """Serve the llms.txt file for LLM/AI discoverability (GEO)"""
    try:
        return current_app.send_static_file('llms.txt')
    except Exception as e:
        current_app.logger.error(f"Error serving llms.txt: {str(e)}")
        return Response("LLMs context file not found", status=404)