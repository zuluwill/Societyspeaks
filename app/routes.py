from flask import Blueprint, render_template, request, jsonify, Response, current_app, url_for
from app.models import Discussion
from app import db
from datetime import datetime
from slugify import slugify
from app.seo import generate_sitemap

main_bp = Blueprint('main', __name__)

def init_routes(app):
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_globals():
        return {
            'year': datetime.utcnow().year,
            'topics': Discussion.TOPICS
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

    return render_template('index.html',
                         featured_discussions=featured_discussions,
                         discussions=discussions,
                         pagination=pagination,
                         search=search,
                         country=country,
                         city=city,
                         topic=topic)


@main_bp.route('/about')
def about():
    return render_template('about.html')




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
        print(f"Error generating sitemap: {e}")
        return Response("Error generating sitemap", status=500)



@main_bp.route('/test-sitemap')
def test_sitemap():
    """Test route to view sitemap content"""
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
    """Serve the robots.txt file"""
    try:
        base_url = get_base_url()
        robots_txt = f"""User-agent: Googlebot
Allow: /
Allow: /sitemap.xml

User-agent: *
Allow: /
Disallow: /account/settings
Disallow: /user/settings
Disallow: /api/
Disallow: /admin/
Disallow: /login
Disallow: /register
Disallow: /*/*/edit
Disallow: /*/edit

# Only allow these file types to be indexed
Allow: /*.html$
Allow: /*.htm$
Allow: /*.xml$
Allow: /*.json$

# Crawl-delay: 10

Sitemap: {base_url}/sitemap.xml"""
        return Response(robots_txt, mimetype='text/plain')
    except Exception as e:
        current_app.logger.error(f"Error serving robots.txt: {str(e)}")
        return Response("Error generating robots.txt", status=500)


@main_bp.route('/test-robots')
def test_robots():
    """Test route to verify robots.txt"""
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