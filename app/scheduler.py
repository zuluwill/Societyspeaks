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
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_MISSED
from datetime import datetime, timedelta
import logging
import threading
import atexit
import signal
import os
import requests

logger = logging.getLogger(__name__)


def _job_error_listener(event):
    """
    Handle job errors gracefully, especially during shutdown.
    Suppresses "cannot schedule new futures after shutdown" errors
    which are harmless and occur during Gunicorn worker restarts.
    """
    if event.exception:
        error_msg = str(event.exception)
        if "cannot schedule new futures after shutdown" in error_msg:
            # This is expected during worker restarts, don't log as error
            logger.debug(f"Job {event.job_id} skipped during shutdown (expected)")
        elif "interpreter shutdown" in error_msg:
            logger.debug(f"Job {event.job_id} skipped during interpreter shutdown (expected)")
        else:
            # Log other errors normally
            logger.error(f"Job {event.job_id} raised an exception: {event.exception}", 
                        exc_info=event.traceback)
scheduler = None
_shutdown_registered = False
_shutting_down = False


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


def _send_ops_alert(message: str) -> None:
    """
    Send critical scheduler alerts to Slack when configured.
    Falls back to logs if webhook is missing/invalid.
    """
    webhook_url = os.environ.get('SLACK_WEBHOOK_URL')
    if not webhook_url:
        return

    if not webhook_url.startswith(("https://hooks.slack.com/", "https://hooks.slack-gov.com/")):
        logger.warning("Invalid SLACK_WEBHOOK_URL format; skipping alert delivery")
        return

    try:
        requests.post(
            webhook_url,
            json={"text": f":warning: {message}"},
            timeout=8
        )
    except requests.RequestException as e:
        logger.warning(f"Failed to send scheduler alert to Slack: {e}")


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

    @scheduler.scheduled_job('cron', hour=4, id='reconcile_partner_billing')
    def reconcile_partner_billing():
        """
        Reconcile partner billing status with Stripe daily.
        """
        with app.app_context():
            from app.billing.service import reconcile_partner_subscriptions
            updated = reconcile_partner_subscriptions()
            logger.info(f"Partner billing reconciliation complete (updated={updated})")
    
    
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
                from app.resend_client import get_resend_client
                from app.models import DailyQuestion, DailyQuestionSubscriber
                
                logger.info("Background thread: Starting daily question email send (via Resend)")
                
                # Get today's question
                question = DailyQuestion.get_today()
                if not question:
                    logger.info("No daily question to send - none published for today")
                    return
                
                # Filter to only daily frequency subscribers
                daily_subscribers = DailyQuestionSubscriber.query.filter_by(
                    is_active=True,
                    email_frequency='daily'
                ).all()
                
                logger.info(f"Found {len(daily_subscribers)} daily frequency subscribers")
                
                if not daily_subscribers:
                    logger.info("No daily frequency subscribers to send to")
                    return
                
                # Send to daily subscribers using batch API
                client = get_resend_client()
                result = client.send_daily_question_batch(daily_subscribers, question)
                
                logger.info(
                    f"Background thread: Sent daily question to {result['sent']} subscribers, "
                    f"{result['failed']} failed"
                )
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


    # Weekly digest email sending
    _weekly_digest_in_progress = threading.Event()
    
    # Monthly digest email sending
    _monthly_digest_in_progress = threading.Event()

    def _run_weekly_digest_in_thread(app_instance):
        """Run weekly digest send in background thread with its own app context"""
        try:
            with app_instance.app_context():
                from datetime import datetime
                from app import db
                from app.models import DailyQuestionSubscriber
                from app.resend_client import ResendEmailClient
                from app.daily.auto_selection import select_questions_for_weekly_digest
                import pytz

                logger.info("Background thread: Starting weekly digest processing")

                # Get current UTC time
                utc_now = datetime.utcnow()

                # Get all active weekly subscribers
                weekly_subscribers = DailyQuestionSubscriber.query.filter_by(
                    is_active=True,
                    email_frequency='weekly'
                ).all()

                logger.info(f"Found {len(weekly_subscribers)} weekly subscribers to check")

                # Select questions for the digest (once, reuse for all subscribers)
                questions = select_questions_for_weekly_digest(days_back=7, count=5)

                if not questions:
                    logger.warning("No questions available for weekly digest")
                    return

                logger.info(f"Selected {len(questions)} questions for weekly digest")

                # Initialize Resend client
                client = ResendEmailClient()
                sent_count = 0
                skipped_count = 0

                for subscriber in weekly_subscribers:
                    try:
                        # Check if it's the right time for this subscriber
                        if not subscriber.should_receive_weekly_digest_now(utc_now):
                            continue

                        # Check if already sent this week
                        if subscriber.has_received_weekly_digest_this_week():
                            skipped_count += 1
                            continue

                        # Ensure subscriber has a magic token
                        if not subscriber.magic_token:
                            subscriber.generate_magic_token()
                            db.session.commit()

                        # Send the digest
                        success = client.send_weekly_questions_digest(subscriber, questions)

                        if success:
                            sent_count += 1
                            db.session.commit()
                            logger.debug(f"Sent weekly digest to {subscriber.email}")
                            
                            # Track with PostHog
                            try:
                                import posthog
                                if posthog and getattr(posthog, 'project_api_key', None):
                                    posthog.capture(
                                        distinct_id=subscriber.email,
                                        event='weekly_digest_sent',
                                        properties={
                                            'question_count': len(questions),
                                            'question_ids': [q.id for q in questions],
                                            'send_day': subscriber.preferred_send_day,
                                            'send_hour': subscriber.preferred_send_hour,
                                            'timezone': subscriber.timezone or 'UTC'
                                        }
                                    )
                            except Exception as e:
                                logger.warning(f"PostHog tracking error: {e}")
                        else:
                            logger.warning(f"Failed to send weekly digest to {subscriber.email}")

                    except Exception as e:
                        logger.error(f"Error sending weekly digest to {subscriber.email}: {e}")
                        db.session.rollback()

                logger.info(f"Weekly digest: sent to {sent_count} subscribers, skipped {skipped_count} (already sent)")

        except Exception as e:
            logger.error(f"Background thread: Weekly digest error: {e}", exc_info=True)
        finally:
            _weekly_digest_in_progress.clear()
            logger.info("Background thread: Weekly digest processing complete")

    def _run_monthly_digest_in_thread(app_instance):
        """Run monthly digest send in background thread with its own app context"""
        try:
            with app_instance.app_context():
                from datetime import datetime
                from app import db
                from app.models import DailyQuestionSubscriber
                from app.resend_client import ResendEmailClient
                from app.daily.auto_selection import select_questions_for_monthly_digest
                import pytz

                logger.info("Background thread: Starting monthly digest processing")

                # Get current UTC time
                utc_now = datetime.utcnow()

                # Get all active monthly subscribers
                monthly_subscribers = DailyQuestionSubscriber.query.filter_by(
                    is_active=True,
                    email_frequency='monthly'
                ).all()

                logger.info(f"Found {len(monthly_subscribers)} monthly subscribers to check")

                # Select questions for the digest (once, reuse for all subscribers)
                questions = select_questions_for_monthly_digest(days_back=30, count=10)

                if not questions:
                    logger.warning("No questions available for monthly digest")
                    return

                logger.info(f"Selected {len(questions)} questions for monthly digest")

                # Initialize Resend client
                client = ResendEmailClient()
                sent_count = 0
                skipped_count = 0

                for subscriber in monthly_subscribers:
                    try:
                        # Check if it's the right time for this subscriber
                        if not subscriber.should_receive_monthly_digest_now(utc_now):
                            continue

                        # Check if already sent this month
                        if subscriber.has_received_monthly_digest_this_month():
                            skipped_count += 1
                            continue

                        # Ensure subscriber has a magic token
                        if not subscriber.magic_token:
                            subscriber.generate_magic_token()
                            db.session.commit()

                        # Send the digest
                        success = client.send_monthly_questions_digest(subscriber, questions)

                        if success:
                            sent_count += 1
                            db.session.commit()
                            logger.debug(f"Sent monthly digest to {subscriber.email}")
                            
                            # Track with PostHog
                            try:
                                import posthog
                                if posthog and getattr(posthog, 'project_api_key', None):
                                    posthog.capture(
                                        distinct_id=subscriber.email,
                                        event='monthly_digest_sent',
                                        properties={
                                            'question_count': len(questions),
                                            'question_ids': [q.id for q in questions],
                                            'timezone': subscriber.timezone or 'UTC'
                                        }
                                    )
                            except Exception as e:
                                logger.warning(f"PostHog tracking error: {e}")
                        else:
                            logger.warning(f"Failed to send monthly digest to {subscriber.email}")

                    except Exception as e:
                        logger.error(f"Error sending monthly digest to {subscriber.email}: {e}")
                        db.session.rollback()

                logger.info(f"Monthly digest: sent to {sent_count} subscribers, skipped {skipped_count} (already sent)")

        except Exception as e:
            logger.error(f"Background thread: Monthly digest error: {e}", exc_info=True)
        finally:
            _monthly_digest_in_progress.clear()
            logger.info("Background thread: Monthly digest processing complete")

    @scheduler.scheduled_job('cron', minute=0, id='process_weekly_digest_sends')
    def process_weekly_digest_sends():
        """
        Process weekly digest sends. Runs every hour on the hour.

        Checks which subscribers should receive their weekly digest based on:
        - Their preferred send day (0-6, default Tuesday=1)
        - Their preferred send hour (0-23, default 9am)
        - Their timezone

        Example: If it's Tuesday 9am in Europe/London, send to all subscribers
        who have preferred_send_day=1, preferred_send_hour=9, timezone='Europe/London'

        IMPORTANT: Only sends in production to prevent duplicate emails from dev environment.
        """
        # Skip in development environment
        if not _is_production_environment():
            logger.debug("Skipping weekly digest processing - development environment")
            return

        if _weekly_digest_in_progress.is_set():
            logger.warning("Weekly digest processing already in progress, skipping")
            return

        _weekly_digest_in_progress.set()
        logger.info("Launching weekly digest processing in background thread")

        digest_thread = threading.Thread(
            target=_run_weekly_digest_in_thread,
            args=(app,),
            daemon=True,
            name="weekly-digest-sender"
        )
        digest_thread.start()
        logger.info("Weekly digest thread launched, scheduler continuing")

    @scheduler.scheduled_job('cron', minute=0, id='process_monthly_digest_sends')
    def process_monthly_digest_sends():
        """
        Process monthly digest sends. Runs every hour on the hour.

        Checks which subscribers should receive their monthly digest based on:
        - It's the 1st of the month
        - It's 9am in the subscriber's timezone
        - They haven't received it this month yet

        IMPORTANT: Only sends in production to prevent duplicate emails from dev environment.
        """
        # Skip in development environment
        if not _is_production_environment():
            logger.debug("Skipping monthly digest processing - development environment")
            return
        
        if _monthly_digest_in_progress.is_set():
            logger.warning("Monthly digest send already in progress, skipping")
            return
        
        _monthly_digest_in_progress.set()
        logger.info("Launching monthly digest send in background thread")
        
        email_thread = threading.Thread(
            target=_run_monthly_digest_in_thread,
            args=(app,),
            daemon=True,
            name="monthly-digest-sender"
        )
        email_thread.start()
        logger.info("Monthly digest thread launched, scheduler continuing")

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
                        if posthog and getattr(posthog, 'project_api_key', None):
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
                        if posthog and getattr(posthog, 'project_api_key', None):
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
                        if posthog and getattr(posthog, 'project_api_key', None):
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
                        if posthog and getattr(posthog, 'project_api_key', None):
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
                        if posthog and getattr(posthog, 'project_api_key', None):
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
                        if posthog and getattr(posthog, 'project_api_key', None):
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

    @scheduler.scheduled_job('cron', hour=16, minute=30, id='pre_brief_polymarket_matching')
    def pre_brief_polymarket_matching():
        """
        Run Polymarket matching 30 minutes before brief generation (4:30pm UTC).
        Ensures fresh matches are available when the brief generates at 5pm.
        """
        with app.app_context():
            from app.polymarket.matcher import market_matcher

            logger.info("Pre-brief Polymarket matching (runs 30min before brief generation)")
            try:
                stats = market_matcher.run_batch_matching(days_back=3, reprocess_existing=False)
                logger.info(f"Pre-brief matching complete: {stats}")
            except Exception as e:
                logger.error(f"Pre-brief Polymarket matching failed: {e}", exc_info=True)

    @scheduler.scheduled_job('cron', hour=17, minute=0, id='generate_daily_brief')
    def generate_daily_brief_job():
        """
        Generate daily brief at 5:00pm UTC.

        Uses the new sectioned format (lead, politics, economy, society, science,
        global roundup, week ahead, market pulse) with automatic fallback to
        legacy flat format if sectioned selection fails.
        
        Idempotency: Checks if brief already exists with ready/published status.
        """
        with app.app_context():
            from app.brief.generator import generate_daily_brief
            from app.models import DailyBrief
            from datetime import date

            logger.info("Starting daily brief generation (sectioned mode)")

            try:
                # Idempotency check
                existing = DailyBrief.query.filter_by(
                    date=date.today(), brief_type='daily'
                ).first()
                if existing and existing.status in ('ready', 'published'):
                    logger.info(f"Brief already exists with status '{existing.status}', skipping")
                    return
                
                brief = generate_daily_brief(
                    brief_date=date.today(),
                    auto_publish=True
                )

                if brief is None:
                    logger.warning("No topics available for today's brief - skipping")
                    return

                logger.info(f"Daily brief generated: {brief.title} ({brief.item_count} items)")

                if brief.item_count < 3:
                    logger.warning(f"Brief only has {brief.item_count} items, below minimum!")

            except Exception as e:
                logger.error(f"Daily brief generation failed: {e}", exc_info=True)

    @scheduler.scheduled_job('cron', day_of_week='sat', hour=17, minute=0, id='generate_weekly_brief')
    def generate_weekly_brief_job():
        """
        Generate weekly brief every Saturday at 5:00pm UTC.
        Summarises the past week's daily briefs into a curated digest.
        Delivered to weekly subscribers on their preferred day (default Sunday).
        """
        with app.app_context():
            from app.brief.weekly_generator import generate_weekly_brief
            from datetime import date, timedelta

            logger.info("Starting weekly brief generation")

            try:
                # Generate for the week ending tomorrow (Sunday)
                tomorrow = date.today() + timedelta(days=1)
                brief = generate_weekly_brief(
                    week_end_date=tomorrow,
                    auto_publish=True
                )

                if brief is None:
                    logger.warning("Weekly brief generation returned None")
                    return

                logger.info(f"Weekly brief generated: {brief.title} ({brief.item_count} items)")

            except Exception as e:
                logger.error(f"Weekly brief generation failed: {e}", exc_info=True)


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

    @scheduler.scheduled_job('interval', seconds=3, id='process_brief_generation_queue')
    def process_brief_generation_queue_job():
        """
        Process pending brief generation jobs.
        Runs every 3 seconds for responsive user experience.
        """
        with app.app_context():
            from app.briefing.jobs import process_pending_jobs
            try:
                process_pending_jobs()
            except Exception as e:
                logger.error(f"Brief generation queue processing failed: {e}", exc_info=True)

    @scheduler.scheduled_job('interval', seconds=10, id='process_audio_generation_queue')
    def process_audio_generation_queue_job():
        """
        Audio generation is disabled (feature was deprecated as not worthwhile).
        Job is kept as a no-op so scheduler config is unchanged; no processing runs.
        """
        return

    @scheduler.scheduled_job('interval', minutes=15, id='process_briefing_runs')
    def process_briefing_runs_job():
        """
        Process scheduled briefings and generate runs.
        Runs every 15 minutes to check for briefings that need generation.
        
        For each active briefing:
        1. Verify owner has active subscription (admin or paid)
        2. Check if a run already exists for this period (daily/weekly)
        3. Ingest content from configured sources
        4. Generate the brief run content
        
        IMPORTANT: Only runs in production to prevent duplicate generation from dev environment.
        """
        if not _is_production_environment():
            logger.debug("Skipping briefing runs processing - development environment")
            return
            
        with app.app_context():
            from app.briefing.generator import generate_brief_run_for_briefing
            from app.briefing.ingestion.source_ingester import SourceIngester
            from app.models import Briefing, BriefRun, InputSource
            from app import db
            from datetime import datetime, timedelta
            import pytz
            
            logger.info("Processing briefing runs")
            
            try:
                active_briefings = Briefing.query.filter_by(status='active').all()
                
                for briefing in active_briefings:
                    try:
                        from app.billing.service import get_active_subscription
                        from app.models import User, Subscription
                        
                        has_active_subscription = False
                        
                        if briefing.owner_type == 'user':
                            user = db.session.get(User, briefing.owner_id)
                            if user:
                                if user.is_admin:
                                    has_active_subscription = True
                                else:
                                    sub = get_active_subscription(user)
                                    has_active_subscription = sub is not None
                        elif briefing.owner_type == 'org':
                            sub = Subscription.query.filter(
                                Subscription.org_id == briefing.owner_id,
                                Subscription.status.in_(['trialing', 'active'])
                            ).first()
                            has_active_subscription = sub is not None
                        
                        if not has_active_subscription:
                            logger.info(
                                f"Skipping briefing {briefing.id} - owner has no active subscription "
                                f"(owner_type={briefing.owner_type}, owner_id={briefing.owner_id})"
                            )
                            continue

                        from app.briefing.timezone_utils import get_next_scheduled_time, get_weekly_scheduled_time

                        if briefing.cadence == 'daily':
                            try:
                                tz = pytz.timezone(briefing.timezone)
                            except pytz.UnknownTimeZoneError:
                                logger.warning(f"Unknown timezone '{briefing.timezone}' for briefing {briefing.id}, using UTC")
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

                            preferred_minute = getattr(briefing, 'preferred_send_minute', 0)
                            
                            today_target_naive = local_now.replace(
                                hour=briefing.preferred_send_hour,
                                minute=preferred_minute,
                                second=0, microsecond=0
                            ).replace(tzinfo=None)
                            from app.briefing.timezone_utils import safe_localize
                            today_target_local = safe_localize(tz, today_target_naive)
                            
                            if local_now > today_target_local:
                                scheduled_utc = today_target_local.astimezone(pytz.UTC).replace(tzinfo=None)
                                logger.info(
                                    f"Briefing {briefing.id}: preferred time {briefing.preferred_send_hour}:{preferred_minute:02d} "
                                    f"already passed in {briefing.timezone}, generating catch-up run "
                                    f"(scheduled_at={scheduled_utc})"
                                )
                            else:
                                scheduled_utc = get_next_scheduled_time(
                                    timezone_str=briefing.timezone,
                                    preferred_hour=briefing.preferred_send_hour,
                                    preferred_minute=preferred_minute
                                )

                        elif briefing.cadence == 'weekly':
                            try:
                                tz = pytz.timezone(briefing.timezone)
                            except pytz.UnknownTimeZoneError:
                                logger.warning(f"Unknown timezone '{briefing.timezone}' for briefing {briefing.id}, using UTC")
                                tz = pytz.UTC

                            local_now = datetime.now(tz)
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

                            scheduled_utc = get_weekly_scheduled_time(
                                timezone_str=briefing.timezone,
                                preferred_hour=briefing.preferred_send_hour,
                                preferred_weekday=0,
                                preferred_minute=getattr(briefing, 'preferred_send_minute', 0)
                            )
                        else:
                            logger.warning(f"Unknown cadence '{briefing.cadence}' for briefing {briefing.id}, skipping")
                            continue
                        
                        ingester = SourceIngester()
                        ingestion_errors = 0
                        for source_link in briefing.sources:
                            source = source_link.input_source
                            if source and source.enabled:
                                try:
                                    ingester.ingest_source(source)
                                except Exception as e:
                                    ingestion_errors += 1
                                    logger.error(f"Error ingesting source {source.id} for briefing {briefing.id}: {e}")
                        
                        if ingestion_errors > 0:
                            logger.warning(
                                f"Briefing {briefing.id}: {ingestion_errors} source ingestion errors, "
                                f"proceeding with available content"
                            )
                        
                        brief_run = generate_brief_run_for_briefing(
                            briefing.id,
                            scheduled_at=scheduled_utc
                        )
                        
                        if brief_run:
                            logger.info(f"Generated BriefRun {brief_run.id} for briefing {briefing.id} (scheduled: {scheduled_utc})")
                        else:
                            logger.warning(f"No BriefRun generated for briefing {briefing.id} - generator returned None")
                        
                    except Exception as e:
                        logger.error(f"Error processing briefing {briefing.id}: {e}", exc_info=True)
                        db.session.rollback()
                        continue
                        
            except Exception as e:
                logger.error(f"Error in briefing runs processor: {e}", exc_info=True)

    @scheduler.scheduled_job('interval', minutes=5, id='send_approved_brief_runs')
    def send_approved_brief_runs_job():
        """
        Send approved BriefRuns that are ready to send.
        Runs every 5 minutes to send briefs promptly after approval.
        
        Pipeline:
        1. Expire stale runs (too old to send)
        2. Clear unsendable runs (inactive briefings, no recipients)
        3. Fail runs that exceeded max send attempts
        4. Send eligible approved runs
        5. Recover stuck 'sending' runs
        6. Clean up stale email claims
        
        IMPORTANT: Only sends in production to prevent duplicate emails from dev environment.
        """
        if not _is_production_environment():
            logger.info("Skipping briefing sends - development environment")
            return
            
        with app.app_context():
            from app.briefing.email_client import send_brief_run_emails
            from app.models import BriefRun, BriefRecipient, Briefing, BriefEmailSend
            from app import db
            from sqlalchemy import update, or_, func
            from datetime import datetime, timedelta
            
            now = datetime.utcnow()
            MAX_BRIEFRUN_SEND_ATTEMPTS = 5
            STALE_DAILY_HOURS = 20
            STALE_WEEKLY_HOURS = 48
            STUCK_SENDING_MINUTES = 15
            
            # === Phase 1: Expire stale runs ===
            # Runs older than their staleness window should not be sent (confusing for users)
            try:
                daily_cutoff = now - timedelta(hours=STALE_DAILY_HOURS)
                weekly_cutoff = now - timedelta(hours=STALE_WEEKLY_HOURS)
                
                stale_expired = db.session.execute(
                    db.text("""
                        UPDATE brief_run br SET status = 'failed', sent_at = :now
                        WHERE br.status = 'approved' AND br.sent_at IS NULL
                        AND br.scheduled_at <= :now
                        AND (
                            (EXISTS (SELECT 1 FROM briefing b WHERE b.id = br.briefing_id AND b.cadence = 'daily')
                             AND br.scheduled_at < :daily_cutoff)
                            OR
                            (EXISTS (SELECT 1 FROM briefing b WHERE b.id = br.briefing_id AND b.cadence = 'weekly')
                             AND br.scheduled_at < :weekly_cutoff)
                        )
                    """),
                    {'now': now, 'daily_cutoff': daily_cutoff, 'weekly_cutoff': weekly_cutoff}
                )
                db.session.commit()
                if stale_expired.rowcount > 0:
                    logger.warning(
                        f"Expired {stale_expired.rowcount} stale BriefRuns "
                        f"(daily>{STALE_DAILY_HOURS}h, weekly>{STALE_WEEKLY_HOURS}h)"
                    )
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error expiring stale runs: {e}", exc_info=True)
            
            # === Phase 2: Clear unsendable runs ===
            # Runs for inactive briefings or briefings with no active recipients
            try:
                inactive_cleared = db.session.execute(
                    db.text("""
                        UPDATE brief_run SET status = 'failed', sent_at = :now
                        WHERE status = 'approved' AND sent_at IS NULL
                        AND scheduled_at <= :now
                        AND briefing_id IN (
                            SELECT id FROM briefing WHERE status != 'active'
                        )
                    """),
                    {'now': now}
                )
                if inactive_cleared.rowcount > 0:
                    logger.info(f"Cleared {inactive_cleared.rowcount} runs for inactive briefings")
                
                no_recipient_cleared = db.session.execute(
                    db.text("""
                        UPDATE brief_run SET status = 'sent', sent_at = :now
                        WHERE status = 'approved' AND sent_at IS NULL
                        AND scheduled_at <= :now
                        AND briefing_id NOT IN (
                            SELECT DISTINCT briefing_id FROM brief_recipient WHERE status = 'active'
                        )
                    """),
                    {'now': now}
                )
                if no_recipient_cleared.rowcount > 0:
                    logger.info(f"Cleared {no_recipient_cleared.rowcount} runs for briefings with no active recipients")
                
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error clearing unsendable runs: {e}", exc_info=True)
            
            # === Phase 3: Fail runs that exceeded max send attempts ===
            try:
                max_attempt_failed = db.session.execute(
                    db.text("""
                        UPDATE brief_run SET status = 'failed', sent_at = :now
                        WHERE status = 'approved' AND sent_at IS NULL
                        AND COALESCE(send_attempts, 0) >= :max_attempts
                    """),
                    {'now': now, 'max_attempts': MAX_BRIEFRUN_SEND_ATTEMPTS}
                )
                db.session.commit()
                if max_attempt_failed.rowcount > 0:
                    alert_message = (
                        f"ALERT: Failed {max_attempt_failed.rowcount} BriefRuns that exceeded "
                        f"{MAX_BRIEFRUN_SEND_ATTEMPTS} send attempts. Manual investigation required."
                    )
                    logger.error(alert_message)
                    _send_ops_alert(alert_message)
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error failing max-attempt runs: {e}", exc_info=True)
            
            # === Phase 4: Send eligible approved runs ===
            try:
                approved_runs = BriefRun.query.filter(
                    BriefRun.status == 'approved',
                    BriefRun.sent_at.is_(None),
                    BriefRun.scheduled_at <= now,
                    func.coalesce(BriefRun.send_attempts, 0) < MAX_BRIEFRUN_SEND_ATTEMPTS
                ).order_by(BriefRun.scheduled_at.asc()).limit(20).all()
                
                if approved_runs:
                    logger.info(f"Found {len(approved_runs)} approved BriefRuns to send")
                    
                    for brief_run in approved_runs:
                        try:
                            result = send_brief_run_emails(brief_run.id)
                            logger.info(
                                f"BriefRun {brief_run.id}: sent={result.get('sent', 0)}, "
                                f"failed={result.get('failed', 0)}, "
                                f"method={result.get('method', 'unknown')}"
                            )
                        except Exception as e:
                            logger.error(f"Error sending BriefRun {brief_run.id}: {e}", exc_info=True)
                            db.session.rollback()
                            continue
                        
            except Exception as e:
                logger.error(f"Error in approved BriefRuns sender: {e}", exc_info=True)
            
            # === Phase 5: Recover stuck 'sending' runs ===
            # Reset runs stuck in 'sending' for too long back to 'approved' for retry
            # (only if under max attempts - otherwise fail them)
            try:
                stuck_cutoff = now - timedelta(minutes=STUCK_SENDING_MINUTES)
                
                stuck_retry = db.session.execute(
                    update(BriefRun)
                    .where(BriefRun.status == 'sending')
                    .where(BriefRun.sent_at == None)
                    .where(func.coalesce(BriefRun.send_attempts, 0) < MAX_BRIEFRUN_SEND_ATTEMPTS)
                    .where(
                        or_(
                            BriefRun.claimed_at < stuck_cutoff,
                            (BriefRun.claimed_at == None) & (BriefRun.scheduled_at < stuck_cutoff)
                        )
                    )
                    .values(status='approved', claimed_at=None)
                )
                db.session.commit()
                if stuck_retry.rowcount > 0:
                    logger.warning(f"Reset {stuck_retry.rowcount} stuck 'sending' BriefRuns back to 'approved' for retry")
                
                stuck_failed = db.session.execute(
                    update(BriefRun)
                    .where(BriefRun.status == 'sending')
                    .where(BriefRun.sent_at == None)
                    .where(func.coalesce(BriefRun.send_attempts, 0) >= MAX_BRIEFRUN_SEND_ATTEMPTS)
                    .where(
                        or_(
                            BriefRun.claimed_at < stuck_cutoff,
                            (BriefRun.claimed_at == None) & (BriefRun.scheduled_at < stuck_cutoff)
                        )
                    )
                    .values(status='failed', sent_at=now)
                )
                db.session.commit()
                if stuck_failed.rowcount > 0:
                    alert_message = (
                        f"ALERT: Failed {stuck_failed.rowcount} stuck 'sending' BriefRuns "
                        f"that exceeded {MAX_BRIEFRUN_SEND_ATTEMPTS} attempts"
                    )
                    logger.error(alert_message)
                    _send_ops_alert(alert_message)
                    
            except Exception as e:
                db.session.rollback()
                logger.error(f"Error recovering stuck sends: {e}", exc_info=True)
            
            # === Phase 6: Clean up stale email claims ===
            try:
                stale_claim_cutoff = now - timedelta(minutes=STUCK_SENDING_MINUTES)

                stale_result = db.session.execute(
                    db.text("""
                        UPDATE brief_email_send
                        SET status = 'failed',
                            failure_reason = 'Stale claim - scheduler cleanup',
                            attempt_count = attempt_count + 1
                        WHERE status = 'claimed'
                        AND claimed_at < :stale_cutoff
                    """),
                    {'stale_cutoff': stale_claim_cutoff}
                )
                
                max_attempts = BriefEmailSend.MAX_SEND_ATTEMPTS
                permanent_result = db.session.execute(
                    db.text("""
                        UPDATE brief_email_send
                        SET status = 'permanently_failed'
                        WHERE status = 'failed'
                        AND attempt_count >= :max_attempts
                    """),
                    {'max_attempts': max_attempts}
                )
                db.session.commit()

                if stale_result.rowcount > 0:
                    logger.warning(f"Marked {stale_result.rowcount} stale email claims as failed for retry")
                if permanent_result.rowcount > 0:
                    logger.warning(
                        f"Marked {permanent_result.rowcount} email sends as permanently_failed "
                        f"(exceeded {max_attempts} attempts)"
                    )

                permanent_failures_24h = BriefEmailSend.query.filter(
                    BriefEmailSend.status == 'permanently_failed',
                    BriefEmailSend.claimed_at > now - timedelta(hours=24)
                ).count()
                if permanent_failures_24h > 0:
                    alert_message = (
                        f"ALERT: {permanent_failures_24h} emails permanently failed in last 24h. "
                        f"Manual investigation required. Check brief_email_send table for details."
                    )
                    logger.error(alert_message)
                    _send_ops_alert(alert_message)

            except Exception as e:
                db.session.rollback()
                logger.error(f"Error cleaning up stale email claims: {e}", exc_info=True)

    @scheduler.scheduled_job('cron', hour=18, minute=0, id='auto_publish_brief')
    def auto_publish_daily_brief():
        """
        Auto-publish today's briefs at 6:00pm UTC if still in 'ready' status.
        Handles both daily and weekly briefs. Gives admin 1 hour review window (5pm-6pm).
        """
        with app.app_context():
            from app import db
            from app.models import DailyBrief
            from datetime import date

            logger.info("Checking if briefs should auto-publish")

            try:
                # Auto-publish any 'ready' briefs for today (daily or weekly)
                ready_briefs = DailyBrief.query.filter_by(
                    date=date.today(),
                    status='ready'
                ).all()

                if ready_briefs:
                    for brief in ready_briefs:
                        brief.status = 'published'
                        brief.published_at = datetime.utcnow()
                        logger.info(f"Auto-published {brief.brief_type} brief: {brief.title}")

                    db.session.commit()
                else:
                    existing = DailyBrief.query.filter_by(date=date.today()).all()
                    for b in existing:
                        logger.info(f"Brief ({b.brief_type}) status is '{b.status}', not auto-publishing")
                    if not existing:
                        logger.warning("No briefs exist for today!")

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

                # Send daily briefs to daily subscribers
                daily_results = scheduler_obj.send_todays_brief_hourly()
                if daily_results:
                    logger.info(f"Daily brief emails: {daily_results['sent']} sent, {daily_results['failed']} failed")
                    if daily_results['errors']:
                        for error in daily_results['errors'][:5]:
                            logger.error(error)
                else:
                    logger.info("No daily brief to send or no daily subscribers at this hour")

                # Send weekly briefs to weekly subscribers (checks preferred day internally)
                weekly_results = scheduler_obj.send_weekly_brief_hourly()
                if weekly_results and weekly_results['sent'] > 0:
                    logger.info(f"Weekly brief emails: {weekly_results['sent']} sent, {weekly_results['failed']} failed")

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


    # ==============================================================================
    # POLYMARKET INTEGRATION JOBS
    # ==============================================================================

    @scheduler.scheduled_job('interval', hours=2, id='polymarket_sync')
    def polymarket_sync_job():
        """
        Full sync of Polymarket markets.
        Runs every 2 hours to discover new markets and update existing ones.
        Generates embeddings for new high-quality markets.

        Graceful degradation: If API fails, job completes without error.
        """
        with app.app_context():
            from app.polymarket.service import polymarket_service

            logger.info("Starting Polymarket market sync")
            try:
                stats = polymarket_service.sync_all_markets()
                logger.info(f"Polymarket sync complete: created={stats['created']}, "
                           f"updated={stats['updated']}, deactivated={stats['deactivated']}, "
                           f"embeddings={stats.get('embeddings_generated', 0)}, errors={stats['errors']}")
            except Exception as e:
                logger.error(f"Polymarket sync failed: {e}", exc_info=True)


    @scheduler.scheduled_job('interval', minutes=5, id='polymarket_price_refresh')
    def polymarket_price_refresh_job():
        """
        Refresh prices for tracked Polymarket markets.
        Runs every 5 minutes for timely price updates.

        Prioritizes markets that are matched to active topics or daily questions.

        Graceful degradation: If API fails, job completes without error.
        """
        with app.app_context():
            from app.polymarket.service import polymarket_service
            from app.models import TopicMarketMatch, DailyQuestion

            logger.info("Starting Polymarket price refresh")
            try:
                # Get priority market IDs (markets linked to topics or questions)
                topic_market_ids = [m.market_id for m in TopicMarketMatch.query.all()]
                question_market_ids = [q.polymarket_market_id for q in
                                       DailyQuestion.query.filter(
                                           DailyQuestion.polymarket_market_id.isnot(None)
                                       ).all()]
                priority_ids = list(set(topic_market_ids + question_market_ids))

                stats = polymarket_service.refresh_prices(priority_market_ids=priority_ids)
                logger.info(f"Polymarket price refresh complete: updated={stats['updated']}, "
                           f"errors={stats['errors']}")
            except Exception as e:
                logger.error(f"Polymarket price refresh failed: {e}", exc_info=True)


    @scheduler.scheduled_job('interval', minutes=30, id='polymarket_matching')
    def polymarket_matching_job():
        """
        Match trending topics to Polymarket markets.
        Runs every 30 minutes to find relevant markets for new topics.

        Only processes topics without existing matches (idempotent).

        Graceful degradation: If matching fails, job completes without error.
        """
        with app.app_context():
            from app.polymarket.matcher import market_matcher

            logger.info("Starting Polymarket topic matching")
            try:
                stats = market_matcher.run_batch_matching(days_back=7, reprocess_existing=False)
                logger.info(f"Polymarket matching complete: processed={stats['processed']}, "
                           f"matched={stats['matched']}, skipped={stats['skipped']}, "
                           f"errors={stats['errors']}")
            except Exception as e:
                logger.error(f"Polymarket matching failed: {e}", exc_info=True)


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
        _register_shutdown_handlers()
        # Add error listener to handle shutdown errors gracefully
        scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)
        scheduler.start()
        logger.info("Scheduler started with shutdown handlers and error listener")
    else:
        logger.warning("Scheduler already running")


def shutdown_scheduler(wait: bool = False):
    """
    Shutdown the scheduler gracefully.
    
    Args:
        wait: If True, wait for running jobs to complete. 
              Default False to avoid blocking during worker shutdown.
    """
    global scheduler, _shutting_down
    
    _shutting_down = True
    
    if scheduler:
        try:
            if scheduler.running:
                # Remove all pending jobs first to prevent "cannot schedule new futures" errors
                try:
                    for job in scheduler.get_jobs():
                        job.remove()
                except Exception:
                    pass
                
                scheduler.shutdown(wait=wait)
                logger.info("Scheduler shut down gracefully")
        except (RuntimeError, Exception) as e:
            # Ignore "cannot schedule new futures after shutdown" errors
            if "cannot schedule new futures" not in str(e):
                logger.warning(f"Error during scheduler shutdown (may already be stopped): {e}")


def _register_shutdown_handlers():
    """Register atexit and signal handlers to ensure clean shutdown."""
    global _shutdown_registered
    
    if _shutdown_registered:
        return
    
    def _shutdown_handler(*args):
        shutdown_scheduler(wait=False)
    
    atexit.register(_shutdown_handler)
    
    try:
        signal.signal(signal.SIGTERM, _shutdown_handler)
        signal.signal(signal.SIGINT, _shutdown_handler)
    except (ValueError, OSError):
        pass
    
    _shutdown_registered = True
    logger.debug("Scheduler shutdown handlers registered")

