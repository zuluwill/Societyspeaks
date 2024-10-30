from flask import render_template, redirect, url_for, flash, request, Blueprint
from flask_login import login_required, current_user
from app import db
from app.discussions.forms import CreateDiscussionForm
from app.models import Discussion


discussions_bp = Blueprint('discussions', __name__)

@discussions_bp.route('/create', methods=['GET', 'POST'])
@login_required
def create_discussion():
    form = CreateDiscussionForm()
    if form.validate_on_submit():
        # Create a new discussion
        discussion = Discussion(
            polis_id=form.polis_id.data,
            title=form.title.data,
            description=form.description.data,
            topic=form.topic.data,
            country=form.country.data,
            city=form.city.data,
            creator_id=current_user.id,
            individual_profile_id=current_user.individual_profile.id if current_user.profile_type == 'individual' else None,
            company_profile_id=current_user.company_profile.id if current_user.profile_type == 'company' else None
        )
        db.session.add(discussion)
        db.session.commit()
        flash("Discussion created successfully!", "success")
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id))
    return render_template('discussions/create_discussion.html', form=form)


@discussions_bp.route('/<int:discussion_id>/<slug>', methods=['GET'])
def view_discussion(discussion_id, slug):
    discussion = Discussion.query.get_or_404(discussion_id)
    # Check if the slug in the URL matches the one from the discussion
    if discussion.slug != slug:
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id, slug=discussion.slug))

    polis_url = f"https://pol.is/{discussion.polis_id}"
    return render_template('discussions/view_discussion.html', discussion=discussion, polis_url=polis_url)




def fetch_discussions(search, country, city, topic, keywords, page, per_page=9):
    return Discussion.search_discussions(
        search=search, country=country, city=city, topic=topic, keywords=keywords, page=page, per_page=per_page
    )


@discussions_bp.route('/search', methods=['GET'])
def search_discussions():
    search_term = request.args.get('q', '')
    topic = request.args.get('topic')
    country = request.args.get('country')
    city = request.args.get('city')
    keywords = request.args.get('keywords', '')
    page = request.args.get('page', 1, type=int)

    discussions = fetch_discussions(search_term, country, city, topic, keywords, page)

    return render_template(
        'discussions/search_discussions.html', 
        discussions=discussions, 
        search_term=search_term
    )



@discussions_bp.route('/api/search', methods=['GET'])
def api_search_discussions():
    search = request.args.get('search', '')
    country = request.args.get('country', '')
    city = request.args.get('city', '')
    topic = request.args.get('topic', '')
    keywords = request.args.get('keywords', '')
    page = request.args.get('page', 1, type=int)
    pagination = fetch_discussions(search, country, city, topic, keywords, page)
    return jsonify({
        'discussions': [d.to_dict() for d in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': pagination.page
    })







