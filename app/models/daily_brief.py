"""
Daily Brief v1 system.

DailyBrief — evening sense-making brief (published at 6pm), supports
daily and weekly cadence and both flat and sectioned item layouts.
BriefItem — individual stories in a brief, with section/depth metadata
and coverage analysis.
NewsPerspectiveCache — cached LLM-generated perspectives for topics
surfaced on the /news transparency page but not promoted into a brief.
AudioGenerationJob — batch audio job (XTTS v2) for either a DailyBrief
or a BriefRun (polymorphic on brief_type).
DailyBriefSubscriber — subscriber list with tier (trial/free/individual/
team), timezone + send-hour preferences, Stripe linkage, and idempotent
send tracking.
BriefTeam — multi-seat team subscriptions.

Moved here from app/models.py as part of the models-split refactor.
Cross-domain relationships (User, TrendingTopic, Discussion, BriefRun)
use string references; no cross-submodule imports are required.
"""

from datetime import timedelta

from app import db
from app.lib.time import utcnow_naive


class DailyBrief(db.Model):
    """
    Daily Sense-Making Brief - Evening news summary (6pm).
    Aggregates curated topics with coverage analysis, organised into sections.
    Separate from Daily Question (morning participation prompt).

    Supports two formats:
    - Legacy flat: 3-5 items ordered by position (backward compatible)
    - Sectioned: Items grouped by section (lead, politics, economy, etc.) at variable depth

    Also supports weekly briefs via brief_type='weekly'.
    """
    __tablename__ = 'daily_brief'
    __table_args__ = (
        db.Index('idx_brief_date', 'date'),
        db.Index('idx_brief_status', 'status'),
        db.Index('idx_brief_type_date', 'brief_type', 'date'),
        db.UniqueConstraint('date', 'brief_type', name='uq_daily_brief_date_type'),
    )

    id = db.Column(db.Integer, primary_key=True)

    date = db.Column(db.Date, nullable=False)  # Unique per brief_type (see composite constraint)
    title = db.Column(db.String(200))  # e.g., "Tuesday's Brief: Climate, Tech, Healthcare"
    intro_text = db.Column(db.Text)  # 2-3 sentence calm framing

    status = db.Column(db.String(20), default='draft')  # draft|ready|published|skipped

    # Brief type: daily (default) or weekly
    brief_type = db.Column(db.String(10), default='daily')  # daily|weekly

    # For weekly briefs: which week does this cover?
    week_start_date = db.Column(db.Date, nullable=True)  # Monday of the week
    week_end_date = db.Column(db.Date, nullable=True)    # Sunday of the week

    # Admin override tracking
    auto_selected = db.Column(db.Boolean, default=True)  # False if admin edited
    admin_edited_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    admin_notes = db.Column(db.Text)  # Why was this edited/skipped?

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    published_at = db.Column(db.DateTime)

    # "Same Story, Different Lens" cross-perspective analysis
    # Shows how left/centre/right outlets frame the same story differently
    # Generated automatically during brief creation - see app/brief/lens_check.py
    lens_check = db.Column(db.JSON)

    # "The Week Ahead" events data
    # Generated during brief creation - see app/brief/generator.py
    week_ahead = db.Column(db.JSON)  # [{'title': '...', 'date': '...', 'description': '...', 'category': '...'}]

    # "Market Pulse" section data (aggregated from Polymarket)
    # Stored at brief level so it's not tied to individual items
    market_pulse = db.Column(db.JSON)  # [{'question': '...', 'probability': 0.65, ...}]

    # "What the World is Watching" section data (curated geopolitical prediction markets)
    # Same schema as market_pulse but filtered by world events categories + high volume
    world_events = db.Column(db.JSON)  # [{'question': '...', 'probability': 0.65, 'category': '...', ...}]

    # Relationships
    items = db.relationship('BriefItem', backref='brief', lazy='dynamic',
                           cascade='all, delete-orphan', order_by='BriefItem.position')
    admin_editor = db.relationship('User', backref='edited_briefs', foreign_keys=[admin_edited_by])

    @property
    def item_count(self):
        """Number of items in this brief.

        Uses cached count if available (set by batch queries in routes)
        to prevent N+1 query issues.
        """
        if hasattr(self, '_cached_item_count'):
            return self._cached_item_count
        # Use count() method if available (for lazy/dynamic relationships)
        # Otherwise fall back to len() for eagerly loaded lists
        if hasattr(self.items, 'count') and callable(self.items.count):
            return self.items.count()
        try:
            return len(self.items)
        except TypeError:
            # Fallback: query the database directly
            return BriefItem.query.filter_by(brief_id=self.id).count()

    @classmethod
    def get_today(cls, brief_type='daily'):
        """Get today's brief (optionally by type)"""
        from datetime import date
        today = date.today()
        return cls.query.filter_by(date=today, status='published', brief_type=brief_type).first() or \
               cls.query.filter_by(date=today, status='ready', brief_type=brief_type).first()

    @classmethod
    def get_by_date(cls, brief_date, brief_type='daily'):
        """Get brief for a specific date (optionally by type)"""
        return cls.query.filter_by(date=brief_date, status='published', brief_type=brief_type).first() or \
               cls.query.filter_by(date=brief_date, status='ready', brief_type=brief_type).first()

    @property
    def is_sectioned(self):
        """Check if this brief uses the sectioned format (vs legacy flat)."""
        from app.brief.sections import is_sectioned_brief
        items = self.items.all() if hasattr(self.items, 'all') else list(self.items)
        return is_sectioned_brief(items)

    @property
    def items_by_section(self):
        """Get items grouped by section for template rendering."""
        from app.brief.sections import group_items_by_section
        items = self.items.order_by(BriefItem.position).all() if hasattr(self.items, 'all') else list(self.items)
        return group_items_by_section(items)

    @property
    def reading_time(self):
        """Estimate reading time in minutes based on word count (~200 WPM).

        Returns 0 for empty briefs, otherwise at least 1 minute.
        """
        word_count = 0
        try:
            items = self.items.all() if hasattr(self.items, 'all') else list(self.items)
        except Exception:
            return 0
        if not items:
            return 0
        for item in items:
            if item.headline:
                word_count += len(item.headline.split())
            if item.summary_bullets:
                for bullet in (item.summary_bullets or []):
                    if bullet:
                        word_count += len(str(bullet).split())
            if item.so_what:
                word_count += len(item.so_what.split())
            if item.personal_impact:
                word_count += len(item.personal_impact.split())
            if item.quick_summary:
                word_count += len(item.quick_summary.split())
        if word_count == 0:
            return 0
        return max(1, round(word_count / 200))

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.isoformat(),
            'title': self.title,
            'intro_text': self.intro_text,
            'status': self.status,
            'brief_type': self.brief_type,
            'item_count': self.item_count,
            'reading_time': self.reading_time,
            'items': [item.to_dict() for item in self.items.order_by(BriefItem.position)],
            'lens_check': self.lens_check,
            'week_ahead': self.week_ahead,
            'market_pulse': self.market_pulse,
            'world_events': self.world_events,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'created_at': self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<DailyBrief {self.date} {self.brief_type} ({self.status})>'


class BriefItem(db.Model):
    """
    Individual story in a daily brief.
    References TrendingTopic for DRY principle.

    Items are grouped by section and rendered at different depth levels:
    - full: headline, 4 bullets, personal impact, so what, perspectives, deeper context
    - standard: headline, 2 bullets, so what, coverage bar
    - quick: headline + one-sentence summary (used for global roundup, week ahead)

    For backward compatibility, items without section/depth are treated as
    legacy flat items rendered with full depth.
    """
    __tablename__ = 'brief_item'
    __table_args__ = (
        db.Index('idx_brief_item_brief', 'brief_id'),
        db.Index('idx_brief_item_topic', 'trending_topic_id'),
        db.Index('idx_brief_item_section', 'brief_id', 'section'),
        db.UniqueConstraint('brief_id', 'position', name='uq_brief_position'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # Overall display order (1-based)

    # Section and depth (new — nullable for backward compatibility with legacy briefs)
    # Section: which part of the brief this item belongs to (lead, politics, economy, etc.)
    # Depth: how much content to generate (full, standard, quick)
    section = db.Column(db.String(30), nullable=True)   # See app/brief/sections.VALID_SECTIONS
    depth = db.Column(db.String(15), nullable=True)      # 'full', 'standard', 'quick'

    # One-sentence summary for quick-depth items (replaces bullets)
    quick_summary = db.Column(db.Text, nullable=True)

    # Source (DRY - reference existing TrendingTopic)
    # RESTRICT prevents deleting topics that are used in briefs
    # Nullable for items that don't reference topics (e.g., week_ahead, market_pulse)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='RESTRICT'), nullable=True)

    # Generated content (LLM-created for brief context)
    headline = db.Column(db.String(200))  # Shorter, punchier than TrendingTopic title
    summary_bullets = db.Column(db.JSON)  # ['bullet1', 'bullet2', 'bullet3']
    personal_impact = db.Column(db.Text)  # One-sentence personal relevance ("Why This Matters To You")
    so_what = db.Column(db.Text)  # "So what?" analysis paragraph
    perspectives = db.Column(db.JSON)  # {'left': '...', 'center': '...', 'right': '...'}

    # Coverage analysis (computed from TrendingTopic articles)
    coverage_distribution = db.Column(db.JSON)  # {'left': 0.2, 'center': 0.5, 'right': 0.3}
    coverage_imbalance = db.Column(db.Float)  # 0-1 score (0=balanced, 1=single perspective)
    source_count = db.Column(db.Integer)  # Number of unique sources
    sources_by_leaning = db.Column(db.JSON)  # {'left': ['Guardian'], 'center': ['BBC', 'FT'], 'right': []}
    blindspot_explanation = db.Column(db.Text)  # LLM-generated explanation for coverage gaps

    # Sensationalism (from source articles)
    sensationalism_score = db.Column(db.Float)  # Average of article scores
    sensationalism_label = db.Column(db.String(20))  # 'low', 'medium', 'high'

    # Verification links (LLM-extracted + admin additions)
    verification_links = db.Column(db.JSON)  # [{'tier': 'primary', 'url': '...', 'type': '...', 'description': '...', 'is_paywalled': bool}]

    # CTA to discussion
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)
    cta_text = db.Column(db.String(200))  # Customizable per item

    # Special item types
    is_underreported = db.Column(db.Boolean, default=False)  # "Under the Radar" bonus item

    # Polymarket Integration (optional market signal data)
    # Stored as JSON snapshot at brief generation time for historical accuracy
    # Schema: see PolymarketMarket.to_signal_dict()
    market_signal = db.Column(db.JSON)  # null if no matching market

    # Deeper context for "Want more detail?" feature
    deeper_context = db.Column(db.Text)  # Extended analysis and background

    # Audio/TTS integration (XTTS v2 - open source)
    audio_url = db.Column(db.String(500))  # URL to generated audio file
    audio_voice_id = db.Column(db.String(100))  # XTTS voice ID used
    audio_generated_at = db.Column(db.DateTime)  # When audio was generated

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    trending_topic = db.relationship('TrendingTopic', backref='brief_items')
    discussion = db.relationship('Discussion', backref='brief_items')

    @property
    def effective_depth(self):
        """Get the rendering depth, defaulting to 'full' for legacy items."""
        return self.depth or 'full'

    @property
    def section_display_name(self):
        """Get the display name for this item's section."""
        from app.brief.sections import SECTIONS
        if self.section and self.section in SECTIONS:
            return SECTIONS[self.section]['display_name']
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'position': self.position,
            'section': self.section,
            'depth': self.depth,
            'quick_summary': self.quick_summary,
            'headline': self.headline,
            'summary_bullets': self.summary_bullets,
            'personal_impact': self.personal_impact,
            'so_what': self.so_what,
            'perspectives': self.perspectives,
            'coverage_distribution': self.coverage_distribution,
            'coverage_imbalance': self.coverage_imbalance,
            'source_count': self.source_count,
            'sources_by_leaning': self.sources_by_leaning,
            'blindspot_explanation': self.blindspot_explanation,
            'sensationalism_score': self.sensationalism_score,
            'sensationalism_label': self.sensationalism_label,
            'verification_links': self.verification_links,
            'discussion_id': self.discussion_id,
            'cta_text': self.cta_text,
            'is_underreported': self.is_underreported,
            'market_signal': self.market_signal,
            'deeper_context': self.deeper_context,
            'audio_url': self.audio_url,
            'audio_voice_id': self.audio_voice_id,
            'trending_topic': self.trending_topic.to_dict() if self.trending_topic else None
        }

    def __repr__(self):
        section_str = f' [{self.section}]' if self.section else ''
        return f'<BriefItem {self.position}.{section_str} {self.headline}>'


class NewsPerspectiveCache(db.Model):
    """
    Cache for perspective analysis generated on news transparency page.

    Separate from BriefItem to avoid coupling. Caches LLM-generated perspectives
    for topics that appear on /news but weren't in the daily brief.
    """
    __tablename__ = 'news_perspective_cache'
    __table_args__ = (
        db.Index('idx_npc_topic_date', 'trending_topic_id', 'generated_date'),
        db.UniqueConstraint('trending_topic_id', 'generated_date', name='uq_npc_topic_date'),
    )

    id = db.Column(db.Integer, primary_key=True)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='CASCADE'), nullable=False)

    # Generated content (LLM-created)
    perspectives = db.Column(db.JSON)  # {'left': '...', 'center': '...', 'right': '...'}
    so_what = db.Column(db.Text)  # "So what?" analysis
    personal_impact = db.Column(db.Text)  # "Why This Matters To You"

    # Cache metadata
    generated_date = db.Column(db.Date, nullable=False)  # Date generated for (allows re-generation)
    generated_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    trending_topic = db.relationship('TrendingTopic', backref='news_perspective_cache')

    def to_dict(self):
        return {
            'id': self.id,
            'trending_topic_id': self.trending_topic_id,
            'perspectives': self.perspectives,
            'so_what': self.so_what,
            'personal_impact': self.personal_impact,
            'generated_date': self.generated_date.isoformat() if self.generated_date else None,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None
        }

    def __repr__(self):
        return f'<NewsPerspectiveCache topic_id={self.trending_topic_id} date={self.generated_date}>'


class AudioGenerationJob(db.Model):
    """
    Tracks batch audio generation jobs for daily briefs.

    Allows generating audio for all items in a brief at once,
    with progress tracking and status updates.

    Optimized for Replit deployment with stale job recovery.
    """
    __tablename__ = 'audio_generation_job'
    __table_args__ = (
        db.Index('idx_audio_job_brief', 'brief_id'),
        db.Index('idx_audio_job_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Support both DailyBrief and BriefRun (polymorphic)
    brief_type = db.Column(db.String(20), nullable=False, default='daily_brief')  # 'daily_brief' | 'brief_run'
    brief_id = db.Column(db.Integer, db.ForeignKey('daily_brief.id', ondelete='CASCADE'), nullable=True)  # For DailyBrief
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=True)  # For BriefRun

    voice_id = db.Column(db.String(100), nullable=True)  # XTTS voice ID

    status = db.Column(db.String(20), nullable=False, default='queued')  # queued, processing, completed, failed
    progress = db.Column(db.Integer, default=0)  # 0-100 percentage
    total_items = db.Column(db.Integer, nullable=False)
    completed_items = db.Column(db.Integer, default=0)
    failed_items = db.Column(db.Integer, default=0)  # Track items that failed to generate
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive, nullable=False)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    # Relationships
    brief = db.relationship('DailyBrief', backref='audio_jobs', foreign_keys=[brief_id])
    brief_run = db.relationship('BriefRun', backref='audio_jobs', foreign_keys=[brief_run_id])

    @property
    def progress_percentage(self):
        """Calculate progress percentage based on processed items (completed + failed)."""
        if self.total_items == 0:
            return 0
        processed = (self.completed_items or 0) + (self.failed_items or 0)
        # Cap at 100% to handle edge cases
        return min(int((processed / self.total_items) * 100), 100)

    @property
    def is_stale(self):
        """Check if job is stuck in processing for too long (30 minutes)."""
        if self.status != 'processing' or not self.started_at:
            return False
        return utcnow_naive() - self.started_at > timedelta(minutes=30)

    def to_dict(self):
        return {
            'id': self.id,
            'brief_type': self.brief_type,
            'brief_id': self.brief_id,
            'brief_run_id': self.brief_run_id,
            'voice_id': self.voice_id,
            'status': self.status,
            'progress': self.progress_percentage,
            'total_items': self.total_items,
            'completed_items': self.completed_items or 0,
            'failed_items': self.failed_items or 0,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }

    def __repr__(self):
        return f'<AudioGenerationJob brief_id={self.brief_id} status={self.status} progress={self.progress_percentage}%>'


class DailyBriefSubscriber(db.Model):
    """
    Subscribers to daily brief (separate from daily question).
    Supports paid tiers and timezone preferences.
    """
    __tablename__ = 'daily_brief_subscriber'
    __table_args__ = (
        db.Index('idx_dbs_email', 'email'),
        db.Index('idx_dbs_token', 'magic_token'),
        db.Index('idx_dbs_team', 'team_id'),
        db.Index('idx_dbs_status', 'status'),
        db.Index('idx_dbs_tier_status', 'tier', 'status'),  # Composite index for tier+status queries
    )

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), nullable=False, unique=True)

    # Subscription tier
    tier = db.Column(db.String(20), default='trial')  # trial|free|individual|team
    trial_started_at = db.Column(db.DateTime)
    trial_ends_at = db.Column(db.DateTime)  # 30-day trial

    # Team management
    team_id = db.Column(db.Integer, db.ForeignKey('brief_team.id'), nullable=True)

    # Preferences
    timezone = db.Column(db.String(50), default='UTC')  # e.g., 'Europe/London', 'America/New_York'
    preferred_send_hour = db.Column(db.Integer, default=18)  # 6pm in their timezone (options: 6, 8, 18)

    # Brief cadence: daily (default) or weekly
    cadence = db.Column(db.String(10), default='daily')  # daily|weekly
    preferred_weekly_day = db.Column(db.Integer, default=6)  # Day for weekly delivery (0=Mon, 6=Sun)

    # Status
    status = db.Column(db.String(20), default='active')  # active|unsubscribed|bounced|payment_failed
    unsubscribed_at = db.Column(db.DateTime)

    # Magic link auth (reuse pattern from DailyQuestionSubscriber)
    magic_token = db.Column(db.String(64), unique=True)
    magic_token_expires = db.Column(db.DateTime)

    # Stripe integration
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))
    subscription_expires_at = db.Column(db.DateTime)  # For grace period

    # Optional: Link to User account
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Tracking
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    last_sent_at = db.Column(db.DateTime)
    last_brief_id_sent = db.Column(db.Integer, db.ForeignKey('daily_brief.id'), nullable=True)
    total_briefs_received = db.Column(db.Integer, default=0)
    welcome_email_sent_at = db.Column(db.DateTime)  # Prevents duplicate welcome emails

    # Email analytics
    total_opens = db.Column(db.Integer, default=0)
    total_clicks = db.Column(db.Integer, default=0)
    last_opened_at = db.Column(db.DateTime)
    last_clicked_at = db.Column(db.DateTime)

    # Relationships
    user = db.relationship('User', backref='brief_subscription')
    team = db.relationship('BriefTeam', backref='members')

    def generate_magic_token(self, expires_hours=48):
        """Generate a new magic link token"""
        import secrets
        self.magic_token = secrets.token_urlsafe(32)
        self.magic_token_expires = utcnow_naive() + timedelta(hours=expires_hours)
        return self.magic_token

    @staticmethod
    def verify_magic_token(token):
        """Verify magic token and return subscriber if valid"""
        subscriber = DailyBriefSubscriber.query.filter_by(
            magic_token=token,
            status='active'
        ).first()

        if not subscriber:
            return None

        if subscriber.magic_token_expires and subscriber.magic_token_expires < utcnow_naive():
            return None

        return subscriber

    def start_trial(self, days=30):
        """Start free trial with specified duration (default 30 days)"""
        self.tier = 'trial'
        self.trial_started_at = utcnow_naive()
        self.trial_ends_at = utcnow_naive() + timedelta(days=days)
        self.status = 'active'

    def extend_trial(self, additional_days=30):
        """Extend trial by specified number of days"""
        if not self.trial_ends_at:
            self.trial_ends_at = utcnow_naive()
        self.trial_ends_at = self.trial_ends_at + timedelta(days=additional_days)
        self.tier = 'trial'

    def grant_free_access(self):
        """Grant permanent free access (admin use only)"""
        self.tier = 'free'
        self.trial_ends_at = None  # No expiration
        self.subscription_expires_at = None
        self.status = 'active'

    @property
    def trial_days_remaining(self):
        """Returns days remaining in trial, or None if not on trial"""
        if self.tier != 'trial' or not self.trial_ends_at:
            return None
        remaining = (self.trial_ends_at - utcnow_naive()).days
        return max(0, remaining)

    @property
    def is_trial_expired(self):
        """Check if trial has expired"""
        if self.tier != 'trial':
            return False
        if not self.trial_ends_at:
            return True
        return utcnow_naive() > self.trial_ends_at

    @property
    def subscription_status_display(self):
        """Human-readable subscription status for admin UI"""
        if self.tier == 'free':
            return 'Free (Admin)'
        elif self.tier == 'trial':
            if self.is_trial_expired:
                return 'Trial Expired'
            days = self.trial_days_remaining
            if days == 0:
                return 'Trial Expires Today'
            elif days == 1:
                return 'Trial: 1 day left'
            else:
                return f'Trial: {days} days left'
        elif self.tier in ['individual', 'team']:
            if self.subscription_expires_at:
                if utcnow_naive() > self.subscription_expires_at:
                    return f'{self.tier.title()} (Expired)'
                return f'{self.tier.title()} (Active)'
            return f'{self.tier.title()} (Pending)'
        return 'Unknown'

    def is_subscribed_eligible(self):
        """Check if subscriber should receive emails.

        The Daily Brief is free for all active subscribers — no tier or
        payment check is required.  Only the status field matters.
        """
        return self.status == 'active'

    def has_received_brief_today(self, brief_date=None):
        """Check if subscriber already received brief for given date (prevents duplicate sends)"""
        from datetime import date as date_type
        if brief_date is None:
            brief_date = date_type.today()

        if not self.last_sent_at:
            return False

        return self.last_sent_at.date() == brief_date

    def has_received_this_brief(self, brief_id):
        """DB-level idempotency: check if this specific brief was already sent"""
        return self.last_brief_id_sent == brief_id

    def can_receive_brief(self, brief_date=None, brief_id=None):
        """Full eligibility check including duplicate prevention"""
        if not self.is_subscribed_eligible():
            return False

        if brief_id is not None and self.has_received_this_brief(brief_id):
            return False

        if self.has_received_brief_today(brief_date):
            return False

        return True

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'tier': self.tier,
            'timezone': self.timezone,
            'preferred_send_hour': self.preferred_send_hour,
            'status': self.status,
            'is_eligible': self.is_subscribed_eligible(),
            'trial_ends_at': self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            'trial_days_remaining': self.trial_days_remaining,
            'is_trial_expired': self.is_trial_expired,
            'subscription_status_display': self.subscription_status_display
        }

    def __repr__(self):
        return f'<DailyBriefSubscriber {self.email} ({self.tier})>'


class BriefTeam(db.Model):
    """
    Multi-seat team subscriptions for daily brief.
    """
    __tablename__ = 'brief_team'
    __table_args__ = (
        db.Index('idx_brief_team_admin', 'admin_email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))

    # Billing
    seat_limit = db.Column(db.Integer, default=5)
    price_per_seat = db.Column(db.Integer, default=800)  # $8.00 in cents (team rate)
    base_price = db.Column(db.Integer, default=4000)  # $40/month for 5 seats

    # Stripe
    stripe_customer_id = db.Column(db.String(255))
    stripe_subscription_id = db.Column(db.String(255))

    # Admin contact
    admin_email = db.Column(db.String(255))  # Who manages the team

    # Status
    status = db.Column(db.String(20), default='active')  # active|cancelled|payment_failed

    # Tracking
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    @property
    def current_seat_count(self):
        """Number of active members"""
        return DailyBriefSubscriber.query.filter_by(
            team_id=self.id,
            status='active'
        ).count()

    @property
    def has_available_seats(self):
        """Check if team has available seats"""
        return self.current_seat_count < self.seat_limit

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'seat_limit': self.seat_limit,
            'current_seat_count': self.current_seat_count,
            'has_available_seats': self.has_available_seats,
            'admin_email': self.admin_email,
            'status': self.status
        }

    def __repr__(self):
        return f'<BriefTeam {self.name} ({self.current_seat_count}/{self.seat_limit} seats)>'
