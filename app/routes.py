from flask import Blueprint, render_template, request, jsonify
from app.models import Discussion
from app import db
from datetime import datetime
from slugify import slugify

main_bp = Blueprint('main', __name__)

def init_routes(app):
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_globals():
        return {
            'year': datetime.utcnow().year,
            'topics': Discussion.TOPICS
        }

@main_bp.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    country = request.args.get('country', '')
    city = request.args.get('city', '')
    topic = request.args.get('topic', '')

    # Get featured discussions
    featured_discussions = Discussion.get_featured()

    # Get filtered discussions with pagination
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
