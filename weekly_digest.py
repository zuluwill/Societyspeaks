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
3. Send digest emails using the existing Loops email infrastructure
4. Log the results

This can be scheduled as a cron job or run manually as needed.
"""

import sys
import os

# Add the project root to Python path so we can import from app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import User
from app.email_utils import send_weekly_discussion_digest
from datetime import datetime
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
        
        for user in eligible_users:
            try:
                # Send weekly digest
                digest_sent = send_weekly_discussion_digest(user)
                
                if digest_sent:
                    sent_count += 1
                    logger.info(f"Weekly digest sent successfully to {user.email}")
                else:
                    logger.info(f"No activity to report for {user.email} - no digest sent")
                
            except Exception as e:
                error_count += 1
                logger.error(f"Failed to send weekly digest to {user.email}: {str(e)}")
        
        logger.info(f"Weekly digest process completed. Sent: {sent_count}, Errors: {error_count}, No activity: {len(eligible_users) - sent_count - error_count}")
        
        return {
            'total_eligible': len(eligible_users),
            'sent': sent_count,
            'errors': error_count,
            'no_activity': len(eligible_users) - sent_count - error_count
        }

def main():
    """Main function to run the weekly digest script"""
    try:
        results = send_weekly_digests()
        print(f"\nWeekly Digest Summary:")
        print(f"Total eligible users: {results['total_eligible']}")
        print(f"Digests sent: {results['sent']}")
        print(f"Errors: {results['errors']}")
        print(f"Users with no activity: {results['no_activity']}")
        
        # Exit with error code if there were errors
        if results['errors'] > 0:
            sys.exit(1)
        else:
            sys.exit(0)
            
    except Exception as e:
        print(f"Critical error in weekly digest script: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()