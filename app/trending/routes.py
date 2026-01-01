"""
Admin Routes for Trending Topics Management

Provides UI for:
- Viewing the review queue
- Publishing/editing/merging/discarding topics
- Managing news sources
- Running the pipeline manually
"""

import logging
from datetime import datetime
from flask import render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user

from app import db
from app.models import TrendingTopic, NewsSource, Discussion, NewsArticle
from app.trending import trending_bp
from app.trending.pipeline import run_pipeline, get_review_queue, get_pipeline_stats, process_held_topics
from app.trending.publisher import publish_topic, merge_topic_into_discussion
from app.trending.seed_generator import generate_seed_statements
from app.trending.scorer import score_topic

logger = logging.getLogger(__name__)


def admin_required(f):
    """Decorator to require admin access."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash("Admin access required", "error")
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


@trending_bp.route('/')
@login_required
@admin_required
def dashboard():
    """Trending topics dashboard."""
    from app.trending.topic_signals import get_hot_topics_summary
    
    stats = get_pipeline_stats()
    queue = get_review_queue()
    sources = NewsSource.query.order_by(NewsSource.name).all()
    hot_topics = get_hot_topics_summary()
    
    return render_template(
        'trending/dashboard.html',
        stats=stats,
        queue=queue,
        sources=sources,
        hot_topics=hot_topics
    )


@trending_bp.route('/run-pipeline', methods=['POST'])
@login_required
@admin_required
def trigger_pipeline():
    """Manually trigger the news pipeline."""
    try:
        articles, topics, ready = run_pipeline(hold_minutes=30)
        flash(f"Pipeline complete: {articles} articles fetched, {topics} topics created, {ready} ready for review", "success")
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        flash(f"Pipeline error: {str(e)}", "error")
    
    return redirect(url_for('trending.dashboard'))


@trending_bp.route('/process-pending', methods=['POST'])
@login_required
@admin_required
def process_pending():
    """Process pending topics that are past their hold time."""
    try:
        ready = process_held_topics(batch_size=20)
        if ready > 0:
            flash(f"Processed {ready} topics - now ready for review", "success")
        else:
            flash("No pending topics ready to process", "info")
    except Exception as e:
        logger.error(f"Process pending error: {e}")
        flash(f"Error processing pending topics: {str(e)}", "error")
    
    return redirect(url_for('trending.dashboard'))


@trending_bp.route('/articles')
@login_required
@admin_required
def view_articles():
    """View recent articles."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    articles = NewsArticle.query.order_by(
        NewsArticle.fetched_at.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template(
        'trending/articles.html',
        articles=articles
    )


@trending_bp.route('/topic/<int:topic_id>')
@login_required
@admin_required
def view_topic(topic_id):
    """View topic details."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    recent_discussions = Discussion.query.filter_by(
        has_native_statements=True
    ).order_by(Discussion.created_at.desc()).limit(20).all()
    
    return render_template(
        'trending/topic_detail.html',
        topic=topic,
        recent_discussions=recent_discussions
    )


@trending_bp.route('/topic/<int:topic_id>/publish', methods=['POST'])
@login_required
@admin_required
def publish(topic_id):
    """Publish a topic as a discussion."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    if topic.status not in ['pending_review', 'approved']:
        flash("Topic cannot be published in current state", "error")
        return redirect(url_for('trending.view_topic', topic_id=topic_id))
    
    discussion = publish_topic(topic, current_user)
    
    if discussion:
        flash(f"Published as discussion: {discussion.title}", "success")
        return redirect(url_for('discussions.view_discussion', discussion_id=discussion.id, slug=discussion.slug))
    else:
        flash("Failed to publish topic", "error")
        return redirect(url_for('trending.view_topic', topic_id=topic_id))


@trending_bp.route('/topic/<int:topic_id>/edit', methods=['POST'])
@login_required
@admin_required
def edit_topic(topic_id):
    """Edit topic title and description."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    topic.title = request.form.get('title', topic.title)
    topic.description = request.form.get('description', topic.description)
    
    db.session.commit()
    flash("Topic updated", "success")
    
    return redirect(url_for('trending.view_topic', topic_id=topic_id))


@trending_bp.route('/topic/<int:topic_id>/regenerate-seeds', methods=['POST'])
@login_required
@admin_required
def regenerate_seeds(topic_id):
    """Regenerate seed statements for a topic."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    seeds = generate_seed_statements(topic, count=7)
    topic.seed_statements = seeds
    db.session.commit()
    
    flash(f"Regenerated {len(seeds)} seed statements", "success")
    return redirect(url_for('trending.view_topic', topic_id=topic_id))


@trending_bp.route('/topic/<int:topic_id>/rescore', methods=['POST'])
@login_required
@admin_required
def rescore_topic(topic_id):
    """Rescore a topic."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    topic = score_topic(topic)
    db.session.commit()
    
    flash("Topic rescored", "success")
    return redirect(url_for('trending.view_topic', topic_id=topic_id))


@trending_bp.route('/topic/<int:topic_id>/merge', methods=['POST'])
@login_required
@admin_required
def merge(topic_id):
    """Merge topic into an existing discussion."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    discussion_id = request.form.get('discussion_id', type=int)
    if not discussion_id:
        flash("Please select a discussion to merge into", "error")
        return redirect(url_for('trending.view_topic', topic_id=topic_id))
    
    discussion = Discussion.query.get_or_404(discussion_id)
    
    merge_topic_into_discussion(topic, discussion, current_user)
    
    flash(f"Merged into: {discussion.title}", "success")
    return redirect(url_for('discussions.view_discussion', slug=discussion.slug))


@trending_bp.route('/topic/<int:topic_id>/discard', methods=['POST'])
@login_required
@admin_required
def discard(topic_id):
    """Discard a topic."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    topic.status = 'discarded'
    topic.reviewed_by_id = current_user.id
    topic.reviewed_at = datetime.utcnow()
    db.session.commit()
    
    flash("Topic discarded", "success")
    return redirect(url_for('trending.dashboard'))


@trending_bp.route('/sources')
@login_required
@admin_required
def manage_sources():
    """Manage news sources."""
    sources = NewsSource.query.order_by(NewsSource.name).all()
    return render_template('trending/sources.html', sources=sources)


@trending_bp.route('/sources/add', methods=['POST'])
@login_required
@admin_required
def add_source():
    """Add a new news source."""
    name = request.form.get('name')
    feed_url = request.form.get('feed_url')
    source_type = request.form.get('source_type', 'rss')
    reputation = float(request.form.get('reputation_score', 0.7))
    
    if not name or not feed_url:
        flash("Name and URL are required", "error")
        return redirect(url_for('trending.manage_sources'))
    
    existing = NewsSource.query.filter_by(name=name).first()
    if existing:
        flash("Source with this name already exists", "error")
        return redirect(url_for('trending.manage_sources'))
    
    source = NewsSource(
        name=name,
        feed_url=feed_url,
        source_type=source_type,
        reputation_score=reputation
    )
    db.session.add(source)
    db.session.commit()
    
    flash(f"Added source: {name}", "success")
    return redirect(url_for('trending.manage_sources'))


@trending_bp.route('/sources/<int:source_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_source(source_id):
    """Toggle source active status."""
    source = NewsSource.query.get_or_404(source_id)
    source.is_active = not source.is_active
    db.session.commit()
    
    status = "activated" if source.is_active else "deactivated"
    flash(f"Source {status}: {source.name}", "success")
    return redirect(url_for('trending.manage_sources'))


@trending_bp.route('/sources/<int:source_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_source(source_id):
    """Delete a news source."""
    source = NewsSource.query.get_or_404(source_id)
    name = source.name
    
    db.session.delete(source)
    db.session.commit()
    
    flash(f"Deleted source: {name}", "success")
    return redirect(url_for('trending.manage_sources'))


@trending_bp.route('/api/stats')
@login_required
@admin_required
def api_stats():
    """API endpoint for pipeline stats."""
    return jsonify(get_pipeline_stats())


@trending_bp.route('/topic/<int:topic_id>/share-bluesky', methods=['POST'])
@login_required
@admin_required
def share_to_bluesky(topic_id):
    """Manually share a published topic to Bluesky."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    if not topic.created_discussion:
        flash("Topic must be published first", "error")
        return redirect(url_for('trending.view_topic', topic_id=topic_id))
    
    try:
        from app.trending.social_poster import post_to_bluesky
        from flask import current_app
        
        base_url = current_app.config.get('SITE_URL', 'https://societyspeaks.io')
        discussion = topic.created_discussion
        discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"
        
        uri = post_to_bluesky(
            title=discussion.title,
            topic=discussion.topic or 'Society',
            discussion_url=discussion_url
        )
        
        if uri:
            flash("Posted to Bluesky successfully!", "success")
        else:
            flash("Failed to post to Bluesky. Check app password.", "error")
    except Exception as e:
        logger.error(f"Bluesky share error: {e}")
        flash(f"Error posting to Bluesky: {str(e)}", "error")
    
    return redirect(url_for('trending.view_topic', topic_id=topic_id))


@trending_bp.route('/topic/<int:topic_id>/x-share-url')
@login_required
@admin_required
def get_x_share_url(topic_id):
    """Generate and redirect to X share URL."""
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    if not topic.created_discussion:
        flash("Topic must be published first", "error")
        return redirect(url_for('trending.view_topic', topic_id=topic_id))
    
    from app.trending.social_poster import generate_x_share_url
    from flask import current_app
    
    base_url = current_app.config.get('SITE_URL', 'https://societyspeaks.io')
    discussion = topic.created_discussion
    discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"
    
    share_url = generate_x_share_url(
        title=discussion.title,
        topic=discussion.topic or 'Society',
        discussion_url=discussion_url
    )
    
    return redirect(share_url)
