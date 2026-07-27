
from flask.cli import with_appcontext
from flask import current_app
import click
from app import db
from app.models import User, IndividualProfile, CompanyProfile, Discussion
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive

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
from app.discussions.thresholds import CONSENSUS_RECOMMENDED_STATEMENT_COUNT
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

    @app.cli.command('generate-weekly-brief')
    @click.option(
        '--date',
        default=None,
        help='Week-ending date (Sunday) in YYYY-MM-DD format (default: most recent Sunday)',
    )
    @click.option('--force', is_flag=True, help='Force regenerate even if a ready/published edition exists')
    def generate_weekly_brief_cmd(date, force):
        """Generate weekly brief for the week ending on the given Sunday."""
        from datetime import date as date_type
        from app.brief.weekly_generator import generate_weekly_brief
        from app.models import DailyBrief
        from app.brief.sections import BRIEF_TYPE_WEEKLY

        try:
            if date:
                week_end = datetime.strptime(date, '%Y-%m-%d').date()
            else:
                today = date_type.today()
                days_since_sunday = (today.weekday() + 1) % 7
                week_end = today - timedelta(days=days_since_sunday)

            existing = DailyBrief.query.filter_by(
                date=week_end,
                brief_type=BRIEF_TYPE_WEEKLY,
            ).first()
            if existing and existing.status in ('ready', 'published') and not force:
                click.echo(
                    f"Weekly brief already exists for week ending {week_end} "
                    f"(status: {existing.status})"
                )
                click.echo("Use --force to regenerate")
                return

            click.echo(f"Generating weekly brief for week ending {week_end}...")
            brief = generate_weekly_brief(
                week_end_date=week_end,
                auto_publish=True,
                force=force,
            )

            if brief is None:
                click.echo("Weekly brief generation failed — see logs", err=True)
                return

            click.echo(f"✓ Weekly brief generated: {brief.title}")
            click.echo(f"  Items: {brief.item_count}")
            click.echo(f"  Status: {brief.status}")

        except Exception as e:
            click.echo(f"Error generating weekly brief: {str(e)}", err=True)

    @app.cli.command('test-brief-email')
    @click.argument('email')
    @click.option('--date', default=None, help='Date in YYYY-MM-DD format (default: latest)')
    @click.option('--type', 'brief_type', default='daily',
                  type=click.Choice(['daily', 'weekly']),
                  help='Which edition to send (default: daily)')
    @click.option('--allow-unpublished', is_flag=True,
                  help="Also consider 'ready' editions that are not published yet")
    def test_brief_email_cmd(email, date, brief_type, allow_unpublished):
        """Send test brief email to an address"""
        try:
            click.echo(f"Sending test {brief_type} email to {email}...")

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
                subscriber.ensure_unsubscribe_token()
                subscriber.start_trial()
                db.session.add(subscriber)
                db.session.commit()

            success = send_brief_to_subscriber(
                email, date, brief_type, allow_unpublished=allow_unpublished
            )

            if success:
                click.echo(f"✓ Email sent to {email}")
            else:
                click.echo(f"✗ Failed to send email", err=True)

        except Exception as e:
            click.echo(f"Error sending test email: {str(e)}", err=True)

    @app.cli.command('seed-allsides')
    @click.option('--force', is_flag=True, help='Force update all ratings even if unchanged')
    def seed_allsides_cmd(force):
        """Seed political leaning ratings from AllSides and MBFC"""
        try:
            click.echo("Updating political leaning ratings (AllSides + MBFC)...")
            results = update_source_leanings(force=force)

            click.echo(f"✓ Updated: {results['updated']} sources")
            click.echo(f"  Unchanged: {results['unchanged']}")
            if results['not_found']:
                click.echo(f"  Not found: {len(results['not_found'])} sources")
                for name in results['not_found']:
                    click.echo(f"    - {name}")

        except Exception as e:
            click.echo(f"Error seeding ratings: {str(e)}", err=True)

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
            brief = db.session.get(DailyBrief, brief_id)
            if not brief:
                click.echo(f"Brief {brief_id} not found", err=True)
                return

            if brief.status == 'published':
                click.echo(f"Brief already published at {brief.published_at}")
                return

            brief.status = 'published'
            brief.published_at = utcnow_naive()
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
    @click.option('--hour', default=18, help='Preferred send hour (6-9, 12, 17-20)')
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
            subscriber.ensure_unsubscribe_token()
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

    @app.cli.command('backfill-dq-subscriber-timezones')
    @click.option('--dry-run', is_flag=True, help='Report counts without updating rows')
    @click.option('--yes', is_flag=True, help='Skip the confirmation prompt')
    def backfill_dq_subscriber_timezones_cmd(dry_run, yes):
        """Set explicit UTC on daily-question subscribers with NULL timezone.

        ⚠️  NOT RECOMMENDED — prefer --dry-run to size the cohort, then leave it.

        This changes no send behaviour: ``should_receive_weekly_digest_now`` and
        ``hours_until_next_weekly_digest`` already resolve NULL to UTC. It does
        not improve any display either — ``daily/preferences.html`` renders NULL
        correctly as "UTC" already, and the admin list shows "UTC · not set".

        What it DOES do is destroy a signal. Today ``timezone IS NULL`` means
        "imported, never asked". After this runs those rows are identical to a
        subscriber who deliberately chose UTC, permanently and with no way back.
        That cohort — people receiving a 09:00 UTC digest at whatever local hour
        that lands on — is exactly the audience for a "when would you like this?"
        email, and this is the query that finds them.

        Kept for the case where you have already collected real timezones and
        want the stragglers made explicit.
        """
        from app.models import DailyQuestionSubscriber

        try:
            query = DailyQuestionSubscriber.query.filter(
                DailyQuestionSubscriber.is_active.is_(True),
                DailyQuestionSubscriber.timezone.is_(None),
            )
            total = query.count()
            if total == 0:
                click.echo('✓ No active daily-question subscribers with NULL timezone')
                return

            weekly = query.filter(
                DailyQuestionSubscriber.email_frequency == 'weekly',
            ).count()

            click.echo(
                f"Found {total} active subscriber(s) with NULL timezone "
                f"({weekly} on weekly digest cadence)"
            )
            if dry_run:
                click.echo('Dry run — no rows updated')
                return

            click.echo(
                'This overwrites NULL with UTC and permanently loses the '
                '"never asked" signal for these subscribers. Send times do not change.'
            )
            if not yes and not click.confirm('Continue?', default=False):
                click.echo('Aborted — no rows updated')
                return

            updated = query.update({'timezone': 'UTC'}, synchronize_session=False)
            db.session.commit()
            click.echo(f'✓ Set timezone=UTC on {updated} subscriber(s)')

        except Exception as e:
            db.session.rollback()
            click.echo(f'Error backfilling timezones: {str(e)}', err=True)

    @app.cli.command('backfill-normalized-urls')
    @click.option('--batch-size', default=500, help='Number of articles to process per batch')
    @click.option('--dry-run', is_flag=True, help='Show what would be done without making changes')
    def backfill_normalized_urls_cmd(batch_size, dry_run):
        """
        Backfill normalized_url and url_hash for existing NewsArticle records.

        This command should be run after the migration that adds the normalized_url
        and url_hash columns to the news_article table.

        Example:
            flask backfill-normalized-urls
            flask backfill-normalized-urls --batch-size=1000
            flask backfill-normalized-urls --dry-run
        """
        from app.models import NewsArticle
        from app.lib.url_normalizer import normalize_url, url_hash

        try:
            # Count total articles needing update
            total = NewsArticle.query.filter(
                NewsArticle.normalized_url.is_(None)
            ).count()

            if total == 0:
                click.echo("✓ All articles already have normalized_url set")
                return

            click.echo(f"Found {total} articles needing normalized_url backfill")

            if dry_run:
                click.echo("(Dry run - no changes will be made)")
                # Show a few examples
                samples = NewsArticle.query.filter(
                    NewsArticle.normalized_url.is_(None)
                ).limit(5).all()
                for article in samples:
                    normalized = normalize_url(article.url)
                    click.echo(f"  {article.url[:60]}...")
                    click.echo(f"    -> {normalized[:60] if normalized else 'INVALID'}...")
                return

            processed = 0
            updated = 0
            errors = 0

            while processed < total:
                # Get batch of articles
                articles = NewsArticle.query.filter(
                    NewsArticle.normalized_url.is_(None)
                ).limit(batch_size).all()

                if not articles:
                    break

                for article in articles:
                    try:
                        normalized = normalize_url(article.url)
                        if normalized:
                            article.normalized_url = normalized
                            article.url_hash = url_hash(article.url)
                            updated += 1
                        else:
                            # URL couldn't be normalized - log but don't fail
                            click.echo(f"  Warning: Could not normalize URL for article {article.id}: {article.url[:50]}...")
                            errors += 1
                    except Exception as e:
                        click.echo(f"  Error processing article {article.id}: {e}")
                        errors += 1

                    processed += 1

                # Commit batch
                db.session.commit()
                click.echo(f"  Processed {processed}/{total} ({updated} updated, {errors} errors)")

            click.echo(f"\n✓ Backfill complete: {updated} updated, {errors} errors out of {total} articles")

        except Exception as e:
            db.session.rollback()
            click.echo(f"Error during backfill: {str(e)}", err=True)
            import traceback
            traceback.print_exc()

    @app.cli.command('backfill-seed-statements')
    @click.option('--min', 'min_count', default=CONSENSUS_RECOMMENDED_STATEMENT_COUNT,
                  help='Minimum seed statements a discussion should have (default: 10)')
    @click.option('--limit', default=50, help='Max discussions to process this run')
    @click.option('--discussion-id', default=None, type=int,
                  help='Only process this discussion id (ignores --limit)')
    @click.option('--dry-run', is_flag=True, help='Report changes without writing to the database')
    def backfill_seed_statements_cmd(min_count, limit, discussion_id, dry_run):
        """Top up native-statement discussions below the recommended seed count.

        Finds discussions with fewer than --min visible statements (not deleted,
        not negatively moderated) and generates additional balanced pro/con/neutral
        seed statements via the LLM seed generator, skipping duplicates.

        Examples:
            flask backfill-seed-statements --dry-run
            flask backfill-seed-statements --limit 20
            flask backfill-seed-statements --discussion-id 9154
        """
        from sqlalchemy import func
        from app.models import Statement, User
        from app.trending.seed_generator import generate_seed_statements_from_content

        def _visible_query(disc_id):
            return (
                Statement.query
                .filter_by(discussion_id=disc_id, is_deleted=False)
                .filter(Statement.mod_status != -1)
            )

        try:
            if discussion_id is not None:
                disc = db.session.get(Discussion, discussion_id)
                if not disc:
                    click.echo(f"Discussion {discussion_id} not found", err=True)
                    return
                discussions = [disc]
            else:
                # Count visible statements per discussion, then keep the ones
                # below the floor. LEFT JOIN so discussions with zero statements
                # (coalesced to 0) are included.
                visible = (
                    db.session.query(
                        Statement.discussion_id.label('did'),
                        func.count(Statement.id).label('n'),
                    )
                    .filter(Statement.is_deleted.is_(False))
                    .filter(Statement.mod_status != -1)
                    .group_by(Statement.discussion_id)
                    .subquery()
                )
                rows = (
                    db.session.query(Discussion)
                    .outerjoin(visible, visible.c.did == Discussion.id)
                    .filter(Discussion.has_native_statements.is_(True))
                    .filter(func.coalesce(visible.c.n, 0) < min_count)
                    .order_by(Discussion.id.desc())
                    .limit(limit)
                    .all()
                )
                discussions = list(rows)

            if not discussions:
                click.echo(f"✓ No native-statement discussions below {min_count} statements")
                return

            click.echo(f"Found {len(discussions)} discussion(s) below {min_count} statements"
                       + (" (dry run)" if dry_run else ""))

            default_admin = User.query.filter_by(is_admin=True).order_by(User.id).first()

            total_added = 0
            for disc in discussions:
                existing = _visible_query(disc.id).all()
                existing_contents = {
                    " ".join((s.content or "").split()).lower() for s in existing
                }
                current = len(existing)
                needed = min_count - current
                if needed <= 0:
                    continue

                click.echo(f"\n#{disc.id} '{(disc.title or '')[:60]}' — "
                           f"{current} statement(s), need {needed} more")

                # Ask only for novel fillers; exclude existing content so the
                # generator's floor/padding produces statements we can actually add.
                generated = generate_seed_statements_from_content(
                    title=disc.title,
                    excerpt=disc.description or "",
                    count=needed,
                    exclude_contents=existing_contents,
                )

                author_id = disc.creator_id or (default_admin.id if default_admin else None)

                added_here = 0
                for stmt in generated:
                    if added_here >= needed:
                        break
                    content = " ".join(str(stmt.get('content', '')).split())[:500]
                    if len(content) < 10 or content.lower() in existing_contents:
                        continue
                    existing_contents.add(content.lower())
                    position = (stmt.get('position') or 'neutral').lower()
                    if position not in ('pro', 'con', 'neutral'):
                        position = 'neutral'
                    click.echo(f"   + [{position}] {content[:80]}")
                    if not dry_run:
                        db.session.add(Statement(
                            discussion_id=disc.id,
                            user_id=author_id,
                            content=content,
                            statement_type='claim',
                            is_seed=True,
                            mod_status=1,
                            source='ai_generated',
                            seed_stance=position,
                        ))
                    added_here += 1

                if added_here < needed:
                    click.echo(
                        f"   ! only produced {added_here}/{needed} novel statements for #{disc.id}",
                        err=True,
                    )

                total_added += added_here
                if not dry_run:
                    db.session.commit()

            verb = "would add" if dry_run else "added"
            click.echo(f"\n✓ Backfill complete: {verb} {total_added} seed statement(s) "
                       f"across {len(discussions)} discussion(s)")

        except Exception as e:
            db.session.rollback()
            click.echo(f"Error backfilling seed statements: {str(e)}", err=True)
            import traceback
            traceback.print_exc()

    @app.cli.command('journey-theme-analytics')
    @click.option('--limit', default=15, help='Max topics to list')
    def journey_theme_analytics_cmd(limit):
        """Print ranked Discussion.topic engagement for curriculum planning."""
        from app.programmes.journey_analytics import compute_topic_rankings

        rows = compute_topic_rankings(limit=limit)
        if not rows:
            click.echo("No topic data found (empty database or no votes yet).")
            return
        click.echo(
            f"{'topic':<18} {'votes':>7} {'voters':>7} {'disc':>5} {'civic':>7} {'qual':>7} {'score':>9}"
        )
        click.echo("-" * 70)
        for r in rows:
            click.echo(
                f"{r['topic'][:18]:<18} {r['vote_count']:>7} {r['distinct_voters']:>7} "
                f"{r['discussion_count']:>5} {r['avg_trending_civic']:>7.2f} {r['avg_trending_quality']:>7.2f} {r['composite_score']:>9.1f}"
            )

    from app.programmes.journey_variants import VALID_VARIANTS as _GUIDED_JOURNEY_VARIANTS

    _seed_journey_variant_choice = click.Choice(sorted(_GUIDED_JOURNEY_VARIANTS))

    @app.cli.command('seed-guided-journey')
    @click.option(
        '--variant',
        default='global',
        type=_seed_journey_variant_choice,
        help='Country variant to seed (default: global); keys defined in journey_variants.VARIANT_METADATA.',
    )
    @click.option('--all-variants', is_flag=True, default=False,
                  help='Seed all country variants in one run')
    @click.option('--creator-email', default=None, help='User to own programme and seed statements')
    def seed_guided_journey_cmd(variant, all_variants, creator_email):
        """Create or update guided flagship programmes (global + 10 country variants)."""
        from app.programmes.journey_seed import seed_guided_journey_programme

        targets = sorted(_GUIDED_JOURNEY_VARIANTS) if all_variants else [variant]
        for v in targets:
            try:
                p = seed_guided_journey_programme(variant=v, creator_email=creator_email)
                click.echo(f"✓ {v:6s}  {p.name}  (slug={p.slug}, id={p.id})")
            except Exception as e:
                db.session.rollback()
                click.echo(f"✗ {v:6s}  Error: {e}", err=True)
                import traceback
                traceback.print_exc()