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
        """
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


    @scheduler.scheduled_job('cron', minute=0, id='send_brief_emails')
    def send_brief_emails_hourly():
        """
        Send brief emails every hour on the hour
        Checks which subscribers should receive at this UTC hour based on their timezone
        Example: At 18:00 UTC, sends to:
        - UK users with preferred_hour=18 (6pm UK time)
        - EST users with preferred_hour=13 (1pm EST = 18:00 UTC)
        - PST users with preferred_hour=10 (10am PST = 18:00 UTC)
        """
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

