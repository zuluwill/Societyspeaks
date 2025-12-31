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
    
    scheduler = BackgroundScheduler()
    
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
        Clean up old consensus analyses
        Keep only the 10 most recent for each discussion
        Runs daily at 3 AM
        """
        with app.app_context():
            from app import db
            from app.models import ConsensusAnalysis, Discussion
            
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
    
    
    @scheduler.scheduled_job('interval', hours=1, id='trending_topics_pipeline')
    def run_trending_topics_pipeline():
        """
        Fetch news and process trending topics
        Runs every hour
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

