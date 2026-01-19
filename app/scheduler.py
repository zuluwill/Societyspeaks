# app/scheduler.py
"""
Background Task Scheduler (Phase 3.3)

Uses APScheduler to run periodic tasks:
- Automated consensus clustering for active discussions
- Cleanup old analysis data
- Statistics updates

Designed for Replit deployment (single-instance friendly)
"""
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import logging
import threading

logger = logging.getLogger(__name__)
scheduler = None


def _is_production_environment() -> bool:
    """
    Check if we're running in the DEPLOYED production environment.
    
    Used to prevent development environments from sending real emails,
    social media posts, etc. to avoid duplicates when both dev and prod run.
    
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    !! CRITICAL: DO NOT ADD FLASK_ENV CHECK HERE!                       !!
    !! FLASK_ENV=production is set in dev, causing DUPLICATE EMAILS!    !!
    !! This bug has caused duplicate emails to users MULTIPLE TIMES.    !!
    !! Only REPLIT_DEPLOYMENT=1 reliably indicates deployed production. !!
    !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    
    Returns True ONLY if:
    - REPLIT_DEPLOYMENT is set to '1' (Replit deployments only)
    """
    import os
    
    # ONLY check Replit deployment environment variable
    # This is the ONLY reliable indicator that we're in a deployed environment
    #
    # WARNING: Do NOT add checks for:
    # - FLASK_ENV (is 'production' in dev too!)
    # - REPLIT_DEV_DOMAIN (unreliable)
    # - Any other heuristics
    #
    # REPLIT_DEPLOYMENT=1 is set ONLY by Replit when app is deployed
    return os.environ.get('REPLIT_DEPLOYMENT') == '1'


def init_scheduler(app):
    """
    Initialize the APScheduler with Flask app context
    """
    global scheduler
    
    if scheduler is not None:
        logger.warning("Scheduler already initialized")
        return scheduler
    
    # Configure scheduler with generous misfire handling
    # This allows jobs to run even if app restarts around scheduled time
    scheduler = BackgroundScheduler(
        job_defaults={
            'coalesce': True,  # Combine multiple missed runs into one
            'max_instances': 1,  # Only one instance of each job at a time
            'misfire_grace_time': 3600  # Allow jobs to run up to 1 hour late
        }
    )
    
    # Add jobs with app context
    @scheduler.scheduled_job('interval', hours=6, id='auto_cluster_discussions')
    def auto_cluster_active_discussions():
        """
        Automatically run clustering on active discussions
        Runs every 6 hours
        """
        with app.app_context():
            from app import db
            from app.models import Discussion, StatementVote, ConsensusAnalysis
            from app.lib.consensus_engine import run_consensus_analysis, save_consensus_analysis, can_cluster
            
            logger.info("Starting automated clustering task")
            
            # Find discussions that need clustering
            # Criteria:
            # - Has native statements
            # - Has recent activity (votes in last 7 days)
            # - No analysis in last 6 hours OR has new votes since last analysis
            
            recent_activity_threshold = datetime.utcnow() - timedelta(days=7)
            recent_analysis_threshold = datetime.utcnow() - timedelta(hours=6)
            
            # Get discussions with recent votes
            active_discussion_ids = db.session.query(StatementVote.discussion_id).filter(
                StatementVote.created_at >= recent_activity_threshold
            ).distinct().all()
            
            active_discussion_ids = [d[0] for d in active_discussion_ids]
            
            logger.info(f"Found {len(active_discussion_ids)} discussions with recent activity")
            
            for discussion_id in active_discussion_ids:
                try:
                    discussion = Discussion.query.get(discussion_id)
                    
                    if not discussion or not discussion.has_native_statements:
                        continue
                    
                    # Check if ready for clustering
                    ready, message = can_cluster(discussion_id, db)
                    if not ready:
                        logger.debug(f"Discussion {discussion_id} not ready: {message}")
                        continue
                    
                    # Check last analysis
                    last_analysis = ConsensusAnalysis.query.filter_by(
                        discussion_id=discussion_id
                    ).order_by(ConsensusAnalysis.created_at.desc()).first()
                    
                    if last_analysis:
                        # Skip if recently analyzed
                        if last_analysis.created_at >= recent_analysis_threshold:
                            logger.debug(f"Discussion {discussion_id} recently analyzed, skipping")
                            continue
                        
                        # Check if new votes since last analysis
                        new_votes = StatementVote.query.filter(
                            StatementVote.discussion_id == discussion_id,
                            StatementVote.created_at > last_analysis.created_at
                        ).count()
                        
                        if new_votes < 5:  # Need at least 5 new votes to reanalyze
                            logger.debug(f"Discussion {discussion_id} has only {new_votes} new votes, skipping")
                            continue
                    
                    # Run analysis
                    logger.info(f"Running automated clustering for discussion {discussion_id}")
                    results = run_consensus_analysis(discussion_id, db, method='agglomerative')
                    
                    if results:
                        save_consensus_analysis(discussion_id, results, db)
                        logger.info(f"Successfully clustered discussion {discussion_id}")
                    
                except Exception as e:
                    logger.error(f"Error clustering discussion {discussion_id}: {e}", exc_info=True)
                    continue
            
            logger.info("Automated clustering task complete")
    
    
    @scheduler.scheduled_job('cron', hour=3, id='cleanup_old_analyses')
    def cleanup_old_consensus_analyses():
        """
        Clean up old consensus analyses and news data
        Runs daily at 3 AM
        """
        with app.app_context():
            from app import db
            from app.models import (
                ConsensusAnalysis, Discussion, NewsArticle, TrendingTopic, 
                TrendingTopicArticle, DiscussionSourceArticle, BriefItem
            )
            from datetime import timedelta
            
            logger.info("Starting cleanup of old data")
            
            cutoff_30_days = datetime.utcnow() - timedelta(days=30)
            cutoff_7_days = datetime.utcnow() - timedelta(days=7)
            
            # Get IDs of articles linked to published discussions (we want to KEEP these)
            # These preserve source attribution for user-facing content
            articles_in_discussions = db.session.query(
                DiscussionSourceArticle.article_id
            ).distinct().subquery()
            
            # Clean up low-relevance articles (with foreign key handling)
            # EXCLUDE articles that are linked to discussions - we keep those
            try:
                low_relevance_article_ids = db.session.query(NewsArticle.id).filter(
                    NewsArticle.fetched_at < cutoff_7_days,
                    NewsArticle.relevance_score.isnot(None),
                    NewsArticle.relevance_score < 0.3,
                    NewsArticle.id.notin_(articles_in_discussions)  # Keep discussion sources
                ).all()
                low_relevance_ids = [a[0] for a in low_relevance_article_ids]
                
                if low_relevance_ids:
                    # First delete references in trending_topic_article
                    refs_deleted = TrendingTopicArticle.query.filter(
                        TrendingTopicArticle.article_id.in_(low_relevance_ids)
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    if refs_deleted > 0:
                        logger.info(f"Deleted {refs_deleted} topic-article references for low-relevance articles")
                    
                    # Now safe to delete the articles
                    low_relevance_deleted = NewsArticle.query.filter(
                        NewsArticle.id.in_(low_relevance_ids)
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    if low_relevance_deleted > 0:
                        logger.info(f"Deleted {low_relevance_deleted} low-relevance articles (>7 days old)")
            except Exception as e:
                logger.error(f"Error cleaning up low-relevance articles: {e}")
                db.session.rollback()
            
            # Also check if articles are in briefs via topics (prevents losing source attribution)
            articles_in_brief_topics = db.session.query(
                TrendingTopicArticle.article_id
            ).join(
                BriefItem, BriefItem.trending_topic_id == TrendingTopicArticle.topic_id
            ).distinct().subquery()
            
            # Clean up old articles (with foreign key handling)
            # EXCLUDE articles that are linked to discussions OR briefs - we keep those
            try:
                old_article_ids = db.session.query(NewsArticle.id).filter(
                    NewsArticle.fetched_at < cutoff_30_days,
                    NewsArticle.id.notin_(articles_in_discussions),  # Keep discussion sources
                    NewsArticle.id.notin_(articles_in_brief_topics)  # Keep brief sources
                ).all()
                old_ids = [a[0] for a in old_article_ids]
                
                if old_ids:
                    # First delete references in trending_topic_article
                    old_refs_deleted = TrendingTopicArticle.query.filter(
                        TrendingTopicArticle.article_id.in_(old_ids)
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    if old_refs_deleted > 0:
                        logger.info(f"Deleted {old_refs_deleted} topic-article references for old articles")
                    
                    # Now safe to delete the articles
                    old_articles = NewsArticle.query.filter(
                        NewsArticle.id.in_(old_ids)
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    if old_articles > 0:
                        logger.info(f"Deleted {old_articles} old news articles (>30 days)")
            except Exception as e:
                logger.error(f"Error cleaning up old articles: {e}")
                db.session.rollback()
            
            # Clean up discarded topics (with foreign key handling)
            # Note: Only delete topics that are NOT referenced by BriefItem (used in Daily Brief)
            try:
                from app.models import BriefItem
                
                # Get IDs of topics used in briefs (we want to KEEP these)
                topics_in_briefs = db.session.query(
                    BriefItem.trending_topic_id
                ).distinct().subquery()
                
                # Find discarded topics to delete
                discarded_topic_ids = db.session.query(TrendingTopic.id).filter(
                    TrendingTopic.status == 'discarded',
                    TrendingTopic.created_at < cutoff_30_days,
                    TrendingTopic.id.notin_(topics_in_briefs)  # Keep topics used in briefs
                ).all()
                discarded_ids = [t[0] for t in discarded_topic_ids]
                
                if discarded_ids:
                    # First delete TrendingTopicArticle references
                    topic_refs_deleted = TrendingTopicArticle.query.filter(
                        TrendingTopicArticle.topic_id.in_(discarded_ids)
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    if topic_refs_deleted > 0:
                        logger.info(f"Deleted {topic_refs_deleted} topic-article references for discarded topics")
                    
                    # Now safe to delete the topics
                    old_discarded = TrendingTopic.query.filter(
                        TrendingTopic.id.in_(discarded_ids)
                    ).delete(synchronize_session=False)
                    db.session.commit()
                    if old_discarded > 0:
                        logger.info(f"Deleted {old_discarded} old discarded topics")
            except Exception as e:
                logger.error(f"Error cleaning up discarded topics: {e}")
                db.session.rollback()
            
            logger.info("Starting cleanup of old consensus analyses")
            
            # Only get discussion IDs that have analyses to clean up (more efficient)
            discussion_ids_with_analyses = db.session.query(
                ConsensusAnalysis.discussion_id
            ).group_by(ConsensusAnalysis.discussion_id).having(
                db.func.count(ConsensusAnalysis.id) > 10
            ).all()
            
            for (discussion_id,) in discussion_ids_with_analyses:
                try:
                    # Get all analyses for this discussion
                    analyses = ConsensusAnalysis.query.filter_by(
                        discussion_id=discussion_id
                    ).order_by(ConsensusAnalysis.created_at.desc()).all()
                    
                    # Keep only 10 most recent
                    if len(analyses) > 10:
                        to_delete = analyses[10:]
                        for analysis in to_delete:
                            db.session.delete(analysis)
                        
                        db.session.commit()
                        logger.info(f"Deleted {len(to_delete)} old analyses for discussion {discussion_id}")
                    
                except Exception as e:
                    logger.error(f"Error cleaning up analyses for discussion {discussion_id}: {e}")
                    db.session.rollback()
                    continue

            # Clean up old news perspective cache entries (keep last 7 days)
            try:
                from app.models import NewsPerspectiveCache
                from datetime import date

                cutoff_date = date.today() - timedelta(days=7)
                deleted_perspectives = NewsPerspectiveCache.query.filter(
                    NewsPerspectiveCache.generated_date < cutoff_date
                ).delete()

                if deleted_perspectives > 0:
                    db.session.commit()
                    logger.info(f"Deleted {deleted_perspectives} old news perspective cache entries")

            except Exception as e:
                logger.error(f"Error cleaning up news perspective cache: {e}")
                db.session.rollback()

            logger.info("Cleanup task complete")
    
    
    @scheduler.scheduled_job('cron', hour='7,12,18,22', id='trending_topics_pipeline')
    def run_trending_topics_pipeline():
        """
        Fetch news and process trending topics
        Runs 4 times daily: 7am, 12pm, 6pm, 10pm UTC
        Optimized for cost efficiency while catching major news cycles
        """
        with app.app_context():
            from app.trending.pipeline import run_pipeline, process_held_topics
            
            logger.info("Starting trending topics pipeline")
            
            try:
                articles, topics, ready = run_pipeline(hold_minutes=60)
                logger.info(f"Pipeline result: {articles} articles, {topics} new topics, {ready} ready for review")
                
                held_ready = process_held_topics()
                if held_ready > 0:
                    logger.info(f"Processed {held_ready} held topics")
                    
            except Exception as e:
                logger.error(f"Trending topics pipeline error: {e}", exc_info=True)
            
            logger.info("Trending topics pipeline complete")
    
    
    @scheduler.scheduled_job('cron', hour=8, id='daily_auto_publish')
    def daily_auto_publish():
        """
        Auto-publish up to 5 diverse topics daily.
        Runs once at 8am UTC.
        Bluesky and X posts are scheduled for staggered times throughout the day.
        """
        with app.app_context():
            from app.trending.pipeline import auto_publish_daily
            
            logger.info("Starting daily auto-publish")
            
            try:
                published = auto_publish_daily(max_topics=5, schedule_bluesky=True, schedule_x=True)
                logger.info(f"Auto-published {published} topics (Bluesky and X posts scheduled)")
            except Exception as e:
                logger.error(f"Daily auto-publish error: {e}", exc_info=True)
            
            logger.info("Daily auto-publish complete")
    
    
    @scheduler.scheduled_job('cron', hour=9, id='single_source_to_discussions')
    def single_source_to_discussions():
        """
        Process single-source content (podcasts, newsletters) into discussions.
        Runs once daily at 9am UTC (after daily auto-publish).
        Creates discussions with AI-generated seed statements.
        """
        with app.app_context():
            from app.trending.podcast_publisher import process_single_source_articles
            
            logger.info("Starting single-source-to-discussions pipeline")
            
            try:
                stats = process_single_source_articles(
                    source_categories=['podcast', 'newsletter', 'magazine', 'think_tank'],
                    days=14,
                    max_per_source=3
                )
                logger.info(f"Single-source pipeline complete: {stats}")
            except Exception as e:
                logger.error(f"Single-source pipeline error: {e}", exc_info=True)
    
    
    @scheduler.scheduled_job('cron', minute='*/15', id='process_scheduled_bluesky')
    def process_scheduled_bluesky():
        """
        Process scheduled Bluesky posts.
        Runs every 15 minutes to check for posts due to be sent.
        Posts are scheduled at: 2pm, 4pm, 6pm, 8pm, 10pm UTC
        (= 9am, 11am, 1pm, 3pm, 5pm EST for US audience)
        """
        with app.app_context():
            from app.trending.social_poster import process_scheduled_bluesky_posts
            
            try:
                posted = process_scheduled_bluesky_posts()
                if posted > 0:
                    logger.info(f"Posted {posted} scheduled Bluesky posts")
            except Exception as e:
                logger.error(f"Scheduled Bluesky processing error: {e}", exc_info=True)
    
    
    @scheduler.scheduled_job('cron', minute='*/15', id='process_scheduled_x')
    def process_scheduled_x():
        """
        Process scheduled X/Twitter posts.
        Runs every 15 minutes to check for posts due to be sent.
        Posts are scheduled at: 2pm, 4pm, 6pm, 8pm, 10pm UTC
        (= 9am, 11am, 1pm, 3pm, 5pm EST for US audience)
        """
        with app.app_context():
            from app.trending.social_poster import process_scheduled_x_posts
            
            try:
                posted = process_scheduled_x_posts()
                if posted > 0:
                    logger.info(f"Posted {posted} scheduled X posts")
            except Exception as e:
                logger.error(f"Scheduled X processing error: {e}", exc_info=True)
    
    
    @scheduler.scheduled_job('cron', hour='9,15,21', id='backfill_orphan_articles')
    def backfill_orphan_articles_job():
        """
        Backfill orphan articles to existing topics.
        Runs 3 times daily to enrich topics with more sources.
        """
        with app.app_context():
            from app.trending.pipeline import backfill_orphan_articles
            
            logger.info("Starting orphan article backfill")
            
            try:
                backfilled = backfill_orphan_articles(limit=100)
                logger.info(f"Backfilled {backfilled} orphan articles")
            except Exception as e:
                logger.error(f"Orphan article backfill error: {e}", exc_info=True)
            
            logger.info("Orphan article backfill complete")
    

    @scheduler.scheduled_job('cron', hour=7, minute=30, id='daily_question_publish')
    def daily_question_publish():
        """
        Auto-publish today's daily question and schedule upcoming questions.
        Runs at 7:30am UTC (before email send).
        
        Idempotency: auto_publish_todays_question checks if question already published
        """
        with app.app_context():
            from app.daily.auto_selection import auto_publish_todays_question, auto_schedule_upcoming_questions
            from app.models import DailyQuestion
            from datetime import date
            
            logger.info("Starting daily question auto-publish")
            
            try:
                # Idempotency check - skip if question already published today
                existing = DailyQuestion.query.filter_by(
                    question_date=date.today(),
                    status='published'
                ).first()
                if existing:
                    logger.info(f"Daily question #{existing.question_number} already published, skipping")
                else:
                    question = auto_publish_todays_question()
                    if question:
                        logger.info(f"Published daily question #{question.question_number}")
                    else:
                        logger.warning("No daily question available to publish")
                
                scheduled = auto_schedule_upcoming_questions(days_ahead=7)
                logger.info(f"Auto-scheduled {scheduled} upcoming questions")
            except Exception as e:
                logger.error(f"Daily question publish error: {e}", exc_info=True)
            
            logger.info("Daily question auto-publish complete")
    
    
    _email_send_in_progress = threading.Event()
    
    def _run_email_send_in_thread(app_instance):
        """Run email send in background thread with its own app context"""
        try:
            with app_instance.app_context():
                # Use new Resend client with batch API for faster sending
                from app.resend_client import send_daily_question_to_all_subscribers
                
                logger.info("Background thread: Starting daily question email send (via Resend)")
                sent = send_daily_question_to_all_subscribers()
                logger.info(f"Background thread: Sent daily question to {sent} subscribers")
        except Exception as e:
            logger.error(f"Background thread: Daily question email error: {e}", exc_info=True)
        finally:
            _email_send_in_progress.clear()
            logger.info("Background thread: Daily question email send complete")
    
    @scheduler.scheduled_job('cron', hour=8, minute=0, id='daily_question_email')
    def daily_question_email():
        """
        Send daily question email to all subscribers.
        Runs at 8:00am UTC (after question is published).
        Launches in background thread to not block other scheduled jobs.
        
        IMPORTANT: Only sends in production to prevent duplicate emails from dev environment.
        """
        # Skip email sending in development environment to prevent duplicates
        if not _is_production_environment():
            logger.info("Skipping daily question email - development environment")
            return
            
        if _email_send_in_progress.is_set():
            logger.warning("Daily question email send already in progress, skipping")
            return
        
        _email_send_in_progress.set()
        logger.info("Launching daily question email send in background thread")
        
        email_thread = threading.Thread(
            target=_run_email_send_in_thread,
            args=(app,),
            daemon=True,
            name="daily-email-sender"
        )
        email_thread.start()
        logger.info("Daily question email thread launched, scheduler continuing")
    
    
    @scheduler.scheduled_job('cron', hour=14, minute=0, id='post_daily_question_to_social')
    def post_daily_question_to_social():
        """
        Post today's daily question to social media.
        
        Timing optimized for UK/USA audience:
        - 2pm UTC = 9am EST (USA morning) / 2pm UK (afternoon)
        - Good engagement time for both regions
        
        Runs after question is published and emails are sent.
        
        IMPORTANT: Only posts in production to prevent duplicates from dev environment.
        """
        # Skip social posting in development environment to prevent duplicates
        if not _is_production_environment():
            logger.info("Skipping daily question social post - development environment")
            return
            
        with app.app_context():
            from app.models import DailyQuestion
            from app.trending.social_insights import generate_daily_question_post
            from app.trending.social_poster import post_to_x, post_to_bluesky, DuplicatePostError
            from datetime import date
            import posthog
            
            try:
                question = DailyQuestion.query.filter_by(
                    question_date=date.today(),
                    status='published'
                ).first()
                
                if not question:
                    logger.debug("No published daily question today, skipping social post")
                    return
                
                # Generate posts
                x_post = generate_daily_question_post(question, platform='x')
                bluesky_post = generate_daily_question_post(question, platform='bluesky')
                
                # Post to X
                try:
                    x_url = f"https://societyspeaks.io/daily/{question.question_date.strftime('%Y-%m-%d')}"
                    x_post_text = generate_daily_question_post(question, platform='x')
                    tweet_id = post_to_x(
                        title=question.question_text,
                        topic=question.topic_category or 'Society',
                        discussion_url=x_url,
                        discussion=None,  # Daily question, not discussion
                        custom_text=x_post_text
                    )
                    
                    if tweet_id:
                        logger.info(f"Posted daily question #{question.question_number} to X: {tweet_id}")
                        
                        # Track with PostHog
                        if posthog.project_api_key:
                            try:
                                posthog.capture(
                                    distinct_id='system',
                                    event='daily_question_posted_to_x',
                                    properties={
                                        'question_id': question.id,
                                        'question_number': question.question_number,
                                        'tweet_id': tweet_id,
                                        'response_count': question.response_count
                                    }
                                )
                            except Exception as e:
                                logger.warning(f"PostHog tracking error: {e}")
                except DuplicatePostError:
                    logger.info(f"Daily question #{question.question_number} already posted to X (duplicate)")
                except Exception as e:
                    logger.error(f"Error posting daily question to X: {e}")
                
                # Post to Bluesky
                try:
                    bluesky_url = f"https://societyspeaks.io/daily/{question.question_date.strftime('%Y-%m-%d')}"
                    bluesky_post_text = generate_daily_question_post(question, platform='bluesky')
                    bluesky_uri = post_to_bluesky(
                        title=question.question_text,
                        topic=question.topic_category or 'Society',
                        discussion_url=bluesky_url,
                        discussion=None,  # Daily question, not discussion
                        custom_text=bluesky_post_text
                    )
                    
                    if bluesky_uri:
                        logger.info(f"Posted daily question #{question.question_number} to Bluesky: {bluesky_uri}")
                        
                        # Track with PostHog
                        if posthog.project_api_key:
                            try:
                                posthog.capture(
                                    distinct_id='system',
                                    event='daily_question_posted_to_bluesky',
                                    properties={
                                        'question_id': question.id,
                                        'question_number': question.question_number,
                                        'bluesky_uri': bluesky_uri,
                                        'response_count': question.response_count
                                    }
                                )
                            except Exception as e:
                                logger.warning(f"PostHog tracking error: {e}")
                except Exception as e:
                    logger.error(f"Error posting daily question to Bluesky: {e}")
                    
            except Exception as e:
                logger.error(f"Error posting daily question to social media: {e}", exc_info=True)
    
    
    @scheduler.scheduled_job('cron', day_of_week='sun', hour=17, minute=0, id='post_weekly_insights')
    def post_weekly_insights():
        """
        Post weekly insights (value-first content, 80/20 rule).
        
        Timing: Sunday 5pm UTC = 12pm EST / 5pm UK
        Good engagement time for both regions.
        
        Part of 80/20 strategy: 80% value, 20% promotion.
        This is value-first content.
        
        IMPORTANT: Only posts in production to prevent duplicates from dev environment.
        """
        # Skip social posting in development environment to prevent duplicates
        if not _is_production_environment():
            logger.info("Skipping weekly insights social post - development environment")
            return
            
        with app.app_context():
            from app.trending.value_content import generate_weekly_insights_post
            from app.trending.social_poster import post_to_x, post_to_bluesky, DuplicatePostError
            import posthog
            
            try:
                # Generate value-first content
                x_post = generate_weekly_insights_post(platform='x')
                bluesky_post = generate_weekly_insights_post(platform='bluesky')
                
                if not x_post:
                    logger.debug("No weekly insights to post")
                    return
                
                # Post to X
                try:
                    tweet_id = post_to_x(
                        title="Weekly Insights",
                        topic='Society',
                        discussion_url="https://societyspeaks.io",
                        custom_text=x_post
                    )
                    
                    if tweet_id:
                        logger.info(f"Posted weekly insights to X: {tweet_id}")
                        
                        # Track with PostHog
                        if posthog.project_api_key:
                            try:
                                posthog.capture(
                                    distinct_id='system',
                                    event='weekly_insights_posted',
                                    properties={
                                        'platform': 'x',
                                        'tweet_id': tweet_id,
                                        'content_type': 'value_first'
                                    }
                                )
                            except Exception as e:
                                logger.warning(f"PostHog tracking error: {e}")
                except DuplicatePostError:
                    logger.info("Weekly insights already posted to X (duplicate)")
                except Exception as e:
                    logger.error(f"Error posting weekly insights to X: {e}")
                
                # Post to Bluesky
                try:
                    bluesky_uri = post_to_bluesky(
                        title="Weekly Insights",
                        topic='Society',
                        discussion_url="https://societyspeaks.io",
                        custom_text=bluesky_post
                    )
                    
                    if bluesky_uri:
                        logger.info(f"Posted weekly insights to Bluesky: {bluesky_uri}")
                        
                        # Track with PostHog
                        if posthog.project_api_key:
                            try:
                                posthog.capture(
                                    distinct_id='system',
                                    event='weekly_insights_posted',
                                    properties={
                                        'platform': 'bluesky',
                                        'post_uri': bluesky_uri,
                                        'content_type': 'value_first'
                                    }
                                )
                            except Exception as e:
                                logger.warning(f"PostHog tracking error: {e}")
                except Exception as e:
                    logger.error(f"Error posting weekly insights to Bluesky: {e}")
                    
            except Exception as e:
                logger.error(f"Error posting weekly insights: {e}", exc_info=True)
    
    
    @scheduler.scheduled_job('cron', hour=18, minute=30, id='post_daily_brief_to_social')
    def post_daily_brief_to_social():
        """
        Post today's daily brief to social media.
        
        Timing optimized for UK/USA audience:
        - 6:30pm UTC = 1:30pm EST (USA lunch) / 6:30pm UK (evening)
        - Good engagement time for both regions
        - Runs 30 minutes after brief is published (6pm UTC)
        
        IMPORTANT: Only posts in production to prevent duplicates from dev environment.
        """
        # Skip social posting in development environment to prevent duplicates
        if not _is_production_environment():
            logger.info("Skipping daily brief social post - development environment")
            return
            
        with app.app_context():
            from app.models import DailyBrief
            from app.trending.social_insights import generate_daily_brief_post
            from app.trending.social_poster import post_to_x, post_to_bluesky, DuplicatePostError
            from datetime import date
            import posthog
            
            try:
                brief = DailyBrief.query.filter_by(
                    date=date.today(),
                    status='published'
                ).first()
                
                if not brief:
                    logger.debug("No published daily brief today, skipping social post")
                    return
                
                # Generate posts
                x_post = generate_daily_brief_post(brief, platform='x')
                bluesky_post = generate_daily_brief_post(brief, platform='bluesky')
                
                # Post to X
                try:
                    x_url = f"https://societyspeaks.io/brief/{brief.date.strftime('%Y-%m-%d')}"
                    x_post_text = generate_daily_brief_post(brief, platform='x')
                    tweet_id = post_to_x(
                        title=brief.title,
                        topic='News',
                        discussion_url=x_url,
                        discussion=None,  # Daily brief, not discussion
                        custom_text=x_post_text
                    )
                    
                    if tweet_id:
                        logger.info(f"Posted daily brief to X: {tweet_id}")
                        
                        # Track with PostHog
                        if posthog.project_api_key:
                            try:
                                posthog.capture(
                                    distinct_id='system',
                                    event='daily_brief_posted_to_x',
                                    properties={
                                        'brief_id': brief.id,
                                        'brief_date': brief.date.isoformat(),
                                        'tweet_id': tweet_id,
                                        'item_count': brief.item_count
                                    }
                                )
                            except Exception as e:
                                logger.warning(f"PostHog tracking error: {e}")
                except DuplicatePostError:
                    logger.info(f"Daily brief already posted to X (duplicate)")
                except Exception as e:
                    logger.error(f"Error posting daily brief to X: {e}")
                
                # Post to Bluesky
                try:
                    bluesky_url = f"https://societyspeaks.io/brief/{brief.date.strftime('%Y-%m-%d')}"
                    bluesky_post_text = generate_daily_brief_post(brief, platform='bluesky')
                    bluesky_uri = post_to_bluesky(
                        title=brief.title,
                        topic='News',
                        discussion_url=bluesky_url,
                        discussion=None,  # Daily brief, not discussion
                        custom_text=bluesky_post_text
                    )
                    
                    if bluesky_uri:
                        logger.info(f"Posted daily brief to Bluesky: {bluesky_uri}")
                        
                        # Track with PostHog
                        if posthog.project_api_key:
                            try:
                                posthog.capture(
                                    distinct_id='system',
                                    event='daily_brief_posted_to_bluesky',
                                    properties={
                                        'brief_id': brief.id,
                                        'brief_date': brief.date.isoformat(),
                                        'bluesky_uri': bluesky_uri,
                                        'item_count': brief.item_count
                                    }
                                )
                            except Exception as e:
                                logger.warning(f"PostHog tracking error: {e}")
                except Exception as e:
                    logger.error(f"Error posting daily brief to Bluesky: {e}")
                    
            except Exception as e:
                logger.error(f"Error posting daily brief to social media: {e}", exc_info=True)


    # ==============================================================================
    # DAILY BRIEF JOBS
    # ==============================================================================

    @scheduler.scheduled_job('cron', hour=17, minute=0, id='generate_daily_brief')
    def generate_daily_brief_job():
        """
        Generate daily brief at 5:00pm UTC
        Auto-selects topics and creates draft brief
        Admin has 45-60 min to review before auto-publish
        
        Idempotency: Checks if brief already exists with ready/published status
        """
        with app.app_context():
            from app.brief.generator import generate_daily_brief
            from app.models import DailyBrief
            from datetime import date

            logger.info("Starting daily brief generation")

            try:
                # Idempotency check - skip if brief already exists
                existing = DailyBrief.query.filter_by(date=date.today()).first()
                if existing and existing.status in ('ready', 'published'):
                    logger.info(f"Brief already exists with status '{existing.status}', skipping generation")
                    return
                
                brief = generate_daily_brief(
                    brief_date=date.today(),
                    auto_publish=True  # Sets status to 'ready' not 'published'
                )

                if brief is None:
                    logger.warning("No topics available for today's brief - skipping generation")
                    return

                logger.info(f"Daily brief generated: {brief.title} ({brief.item_count} items)")

                # Log for admin notification (could trigger Slack webhook here)
                if brief.item_count < 3:
                    logger.warning(f"Brief only has {brief.item_count} items, below minimum!")

            except Exception as e:
                logger.error(f"Daily brief generation failed: {e}", exc_info=True)


    @scheduler.scheduled_job('interval', seconds=10, id='process_extraction_queue')
    def process_extraction_queue_job():
        """
        Process pending PDF/DOCX extraction jobs.
        Runs every 10 seconds to process uploads quickly.
        """
        with app.app_context():
            from app.briefing.ingestion.extraction_queue import process_extraction_queue
            try:
                process_extraction_queue()
            except Exception as e:
                logger.error(f"Extraction queue processing failed: {e}", exc_info=True)

    @scheduler.scheduled_job('interval', minutes=15, id='process_briefing_runs')
    def process_briefing_runs_job():
        """
        Process scheduled briefings and generate runs.
        Runs every 15 minutes to check for briefings that need generation.
        """
        with app.app_context():
            from app.briefing.generator import generate_brief_run_for_briefing
            from app.briefing.ingestion.source_ingester import SourceIngester
            from app.models import Briefing, BriefRun, InputSource
            from datetime import datetime, timedelta
            import pytz
            
            logger.info("Processing briefing runs")
            
            try:
                # Get all active briefings
                active_briefings = Briefing.query.filter_by(status='active').all()
                
                for briefing in active_briefings:
                    try:
                        # Import DST-safe timezone utilities
                        from app.briefing.timezone_utils import get_next_scheduled_time, get_weekly_scheduled_time

                        # Check if briefing needs a new run
                        if briefing.cadence == 'daily':
                            # Check if run exists for today (in briefing's timezone)
                            try:
                                tz = pytz.timezone(briefing.timezone)
                            except pytz.UnknownTimeZoneError:
                                tz = pytz.UTC

                            local_now = datetime.now(tz)
                            today_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
                            today_start_utc = today_start_local.astimezone(pytz.UTC).replace(tzinfo=None)

                            existing_run = BriefRun.query.filter_by(
                                briefing_id=briefing.id
                            ).filter(
                                BriefRun.scheduled_at >= today_start_utc
                            ).first()

                            if existing_run:
                                continue

                            # Calculate scheduled time with proper DST handling
                            scheduled_utc = get_next_scheduled_time(
                                timezone_str=briefing.timezone,
                                preferred_hour=briefing.preferred_send_hour,
                                preferred_minute=getattr(briefing, 'preferred_send_minute', 0)
                            )

                        elif briefing.cadence == 'weekly':
                            # Check if run exists this week (in briefing's timezone)
                            try:
                                tz = pytz.timezone(briefing.timezone)
                            except pytz.UnknownTimeZoneError:
                                tz = pytz.UTC

                            local_now = datetime.now(tz)
                            # Get start of week in local timezone (Monday)
                            days_since_monday = local_now.weekday()
                            week_start_local = (local_now - timedelta(days=days_since_monday)).replace(
                                hour=0, minute=0, second=0, microsecond=0
                            )
                            week_start_utc = week_start_local.astimezone(pytz.UTC).replace(tzinfo=None)

                            existing_run = BriefRun.query.filter_by(
                                briefing_id=briefing.id
                            ).filter(
                                BriefRun.scheduled_at >= week_start_utc
                            ).first()

                            if existing_run:
                                continue

                            # Calculate scheduled time with proper DST handling
                            # Default to Monday (weekday=0)
                            scheduled_utc = get_weekly_scheduled_time(
                                timezone_str=briefing.timezone,
                                preferred_hour=briefing.preferred_send_hour,
                                preferred_weekday=0,  # Monday
                                preferred_minute=getattr(briefing, 'preferred_send_minute', 0)
                            )
                        else:
                            continue
                        
                        # Ingest from sources first
                        ingester = SourceIngester()
                        for source_link in briefing.sources:
                            source = source_link.input_source
                            if source and source.enabled:
                                try:
                                    ingester.ingest_source(source)
                                except Exception as e:
                                    logger.error(f"Error ingesting source {source.id}: {e}")
                        
                        # Generate brief run
                        brief_run = generate_brief_run_for_briefing(
                            briefing.id,
                            scheduled_at=scheduled_utc
                        )
                        
                        if brief_run:
                            logger.info(f"Generated BriefRun {brief_run.id} for briefing {briefing.id}")
                        
                    except Exception as e:
                        logger.error(f"Error processing briefing {briefing.id}: {e}", exc_info=True)
                        continue
                        
            except Exception as e:
                logger.error(f"Error in briefing runs processor: {e}", exc_info=True)

    @scheduler.scheduled_job('interval', minutes=5, id='send_approved_brief_runs')
    def send_approved_brief_runs_job():
        """
        Send approved BriefRuns that are ready to send.
        Runs every 5 minutes to send briefs promptly after approval.
        
        IMPORTANT: Only sends in production to prevent duplicate emails from dev environment.
        """
        # Skip email sending in development environment to prevent duplicates
        if not _is_production_environment():
            logger.info("Skipping briefing sends - development environment")
            return
            
        with app.app_context():
            from app.briefing.email_client import send_brief_run_emails
            from app.models import BriefRun
            from datetime import datetime, timedelta
            
            logger.info("Checking for approved BriefRuns to send")
            
            try:
                # Find approved BriefRuns that haven't been sent yet
                # Only check runs scheduled for today or earlier
                cutoff = datetime.utcnow() - timedelta(hours=1)  # Allow 1 hour buffer
                
                approved_runs = BriefRun.query.filter(
                    BriefRun.status == 'approved',
                    BriefRun.sent_at.is_(None),
                    BriefRun.scheduled_at <= datetime.utcnow()
                ).limit(10).all()  # Process 10 at a time
                
                if not approved_runs:
                    return
                
                logger.info(f"Found {len(approved_runs)} approved BriefRuns to send")
                
                for brief_run in approved_runs:
                    try:
                        # Check if briefing is still active
                        if brief_run.briefing.status != 'active':
                            logger.info(f"Briefing {brief_run.briefing_id} is not active, skipping send")
                            continue
                        
                        # Check if briefing has recipients
                        if brief_run.briefing.recipient_count == 0:
                            logger.info(f"Briefing {brief_run.briefing_id} has no recipients, skipping send")
                            continue
                        
                        # Send emails
                        result = send_brief_run_emails(brief_run.id)
                        logger.info(f"Sent BriefRun {brief_run.id}: {result['sent']} sent, {result['failed']} failed")
                        
                    except Exception as e:
                        logger.error(f"Error sending BriefRun {brief_run.id}: {e}", exc_info=True)
                        continue
                        
            except Exception as e:
                logger.error(f"Error in approved BriefRuns sender: {e}", exc_info=True)

    @scheduler.scheduled_job('cron', hour=18, minute=0, id='auto_publish_brief')
    def auto_publish_daily_brief():
        """
        Auto-publish today's brief at 6:00pm UTC if still in 'ready' status
        This gives admin 1 hour review window (5pm-6pm)
        If admin already published/skipped, this does nothing
        """
        with app.app_context():
            from app import db
            from app.models import DailyBrief
            from datetime import date

            logger.info("Checking if brief should auto-publish")

            try:
                brief = DailyBrief.query.filter_by(
                    date=date.today(),
                    status='ready'
                ).first()

                if brief:
                    # Auto-publish
                    brief.status = 'published'
                    brief.published_at = datetime.utcnow()
                    db.session.commit()

                    logger.info(f"Auto-published brief: {brief.title}")
                else:
                    # Either already published, skipped, or doesn't exist
                    existing = DailyBrief.query.filter_by(date=date.today()).first()
                    if existing:
                        logger.info(f"Brief status is '{existing.status}', not auto-publishing")
                    else:
                        logger.warning("No brief exists for today!")

            except Exception as e:
                db.session.rollback()
                logger.error(f"Auto-publish failed: {e}", exc_info=True)


    @scheduler.scheduled_job('cron', minute=10, id='send_brief_emails')
    def send_brief_emails_hourly():
        """
        Send brief emails 10 minutes past each hour
        Offset from minute=0 to avoid race condition with auto_publish_brief at 18:00 UTC
        Checks which subscribers should receive at this UTC hour based on their timezone
        Example: At 18:10 UTC, sends to subscribers with preferred_hour=18:
        - UK users with preferred_hour=18 (6pm UK time)
        - EST users with preferred_hour=13 (1pm EST = 18:00 UTC)
        - PST users with preferred_hour=10 (10am PST = 18:00 UTC)
        
        IMPORTANT: Only sends in production to prevent duplicate emails from dev environment.
        """
        # Skip email sending in development environment to prevent duplicates
        if not _is_production_environment():
            logger.info("Skipping brief email send - development environment")
            return
            
        with app.app_context():
            from app.brief.email_client import BriefEmailScheduler

            current_hour = datetime.utcnow().hour
            logger.info(f"Starting brief email send for hour {current_hour} UTC")

            try:
                scheduler_obj = BriefEmailScheduler()
                results = scheduler_obj.send_todays_brief_hourly()

                if results:
                    logger.info(f"Brief emails sent: {results['sent']} successful, {results['failed']} failed")

                    if results['errors']:
                        for error in results['errors'][:5]:  # Log first 5 errors
                            logger.error(error)
                else:
                    logger.info("No brief to send or no subscribers at this hour")

            except Exception as e:
                logger.error(f"Brief email sending failed: {e}", exc_info=True)


    @scheduler.scheduled_job('cron', day=1, hour=2, id='update_allsides_ratings')
    def update_allsides_ratings_monthly():
        """
        Update AllSides political leaning ratings monthly
        Runs at 2am UTC on the 1st of each month

        Uses APScheduler's day parameter to ensure it only runs on day 1,
        rather than checking in the function body (which would fail if
        server is down on the 1st).
        """
        with app.app_context():
            from app.trending.allsides_seed import update_source_leanings

            logger.info("Updating AllSides ratings (monthly job)")

            try:
                results = update_source_leanings()
                logger.info(f"AllSides update complete: {results}")
            except Exception as e:
                logger.error(f"AllSides update failed: {e}", exc_info=True)


    @scheduler.scheduled_job('cron', day='*/2', hour=10, minute=30, id='update_social_engagement')
    def update_social_engagement():
        """
        Update engagement metrics for recent social media posts.
        Runs EVERY OTHER DAY at 10:30 UTC to conserve X API quota.
        
        X Free tier only allows 100 reads/month! 
        At 3 reads every 2 days = ~45/month, safely under limit.

        Used for A/B testing and performance measurement.
        """
        with app.app_context():
            from app.trending.engagement_tracker import update_recent_engagements

            logger.info("Updating social media engagement metrics (every 2 days, conserving X free tier quota)")

            try:
                # Only fetch 3 posts to conserve X free tier quota (100 reads/month)
                updated_count = update_recent_engagements(hours=72, limit=3)
                logger.info(f"Updated engagement for {updated_count} posts")
            except Exception as e:
                logger.error(f"Social engagement update failed: {e}", exc_info=True)


    @scheduler.scheduled_job('cron', hour=6, id='daily_diversity_check')
    def daily_diversity_check():
        """
        Run daily diversity check to monitor political balance.
        Runs at 6am UTC daily.
        Logs warnings/errors if discussions become imbalanced.
        Supports the mission: "Making Disagreement Useful Again"
        """
        with app.app_context():
            from app.trending.diversity_monitor import run_diversity_check

            try:
                results = run_diversity_check()
                status = results['stats']['balance_assessment']['status']
                ratio = results['stats']['discussions']['left_right_ratio']
                logger.info(f"Diversity check complete: {status} (L/R ratio: {ratio:.2f})")
            except Exception as e:
                logger.error(f"Diversity check failed: {e}", exc_info=True)


    logger.info("Scheduler initialized with jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"  - {job.id}: {job.trigger}")

    return scheduler


def start_scheduler():
    """
    Start the scheduler
    Should be called after app initialization
    """
    global scheduler
    
    if scheduler is None:
        logger.error("Scheduler not initialized. Call init_scheduler() first.")
        return
    
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")
    else:
        logger.warning("Scheduler already running")


def shutdown_scheduler():
    """
    Shutdown the scheduler gracefully
    """
    global scheduler
    
    if scheduler and scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler shut down")

