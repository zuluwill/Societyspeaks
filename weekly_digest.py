#!/usr/bin/env python3
"""
Weekly Discussion Digest Script
===============================

This script sends weekly digest emails to users who have opted in to receive them.
It should be run once per week, typically on Monday mornings.

Usage:
    python weekly_digest.py

The script will:
1. Find all users who have weekly_digest_enabled = True
2. Generate digest content for each user's discussion activity
3. Send digest emails using Resend
4. Log the results

This can be scheduled as a cron job or run manually as needed.
"""

import sys
import os

# Add the project root to Python path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User, Discussion, DiscussionParticipant, StatementVote, Response
from app.resend_client import send_weekly_discussion_digest
from datetime import datetime, timedelta
from sqlalchemy import func
import logging


def setup_logging():
    """Set up logging for the weekly digest script"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('weekly_digest.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )


def get_user_discussion_activity(user, days=7):
    """
    Get discussion activity for a user over the past N days.
    
    Returns:
        dict: Digest data including discussions with activity and user stats
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    base_url = os.environ.get('BASE_URL', 'https://societyspeaks.io')
    
    # Get discussions created by this user
    user_discussions = Discussion.query.filter_by(creator_id=user.id).all()
    
    discussions_with_activity = []
    
    for discussion in user_discussions:
        # Count new participants this week
        new_participants = DiscussionParticipant.query.filter(
            DiscussionParticipant.discussion_id == discussion.id,
            DiscussionParticipant.joined_at >= cutoff
        ).count()
        
        # Count new responses this week (from Response model)
        new_responses = Response.query.filter(
            Response.discussion_id == discussion.id,
            Response.created_at >= cutoff
        ).count()
        
        # Count new votes this week
        new_votes = StatementVote.query.join(
            Response, Response.statement_id == StatementVote.statement_id
        ).filter(
            Response.discussion_id == discussion.id,
            StatementVote.created_at >= cutoff
        ).count()
        
        # Only include if there's activity
        if new_participants > 0 or new_responses > 0 or new_votes > 0:
            discussions_with_activity.append({
                'title': discussion.title,
                'url': f"{base_url}/discussions/{discussion.id}/{discussion.slug}",
                'new_participants': new_participants,
                'new_responses': new_responses,
                'new_votes': new_votes
            })
    
    # Get user's own activity stats
    stats = {
        'discussions_created': Discussion.query.filter(
            Discussion.creator_id == user.id,
            Discussion.created_at >= cutoff
        ).count(),
        'votes_cast': StatementVote.query.filter(
            StatementVote.user_id == user.id,
            StatementVote.created_at >= cutoff
        ).count(),
        'responses_written': Response.query.filter(
            Response.user_id == user.id,
            Response.created_at >= cutoff
        ).count()
    }
    
    # Get trending discussions (most participants this week)
    trending = db.session.query(
        Discussion,
        func.count(DiscussionParticipant.id).label('participant_count')
    ).join(
        DiscussionParticipant,
        Discussion.id == DiscussionParticipant.discussion_id
    ).filter(
        DiscussionParticipant.joined_at >= cutoff
    ).group_by(
        Discussion.id
    ).order_by(
        func.count(DiscussionParticipant.id).desc()
    ).limit(5).all()
    
    trending_topics = []
    for discussion, participant_count in trending:
        trending_topics.append({
            'title': discussion.title,
            'url': f"{base_url}/discussions/{discussion.id}/{discussion.slug}",
            'participant_count': participant_count
        })
    
    return {
        'discussions_with_activity': discussions_with_activity,
        'trending_topics': trending_topics,
        'stats': stats,
        'has_activity': len(discussions_with_activity) > 0 or sum(stats.values()) > 0
    }


def send_weekly_digests():
    """Send weekly digest emails to all eligible users"""
    app = create_app()
    
    with app.app_context():
        setup_logging()
        logger = logging.getLogger(__name__)
        
        logger.info("Starting weekly digest process...")
        
        # Find all users who have weekly digest enabled
        eligible_users = User.query.filter_by(
            weekly_digest_enabled=True,
            email_notifications=True
        ).all()
        
        logger.info(f"Found {len(eligible_users)} users eligible for weekly digest")
        
        sent_count = 0
        error_count = 0
        skipped_count = 0
        
        for user in eligible_users:
            try:
                # Get user's discussion activity
                digest_data = get_user_discussion_activity(user)
                
                # Only send if there's something to report
                if not digest_data['has_activity']:
                    skipped_count += 1
                    logger.debug(f"Skipping {user.email} - no activity this week")
                    continue
                
                # Send the digest
                success = send_weekly_discussion_digest(user, digest_data)
                
                if success:
                    sent_count += 1
                    logger.info(f"Weekly digest sent to {user.email}")
                else:
                    error_count += 1
                    logger.error(f"Failed to send digest to {user.email}")
                
            except Exception as e:
                error_count += 1
                logger.error(f"Error processing digest for {user.email}: {str(e)}")
        
        logger.info(
            f"Weekly digest complete. "
            f"Sent: {sent_count}, Errors: {error_count}, "
            f"Skipped (no activity): {skipped_count}"
        )
        
        return {
            'total_eligible': len(eligible_users),
            'sent': sent_count,
            'errors': error_count,
            'skipped': skipped_count
        }


def main():
    """Main function to run the weekly digest script"""
    try:
        results = send_weekly_digests()
        print(f"\nWeekly Digest Summary:")
        print(f"Total eligible users: {results['total_eligible']}")
        print(f"Digests sent: {results['sent']}")
        print(f"Errors: {results['errors']}")
        print(f"Skipped (no activity): {results['skipped']}")
        
        # Exit with error code if there were errors
        if results['errors'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except Exception as e:
        print(f"Critical error in weekly digest script: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
