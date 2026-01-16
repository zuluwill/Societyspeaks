
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
from app.models import Discussion, DailyBrief, DailyBriefSubscriber, TrendingTopic
from app.brief.generator import generate_daily_brief
from app.brief.topic_selector import select_todays_topics
from app.brief.email_client import send_brief_to_subscriber
from app.brief.underreported import get_underreported_stories
from app.trending.allsides_seed import update_source_leanings
from datetime import date as date_type

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

    # ==================================================================================
    # DAILY BRIEF COMMANDS
    # ==================================================================================

    @app.cli.command('generate-brief')
    @click.option('--date', default=None, help='Date in YYYY-MM-DD format (default: today)')
    @click.option('--force', is_flag=True, help='Force regenerate even if exists')
    def generate_brief_cmd(date, force):
        """Generate daily brief for a date"""
        try:
            if date:
                brief_date = datetime.strptime(date, '%Y-%m-%d').date()
            else:
                brief_date = date_type.today()

            # Check if exists
            existing = DailyBrief.query.filter_by(date=brief_date).first()
            if existing and not force:
                click.echo(f"Brief already exists for {brief_date} (status: {existing.status})")
                click.echo("Use --force to regenerate")
                return

            click.echo(f"Generating brief for {brief_date}...")
            brief = generate_daily_brief(brief_date, auto_publish=True)

            click.echo(f"✓ Brief generated: {brief.title}")
            click.echo(f"  Items: {brief.item_count}")
            click.echo(f"  Status: {brief.status}")

        except Exception as e:
            click.echo(f"Error generating brief: {str(e)}", err=True)

    @app.cli.command('test-brief-email')
    @click.argument('email')
    @click.option('--date', default=None, help='Date in YYYY-MM-DD format (default: today)')
    def test_brief_email_cmd(email, date):
        """Send test brief email to an address"""
        try:
            click.echo(f"Sending test email to {email}...")

            # Ensure subscriber exists
            subscriber = DailyBriefSubscriber.query.filter_by(email=email).first()
            if not subscriber:
                click.echo(f"Creating temp subscriber for {email}")
                subscriber = DailyBriefSubscriber(
                    email=email,
                    timezone='UTC',
                    preferred_send_hour=18
                )
                subscriber.generate_magic_token()
                subscriber.start_trial()
                db.session.add(subscriber)
                db.session.commit()

            success = send_brief_to_subscriber(email, date)

            if success:
                click.echo(f"✓ Email sent to {email}")
            else:
                click.echo(f"✗ Failed to send email", err=True)

        except Exception as e:
            click.echo(f"Error sending test email: {str(e)}", err=True)

    @app.cli.command('seed-allsides')
    @click.option('--update', is_flag=True, help='Update existing ratings')
    def seed_allsides_cmd(update):
        """Seed AllSides political leaning ratings"""
        try:
            click.echo("Updating AllSides ratings...")
            results = update_source_leanings()

            click.echo(f"✓ Updated: {results['updated']} sources")
            click.echo(f"  Skipped: {results['skipped']} (already rated)")
            if results['not_found']:
                click.echo(f"  Not found: {len(results['not_found'])} sources")
                for name in results['not_found']:
                    click.echo(f"    - {name}")

        except Exception as e:
            click.echo(f"Error seeding AllSides: {str(e)}", err=True)

    @app.cli.command('test-topic-selection')
    @click.option('--limit', default=5, help='Number of topics to select')
    def test_topic_selection_cmd(limit):
        """Test topic selection algorithm (no generation)"""
        try:
            click.echo(f"Selecting up to {limit} topics...")
            topics = select_todays_topics(limit=limit)

            if not topics:
                click.echo("No topics selected")
                return

            click.echo(f"\n✓ Selected {len(topics)} topics:\n")

            for i, topic in enumerate(topics, 1):
                click.echo(f"{i}. {topic.title}")
                click.echo(f"   Civic: {topic.civic_score:.2f} | Quality: {topic.quality_score:.2f} | Sources: {topic.source_count}")
                click.echo(f"   Category: {topic.primary_topic} | Scope: {getattr(topic, 'geographic_scope', 'N/A')}")
                click.echo()

        except Exception as e:
            click.echo(f"Error testing selection: {str(e)}", err=True)

    @app.cli.command('test-lens-check')
    @click.option('--date', default=None, help='Date in YYYY-MM-DD format (default: today)')
    def test_lens_check_cmd(date):
        """Test lens check generation (Same Story, Different Lens)"""
        from app.brief.lens_check import generate_lens_check
        import json
        
        try:
            if date:
                check_date = datetime.strptime(date, '%Y-%m-%d').date()
            else:
                check_date = date_type.today()
            
            click.echo(f"Generating lens check for {check_date}...")
            click.echo("This finds stories with cross-spectrum coverage and analyzes framing differences.\n")
            
            result = generate_lens_check(check_date)
            
            if not result:
                click.echo("✗ No story met lens check criteria")
                click.echo("  Criteria: At least 2 sources per perspective (left/centre/right)")
                click.echo("  Tip: Run 'flask test-topic-selection' to see available topics")
                return
            
            click.echo(f"✓ Lens check generated!\n")
            click.echo(f"📰 Story: {result.get('story_summary', 'N/A')}")
            click.echo(f"   Topic ID: {result.get('topic_id')}")
            click.echo()
            
            # Selection criteria
            criteria = result.get('selection_criteria', {})
            click.echo(f"📊 Selection Criteria:")
            click.echo(f"   Total sources: {criteria.get('total_sources', 'N/A')}")
            click.echo(f"   Left: {criteria.get('left_sources', 0)} | Centre: {criteria.get('centre_sources', 0)} | Right: {criteria.get('right_sources', 0)}")
            click.echo(f"   Balance score: {criteria.get('coverage_balance_score', 'N/A')}")
            click.echo()
            
            # Perspectives
            for perspective in ['left', 'centre', 'right']:
                data = result.get('perspectives', {}).get(perspective, {})
                if data:
                    click.echo(f"{'🔵' if perspective == 'left' else '🟣' if perspective == 'centre' else '🔴'} {perspective.upper()} ({data.get('source_count', 0)} sources)")
                    if data.get('emphasis'):
                        click.echo(f"   Emphasis: {data['emphasis']}")
                    for headline in data.get('headlines', []):
                        click.echo(f"   • \"{headline.get('title', 'N/A')[:60]}...\"")
                        click.echo(f"     — {headline.get('source', 'Unknown')}")
                    click.echo()
            
            # Contrast
            if result.get('contrast_analysis'):
                click.echo(f"💡 Contrast: {result['contrast_analysis']}")
                click.echo()
            
            # Omissions
            if result.get('omissions'):
                click.echo(f"🔍 What's Missing: {result['omissions']}")
                click.echo()

            # Metadata (performance and cost tracking)
            metadata = result.get('metadata', {})
            if metadata:
                click.echo(f"⚡ Performance Metrics:")
                click.echo(f"   Generation time: {metadata.get('generation_time_seconds', 'N/A')}s")
                click.echo(f"   API calls: {metadata.get('api_calls_made', 'N/A')}")
                click.echo(f"   Total tokens: {metadata.get('total_tokens_used', 'N/A')}")
                click.echo()

            click.echo(f"Methodology version: {result.get('methodology_version', 'N/A')}")

        except Exception as e:
            click.echo(f"Error generating lens check: {str(e)}", err=True)
            import traceback
            traceback.print_exc()

    @app.cli.command('show-underreported')
    @click.option('--days', default=7, help='Lookback window in days')
    @click.option('--limit', default=10, help='Number of stories to show')
    def show_underreported_cmd(days, limit):
        """Show underreported stories (high civic, low coverage)"""
        try:
            click.echo(f"Finding underreported stories (last {days} days)...\n")
            stories = get_underreported_stories(days=days, limit=limit)

            if not stories:
                click.echo("No underreported stories found")
                return

            click.echo(f"Found {len(stories)} underreported stories:\n")

            for story in stories:
                click.echo(f"• {story['topic'].title}")
                click.echo(f"  Civic score: {story['civic_score']:.2f}")
                click.echo(f"  Sources: {story['source_count']}")
                click.echo(f"  Coverage gaps: {', '.join(story['coverage_gaps'])}")
                click.echo()

        except Exception as e:
            click.echo(f"Error showing underreported: {str(e)}", err=True)

    @app.cli.command('publish-brief')
    @click.argument('brief_id', type=int)
    def publish_brief_cmd(brief_id):
        """Manually publish a brief"""
        try:
            brief = DailyBrief.query.get(brief_id)
            if not brief:
                click.echo(f"Brief {brief_id} not found", err=True)
                return

            if brief.status == 'published':
                click.echo(f"Brief already published at {brief.published_at}")
                return

            brief.status = 'published'
            brief.published_at = datetime.utcnow()
            brief.auto_selected = False
            db.session.commit()

            click.echo(f"✓ Published brief: {brief.title}")

        except Exception as e:
            click.echo(f"Error publishing brief: {str(e)}", err=True)

    @app.cli.command('skip-brief')
    @click.option('--reason', default='Admin decision', help='Reason for skipping')
    def skip_brief_cmd(reason):
        """Skip today's brief"""
        try:
            today = date_type.today()
            brief = DailyBrief.query.filter_by(date=today).first()

            if not brief:
                click.echo("No brief exists for today")
                return

            brief.status = 'skipped'
            brief.admin_notes = reason
            db.session.commit()

            click.echo(f"✓ Skipped brief for {today}: {reason}")

        except Exception as e:
            click.echo(f"Error skipping brief: {str(e)}", err=True)

    @app.cli.command('list-brief-subscribers')
    @click.option('--tier', default=None, help='Filter by tier (trial/individual/team)')
    @click.option('--limit', default=50, help='Max results to show')
    def list_subscribers_cmd(tier, limit):
        """List brief subscribers"""
        try:
            query = DailyBriefSubscriber.query

            if tier:
                query = query.filter_by(tier=tier)

            subscribers = query.limit(limit).all()

            click.echo(f"Subscribers ({len(subscribers)} shown):\n")

            for sub in subscribers:
                status_icon = "✓" if sub.status == 'active' else "✗"
                click.echo(f"{status_icon} {sub.email}")
                click.echo(f"   Tier: {sub.tier} | Status: {sub.status}")
                click.echo(f"   Timezone: {sub.timezone} | Send hour: {sub.preferred_send_hour}")
                if sub.trial_ends_at:
                    click.echo(f"   Trial ends: {sub.trial_ends_at.strftime('%Y-%m-%d')}")
                click.echo()

        except Exception as e:
            click.echo(f"Error listing subscribers: {str(e)}", err=True)

    @app.cli.command('create-brief-subscriber')
    @click.argument('email')
    @click.option('--timezone', default='UTC', help='Timezone (e.g., America/New_York)')
    @click.option('--hour', default=18, help='Preferred send hour (6, 8, or 18)')
    def create_subscriber_cmd(email, timezone, hour):
        """Create a test brief subscriber"""
        try:
            existing = DailyBriefSubscriber.query.filter_by(email=email).first()
            if existing:
                click.echo(f"Subscriber already exists: {email}")
                return

            subscriber = DailyBriefSubscriber(
                email=email,
                timezone=timezone,
                preferred_send_hour=hour
            )
            subscriber.generate_magic_token()
            subscriber.start_trial()

            db.session.add(subscriber)
            db.session.commit()

            click.echo(f"✓ Created subscriber: {email}")
            click.echo(f"  Timezone: {timezone}")
            click.echo(f"  Send hour: {hour}")
            click.echo(f"  Trial ends: {subscriber.trial_ends_at.strftime('%Y-%m-%d')}")

        except Exception as e:
            click.echo(f"Error creating subscriber: {str(e)}", err=True)

    @app.cli.command('brief-resend-welcome')
    @click.argument('email')
    @click.option('--force', is_flag=True, help='Force resend even if already sent')
    def brief_resend_welcome_cmd(email, force):
        """Resend welcome email to a brief subscriber (admin use)"""
        try:
            subscriber = DailyBriefSubscriber.query.filter_by(email=email).first()
            if not subscriber:
                click.echo(f"✗ Subscriber not found: {email}", err=True)
                return

            if subscriber.welcome_email_sent_at and not force:
                click.echo(f"✗ Welcome email already sent at {subscriber.welcome_email_sent_at}")
                click.echo("  Use --force to resend anyway")
                return

            from app.brief.email_client import ResendClient
            client = ResendClient()
            success = client.send_welcome(subscriber, force=force)

            if success:
                click.echo(f"✓ Welcome email sent to {email}")
            else:
                click.echo(f"✗ Failed to send welcome email", err=True)

        except Exception as e:
            click.echo(f"Error: {str(e)}", err=True)

    @app.cli.command('seed-brief-templates')
    def seed_brief_templates_cmd():
        """Seed BriefTemplate table with predefined templates"""
        try:
            from app.models import BriefTemplate
            from app.models import generate_slug

            templates_data = [
                {
                    'name': 'Politics',
                    'description': 'Daily political news and analysis from trusted sources across the spectrum.',
                    'default_sources': [],  # Will be populated with NewsSource IDs
                    'default_filters': {'topics': ['politics', 'government', 'policy', 'elections']},
                    'default_cadence': 'daily',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'Technology',
                    'description': 'Tech industry news, product launches, and innovation updates.',
                    'default_sources': [],
                    'default_filters': {'topics': ['technology', 'tech', 'innovation', 'startups', 'AI']},
                    'default_cadence': 'daily',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'Climate',
                    'description': 'Climate science, environmental policy, and sustainability news.',
                    'default_sources': [],
                    'default_filters': {'topics': ['climate', 'environment', 'sustainability', 'energy']},
                    'default_cadence': 'daily',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'Health',
                    'description': 'Healthcare policy, medical research, and public health updates.',
                    'default_sources': [],
                    'default_filters': {'topics': ['health', 'healthcare', 'medicine', 'public health']},
                    'default_cadence': 'daily',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'Business',
                    'description': 'Business news, economic analysis, and market updates.',
                    'default_sources': [],
                    'default_filters': {'topics': ['business', 'economy', 'finance', 'markets']},
                    'default_cadence': 'daily',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'Culture',
                    'description': 'Arts, culture, media, and social trends.',
                    'default_sources': [],
                    'default_filters': {'topics': ['culture', 'arts', 'media', 'entertainment']},
                    'default_cadence': 'weekly',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'AI & Machine Learning',
                    'description': 'Artificial intelligence, machine learning, and automation news.',
                    'default_sources': [],
                    'default_filters': {'topics': ['AI', 'artificial intelligence', 'machine learning', 'automation']},
                    'default_cadence': 'daily',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'Science',
                    'description': 'Scientific research, discoveries, and academic news.',
                    'default_sources': [],
                    'default_filters': {'topics': ['science', 'research', 'academic', 'discovery']},
                    'default_cadence': 'weekly',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'International',
                    'description': 'Global news, international relations, and world affairs.',
                    'default_sources': [],
                    'default_filters': {'topics': ['international', 'global', 'world', 'foreign policy']},
                    'default_cadence': 'daily',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                },
                {
                    'name': 'Sports',
                    'description': 'Sports news, analysis, and updates.',
                    'default_sources': [],
                    'default_filters': {'topics': ['sports', 'athletics', 'competition']},
                    'default_cadence': 'daily',
                    'default_tone': 'calm_neutral',
                    'allow_customization': True
                }
            ]

            added = 0
            updated = 0

            for template_data in templates_data:
                slug = generate_slug(template_data['name'])
                existing = BriefTemplate.query.filter_by(name=template_data['name']).first()

                if existing:
                    # Update existing template
                    for key, value in template_data.items():
                        if key != 'name':  # Don't update name
                            setattr(existing, key, value)
                    existing.slug = slug
                    updated += 1
                    click.echo(f"✓ Updated template: {template_data['name']}")
                else:
                    # Create new template
                    template = BriefTemplate(
                        name=template_data['name'],
                        slug=slug,
                        **{k: v for k, v in template_data.items() if k != 'name'}
                    )
                    db.session.add(template)
                    added += 1
                    click.echo(f"✓ Added template: {template_data['name']}")

            db.session.commit()
            click.echo(f"\n✓ Seeding complete: {added} added, {updated} updated")

        except Exception as e:
            db.session.rollback()
            click.echo(f"Error seeding brief templates: {str(e)}", err=True)
            import traceback
            traceback.print_exc()