from flask import Blueprint, render_template, request, jsonify
from app.models import Discussion
from datetime import datetime

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

@main_bp.route('/discussion/<discussion_id>')
def discussion(discussion_id):
    discussion = Discussion.query.filter_by(polis_id=discussion_id).first_or_404()
    polis_url = f"https://pol.is/{discussion_id}"
    return render_template('discussion.html',
                         discussion=discussion,
                         polis_url=polis_url)

@main_bp.route('/api/discussions/search')
def search_discussions():
    search = request.args.get('search', '')
    country = request.args.get('country', '')
    city = request.args.get('city', '')
    topic = request.args.get('topic', '')
    page = request.args.get('page', 1, type=int)

    pagination = Discussion.search_discussions(
        search=search,
        country=country,
        city=city,
        topic=topic,
        page=page
    )

    return jsonify({
        'discussions': [d.to_dict() for d in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': pagination.page
    })