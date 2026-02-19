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
from app.lib.time import utcnow_naive
from flask import render_template, redirect, url_for, flash, request, jsonify, current_app
from flask_login import login_required, current_user

from app import db
from app.models import TrendingTopic, NewsSource, Discussion, NewsArticle
from app.trending import trending_bp
from app.trending.pipeline import run_pipeline, get_review_queue, get_pipeline_stats, process_held_topics
from app.trending.publisher import publish_topic, merge_topic_into_discussion
from app.trending.seed_generator import generate_seed_statements
from app.trending.scorer import score_topic
from app.trending.news_fetcher import clean_summary
from app.decorators import admin_required

logger = logging.getLogger(__name__)


@trending_bp.route('/')
@login_required
@admin_required
def dashboard():
    """Trending topics dashboard."""
    from app.trending.topic_signals import get_hot_topics_summary
    from app.trending.social_poster import get_social_posting_status
    
    page = request.args.get('page', 1, type=int)
    per_page = 50

    stats = get_pipeline_stats()
    queue = get_review_queue(page=page, per_page=per_page)
    sources = NewsSource.query.order_by(NewsSource.name).all()
    hot_topics = get_hot_topics_summary()
    social_status = get_social_posting_status()
    
    return render_template(
        'trending/dashboard.html',
        stats=stats,
        queue=queue,
        sources=sources,
        hot_topics=hot_topics,
        social_status=social_status
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
    """View recent articles with search/filter."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    search = request.args.get('search', '').strip()
    source_id = request.args.get('source', type=int)
    status = request.args.get('status', '')
    keyword = request.args.get('keyword', '').strip()
    
    query = NewsArticle.query.options(
        db.joinedload(NewsArticle.source)
    )

    if search:
        query = query.filter(
            db.or_(
                NewsArticle.title.ilike(f'%{search}%'),
                NewsArticle.summary.ilike(f'%{search}%')
            )
        )
    
    if keyword:
        query = query.filter(
            db.or_(
                NewsArticle.title.ilike(f'%{keyword}%'),
                NewsArticle.summary.ilike(f'%{keyword}%')
            )
        )
    
    if source_id:
        query = query.filter(NewsArticle.source_id == source_id)
    
    if status == 'unscored':
        query = query.filter(NewsArticle.relevance_score.is_(None))
    elif status == 'scored':
        query = query.filter(NewsArticle.relevance_score.isnot(None))
    elif status == 'high_relevance':
        query = query.filter(NewsArticle.relevance_score >= 0.7)
    elif status == 'medium_relevance':
        query = query.filter(NewsArticle.relevance_score >= 0.4, NewsArticle.relevance_score < 0.7)
    elif status == 'low_relevance':
        query = query.filter(NewsArticle.relevance_score < 0.4)
    
    if status in ['high_relevance', 'medium_relevance', '']:
        query = query.order_by(NewsArticle.relevance_score.desc().nullslast(), NewsArticle.fetched_at.desc())
    else:
        query = query.order_by(NewsArticle.fetched_at.desc())
    
    articles = query.paginate(page=page, per_page=per_page, error_out=False)
    
    sources = NewsSource.query.order_by(NewsSource.name).all()
    
    return render_template(
        'trending/articles.html',
        articles=articles,
        sources=sources,
        search=search,
        source_id=source_id,
        status=status,
        keyword=keyword
    )


@trending_bp.route('/topic/<int:topic_id>')
@login_required
@admin_required
def view_topic(topic_id):
    """View topic details."""
    from app.models import TrendingTopicArticle, NewsArticle
    from sqlalchemy.orm import joinedload

    topic = TrendingTopic.query.options(
        joinedload(TrendingTopic.articles)
        .joinedload(TrendingTopicArticle.article)
        .joinedload(NewsArticle.source)
    ).get_or_404(topic_id)

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
    topic.reviewed_at = utcnow_naive()
    db.session.commit()
    
    flash("Topic discarded", "success")
    return redirect(url_for('trending.dashboard'))


@trending_bp.route('/topic/<int:topic_id>/unpublish', methods=['POST'])
@login_required
@admin_required
def unpublish(topic_id):
    """Unpublish a topic - delete discussion and all related records, revert to pending_review."""
    from app.models import DiscussionSourceArticle, Statement, StatementVote
    
    topic = TrendingTopic.query.get_or_404(topic_id)
    
    if topic.status != 'published' or not topic.discussion_id:
        flash("Topic is not published", "error")
        return redirect(url_for('trending.view_topic', topic_id=topic_id))
    
    discussion_id = topic.discussion_id
    discussion_title = None
    
    try:
        discussion = db.session.get(Discussion, discussion_id)
        if discussion:
            discussion_title = discussion.title
            
            DiscussionSourceArticle.query.filter_by(discussion_id=discussion_id).delete()
            
            StatementVote.query.filter_by(discussion_id=discussion_id).delete()
            
            Statement.query.filter_by(discussion_id=discussion_id).delete()
            
            db.session.delete(discussion)
        
        topic.status = 'pending_review'
        topic.discussion_id = None
        topic.published_at = None
        db.session.commit()
        
        current_app.logger.info(f"Unpublished topic {topic_id}: deleted discussion '{discussion_title}' and related records")
        flash("Discussion unpublished and topic reverted to review queue", "success")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Failed to unpublish topic {topic_id}: {e}")
        flash(f"Error unpublishing: {str(e)}", "error")
    
    return redirect(url_for('trending.view_topic', topic_id=topic_id))


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
    try:
        reputation = float(request.form.get('reputation_score', 0.7))
    except (ValueError, TypeError):
        reputation = 0.7
    
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


@trending_bp.route('/articles/score-unscored', methods=['POST'])
@login_required
@admin_required
def score_unscored_articles():
    """Score all unscored articles."""
    from app.trending.scorer import score_articles_with_llm
    
    try:
        unscored = NewsArticle.query.filter(
            NewsArticle.sensationalism_score.is_(None)
        ).limit(100).all()
        
        if not unscored:
            flash("No unscored articles found", "info")
            return redirect(url_for('trending.view_articles'))
        
        score_articles_with_llm(unscored)
        db.session.commit()
        
        scored_count = sum(1 for a in unscored if a.sensationalism_score is not None)
        flash(f"Scored {scored_count} articles", "success")
    except Exception as e:
        logger.error(f"Scoring error: {e}")
        db.session.rollback()
        flash(f"Error scoring articles: {str(e)}", "error")
    
    return redirect(url_for('trending.view_articles'))


@trending_bp.route('/article/<int:article_id>/promote', methods=['POST'])
@login_required
@admin_required
def promote_article(article_id):
    """Promote a single article to a discussion topic."""
    from app.trending.clustering import generate_neutral_question, get_embeddings
    from datetime import timedelta
    from app.models import TrendingTopicArticle
    
    article = NewsArticle.query.get_or_404(article_id)
    
    try:
        title = generate_neutral_question([article])
        if not title:
            title = f"Discussion: {article.title[:100]}"
        
        text = f"{article.title}. {article.summary or ''}"
        embeddings = get_embeddings([text])
        topic_embedding = embeddings[0] if embeddings else None
        
        topic = TrendingTopic(
            title=title,
            description=article.summary or '',
            topic_embedding=topic_embedding,
            source_count=1,
            status='pending_review',
            hold_until=utcnow_naive()
        )
        
        db.session.add(topic)
        db.session.flush()
        
        link = TrendingTopicArticle(
            topic_id=topic.id,
            article_id=article.id
        )
        db.session.add(link)
        db.session.commit()
        
        flash(f"Article promoted to topic: {title[:60]}...", "success")
        return redirect(url_for('trending.view_topic', topic_id=topic.id))
    except Exception as e:
        logger.error(f"Promote error: {e}")
        db.session.rollback()
        flash(f"Error promoting article: {str(e)}", "error")
    
    return redirect(url_for('trending.view_articles'))


@trending_bp.route('/articles/bulk-action', methods=['POST'])
@login_required
@admin_required
def bulk_article_action():
    """Handle bulk actions on articles."""
    from app.trending.clustering import generate_neutral_question, get_embeddings
    from app.models import TrendingTopicArticle
    from app.trending.scorer import score_articles_with_llm
    
    action = request.form.get('action')
    article_ids_raw = request.form.getlist('article_ids')
    article_ids = [int(x) for x in article_ids_raw if x and x.isdigit()]
    
    if not article_ids:
        flash("No articles selected", "error")
        return redirect(url_for('trending.view_articles'))
    
    articles = NewsArticle.query.filter(NewsArticle.id.in_(article_ids)).all()
    
    if action == 'score':
        try:
            score_articles_with_llm(articles)
            db.session.commit()
            flash(f"Scored {len(articles)} articles", "success")
        except Exception as e:
            logger.error(f"Bulk score error: {e}")
            db.session.rollback()
            flash(f"Error scoring articles: {str(e)}", "error")
    
    elif action == 'create_topic':
        try:
            from app.trending.clustering import generate_neutral_question, get_embeddings, extract_geographic_info_from_articles
            
            title = generate_neutral_question(articles)
            if not title:
                title = f"Discussion: {articles[0].title[:100]}"
            
            texts = [f"{a.title}. {a.summary or ''}" for a in articles]
            combined = " ".join(texts)[:2000]
            embeddings = get_embeddings([combined])
            topic_embedding = embeddings[0] if embeddings else None
            
            # Extract geographic info from source articles
            geographic_scope, geographic_countries = extract_geographic_info_from_articles(articles)
            
            topic = TrendingTopic(
                title=title,
                description=articles[0].summary or '',
                topic_embedding=topic_embedding,
                source_count=len(set(a.source_id for a in articles)),
                geographic_scope=geographic_scope,
                geographic_countries=geographic_countries,
                status='pending_review',
                hold_until=utcnow_naive()
            )
            
            db.session.add(topic)
            db.session.flush()
            
            for article in articles:
                link = TrendingTopicArticle(
                    topic_id=topic.id,
                    article_id=article.id
                )
                db.session.add(link)
            
            db.session.commit()
            flash(f"Created topic from {len(articles)} articles", "success")
            return redirect(url_for('trending.view_topic', topic_id=topic.id))
        except Exception as e:
            logger.error(f"Bulk topic error: {e}")
            db.session.rollback()
            flash(f"Error creating topic: {str(e)}", "error")
    
    return redirect(url_for('trending.view_articles'))


@trending_bp.route('/clean-summaries', methods=['POST'])
@login_required
@admin_required
def clean_summaries():
    """Clean promotional content from existing article summaries and topic descriptions."""
    cleaned_articles = 0
    cleaned_topics = 0
    
    try:
        articles = NewsArticle.query.filter(NewsArticle.summary.isnot(None)).all()
        for article in articles:
            original = article.summary
            cleaned = clean_summary(original)
            if cleaned != original:
                article.summary = cleaned
                cleaned_articles += 1
        
        topics = TrendingTopic.query.filter(TrendingTopic.description.isnot(None)).all()
        for topic in topics:
            original = topic.description
            cleaned = clean_summary(original)
            if cleaned != original:
                topic.description = cleaned
                cleaned_topics += 1
        
        db.session.commit()
        flash(f"Cleaned {cleaned_articles} article summaries and {cleaned_topics} topic descriptions", "success")
    except Exception as e:
        logger.error(f"Error cleaning summaries: {e}")
        db.session.rollback()
        flash(f"Error cleaning summaries: {str(e)}", "error")
    
    return redirect(url_for('trending.dashboard'))
