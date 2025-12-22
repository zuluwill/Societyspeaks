
from flask.cli import with_appcontext
from flask import current_app
import click
from app import db
from app.models import User, IndividualProfile, CompanyProfile, Discussion
from datetime import datetime, timedelta

@click.command('clean-spam')
@with_appcontext
def clean_spam():
    """Delete spam accounts based on patterns"""
    try:
        # Get spam patterns from config
        spam_patterns = current_app.config.get('SPAM_PATTERNS', ['bitcoin', 'btc', 'binance', 'crypto', 'telegra.ph'])
        
        spam_users = User.query.filter(
            db.or_(
                *[User.username.ilike(f'%{pattern}%') for pattern in spam_patterns],
                *[User.email.ilike(f'%{pattern}%') for pattern in spam_patterns]
            )
        ).all()

        total = len(spam_users)
        click.echo(f"Found {total} spam users to delete")

        for i, user in enumerate(spam_users, 1):
            click.echo(f"Processing {i}/{total}: {user.username} ({user.email})")
            # Delete associated data
            if user.individual_profile:
                db.session.delete(user.individual_profile)
                click.echo(f"- Deleted individual profile")
            if user.company_profile:
                db.session.delete(user.company_profile)
                click.echo(f"- Deleted company profile")
            disc_count = Discussion.query.filter_by(creator_id=user.id).delete()
            if disc_count:
                click.echo(f"- Deleted {disc_count} discussions")
            db.session.delete(user)
            if i % 10 == 0:  # Commit every 10 users to avoid timeouts
                db.session.commit()
                click.echo(f"Committed changes for batch {i//10}")

        db.session.commit()
        click.echo(f"Successfully deleted {len(spam_users)} spam accounts")
        
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error cleaning spam: {str(e)}")

@click.command('delete-spam-users')
@with_appcontext
def delete_spam_users():
    """Delete spam users (IDs 75-550) and their associated data"""
    try:
        # Get spam users
        spam_users = User.query.filter(User.id.between(75, 550)).all()
        
        for user in spam_users:
            # Delete associated profiles
            if user.individual_profile:
                db.session.delete(user.individual_profile)
            if user.company_profile:
                db.session.delete(user.company_profile)
                
            # Delete user's discussions
            Discussion.query.filter_by(creator_id=user.id).delete()
            
            # Delete the user
            db.session.delete(user)
            
        db.session.commit()
        click.echo(f"Successfully deleted {len(spam_users)} spam users and their data")
        
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error deleting spam users: {str(e)}")

import click
from flask.cli import with_appcontext
from app import db
from app.models import Discussion

def init_commands(app):
    app.cli.add_command(clean_spam)
    @app.cli.command('seed-db')
    def seed_database():
        """Seeds the database with initial data."""
        try:
            # Clear existing discussions (optional)
            # Discussion.query.delete()

            # Create the NHS discussion
            nhs_discussion = Discussion(
                polis_id='65bnczamhf',
                title='How should we improve the NHS?',
                description='Give specific details of what could be done and how? Give examples of what is not working with proposed solutions. How could we leverage technology whilst also ensuring privacy?',
                country='United Kingdom',
                topic='Healthcare',
                is_featured=True,
                participant_count=1
            )

            db.session.add(nhs_discussion)
            db.session.commit()
            click.echo('Database seeded successfully!')

        except Exception as e:
            db.session.rollback()
            click.echo(f'Error seeding database: {str(e)}')