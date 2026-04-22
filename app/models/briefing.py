"""
Multi-tenant briefing system (v2).

BriefTemplate — off-the-shelf template archetypes (marketplace).
InputSource / IngestedItem — generalized source + item model that
coexists with NewsSource/NewsArticle during the migration to a unified
ingestion layer.
Briefing / BriefingSource — per-owner briefing config and its source
associations.
BriefRun / BriefRunItem — execution instances and the items they render.
BriefEmailOpen / BriefEmailSend / BriefLinkClick — analytics and
two-phase send-tracking for recipients.
BriefRecipient — per-briefing subscriber list (magic-token auth).
SendingDomain — Resend-verified custom domains for organisation brands.
BriefEdit — approval-workflow edit history.

Moved here from app/models.py as part of the models-split refactor.
All cross-domain relationships (User, CompanyProfile, TrendingTopic)
use string references so this submodule has no inbound imports from
other models submodules.
"""

from sqlalchemy.dialects.postgresql import JSONB

from app import db
from app.lib.time import utcnow_naive


class BriefTemplate(db.Model):
    """
    Predefined brief templates (off-the-shelf themes) for the template marketplace.
    Templates are configurable archetypes with intent, cadence, structure, tone, and source types.
    Users can clone a template to create their own briefing with bounded customization.
    """
    __tablename__ = 'brief_template'
    __table_args__ = (
        db.Index('idx_brief_template_name', 'name'),
        db.Index('idx_brief_template_category', 'category'),
        db.Index('idx_brief_template_audience', 'audience_type'),
        db.Index('idx_brief_template_featured', 'is_featured'),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    description = db.Column(db.Text)  # Short description for marketplace listing
    slug = db.Column(db.String(100), unique=True)  # URL-friendly identifier

    # Marketplace categorization
    category = db.Column(db.String(50), default='core_insight')
    # Categories: 'core_insight', 'organizational', 'personal_interest', 'lifestyle'
    audience_type = db.Column(db.String(30), default='all')
    # Audience: 'individual', 'organization', 'all'

    # Display metadata
    icon = db.Column(db.String(50), default='newspaper')  # Icon name for UI
    tagline = db.Column(db.String(200))  # Short tagline (e.g., "What Changed" for Politics)
    sample_output = db.Column(db.Text)  # Example brief output for preview

    # Marketplace visibility
    is_featured = db.Column(db.Boolean, default=False)  # Show in featured section
    is_active = db.Column(db.Boolean, default=True)  # Available in marketplace
    sort_order = db.Column(db.Integer, default=0)  # Display order within category

    # Default config (JSON)
    default_sources = db.Column(db.JSON)  # List of NewsSource IDs or category filters
    default_filters = db.Column(db.JSON)  # Keywords, topics, geographic scope
    default_cadence = db.Column(db.String(20), default='daily')  # 'daily' | 'weekly'
    default_tone = db.Column(db.String(50), default='calm_neutral')
    default_accent_color = db.Column(db.String(20), default='#3B82F6')  # Topic-specific accent color

    # Configurable bounds (JSON) - what users CAN change
    configurable_options = db.Column(JSONB, default=lambda: {
        'geography': True,  # Can user change geographic scope?
        'sources': True,  # Can user add/remove sources?
        'cadence': True,  # Can user change cadence?
        'visibility': True,  # Can user change visibility?
        'auto_send': True,  # Can user toggle auto-send vs approval?
        'tone': False,  # Tone is fixed by default for brand consistency
        'cadence_options': ['daily', 'weekly'],  # Allowed cadence values
    })

    # Fixed guardrails (JSON) - what is ALWAYS enforced
    guardrails = db.Column(JSONB, default=lambda: {
        'max_items': 10,  # Maximum stories per brief
        'require_attribution': True,  # Always show sources
        'no_predictions': False,  # Disable speculative content (for crypto/markets)
        'no_outrage_framing': True,  # Filter sensational headlines
        'structure_template': 'standard',  # Fixed section structure
    })

    # AI generation hints
    custom_prompt_prefix = db.Column(db.Text)  # Added to AI prompt for this template
    focus_keywords = db.Column(JSONB)  # Keywords to prioritize
    exclude_keywords = db.Column(JSONB)  # Keywords to filter out

    # Customization
    allow_customization = db.Column(db.Boolean, default=True)  # Can user modify at all?

    # Usage tracking
    times_used = db.Column(db.Integer, default=0)  # How many briefings created from this

    # Metadata
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    @staticmethod
    def get_category_label(category):
        """Get human-readable category label."""
        labels = {
            'core_insight': 'Core Insight',
            'organizational': 'Organizational',
            'personal_interest': 'Personal Interest',
            'lifestyle': 'Lifestyle & Wellbeing',
        }
        return labels.get(category, category.replace('_', ' ').title())

    @staticmethod
    def get_audience_label(audience_type):
        """Get human-readable audience label."""
        labels = {
            'individual': 'Individuals',
            'organization': 'Organizations',
            'all': 'Everyone',
        }
        return labels.get(audience_type, audience_type.title())

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'slug': self.slug,
            'category': self.category,
            'category_label': self.get_category_label(self.category),
            'audience_type': self.audience_type,
            'audience_label': self.get_audience_label(self.audience_type),
            'icon': self.icon,
            'tagline': self.tagline,
            'default_sources': self.default_sources,
            'default_filters': self.default_filters,
            'default_cadence': self.default_cadence,
            'default_tone': self.default_tone,
            'configurable_options': self.configurable_options,
            'guardrails': self.guardrails,
            'allow_customization': self.allow_customization,
            'is_featured': self.is_featured,
            'times_used': self.times_used,
        }

    def __repr__(self):
        return f'<BriefTemplate {self.name}>'


class InputSource(db.Model):
    """
    Generalized source model for user-defined sources.
    Extends NewsSource concept to support RSS, URLs, uploads, etc.

    Phase 1-2: Coexists with NewsSource (NewsSource for system, InputSource for users)
    Phase 3+: NewsSource will migrate to InputSource (owner_type='system')
    """
    __tablename__ = 'input_source'
    __table_args__ = (
        db.Index('idx_input_source_owner', 'owner_type', 'owner_id'),
        db.Index('idx_input_source_type', 'type'),
        db.Index('idx_input_source_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Ownership
    owner_type = db.Column(db.String(20), nullable=False)  # 'user' | 'org' | 'system'
    owner_id = db.Column(db.Integer, nullable=True)  # User.id or CompanyProfile.id (nullable for system)

    # Source config
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50), nullable=False)  # 'rss' | 'url_list' | 'webpage' | 'upload' | 'substack' | 'x'
    config_json = db.Column(db.JSON)  # Type-specific config (e.g., {'urls': [...]} for url_list)

    # For uploads
    storage_key = db.Column(db.String(500), nullable=True)  # Replit Object Storage key
    storage_url = db.Column(db.String(500), nullable=True)
    extracted_text = db.Column(db.Text, nullable=True)  # Extracted text from PDF/DOCX

    # Status (for async extraction)
    status = db.Column(db.String(30), default='ready')  # 'ready' | 'extracting' | 'failed'
    extraction_error = db.Column(db.Text, nullable=True)  # Error message if extraction failed

    # Source metadata
    enabled = db.Column(db.Boolean, default=True)
    last_fetched_at = db.Column(db.DateTime, nullable=True)
    fetch_error_count = db.Column(db.Integer, default=0)

    # Provenance & Editorial Control (unified ingestion architecture)
    origin_type = db.Column(db.String(20), default='user')  # 'admin' | 'template' | 'user'
    content_domain = db.Column(db.String(50), nullable=True)  # 'news' | 'sport' | 'tech' | 'finance' | 'culture' | 'science' | 'politics'
    allowed_channels = db.Column(JSONB, default=lambda: ['user_briefings'])  # ['daily_brief', 'trending', 'user_briefings']
    political_leaning = db.Column(db.Float, nullable=True)  # -1.0 (left) to 1.0 (right), null = unknown
    is_verified = db.Column(db.Boolean, default=False)  # Admin-verified quality source

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    ingested_items = db.relationship('IngestedItem', backref='source', lazy='dynamic', cascade='all, delete-orphan')
    briefing_sources = db.relationship('BriefingSource', backref=db.backref('input_source', overlaps='source,briefing_associations'), lazy='dynamic', overlaps='source,briefing_associations')

    def to_dict(self):
        return {
            'id': self.id,
            'owner_type': self.owner_type,
            'owner_id': self.owner_id,
            'name': self.name,
            'type': self.type,
            'config_json': self.config_json,
            'status': self.status,
            'enabled': self.enabled,
            'origin_type': self.origin_type,
            'content_domain': self.content_domain,
            'allowed_channels': self.allowed_channels,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def can_be_used_in(self, channel: str) -> bool:
        """Check if this source is allowed in a specific channel."""
        if not self.allowed_channels:
            return channel == 'user_briefings'
        return channel in self.allowed_channels

    def __repr__(self):
        return f'<InputSource {self.name} ({self.type})>'


class IngestedItem(db.Model):
    """
    Individual items ingested from sources.
    Similar to NewsArticle but more generic (supports uploads, URLs, etc.).
    """
    __tablename__ = 'ingested_item'
    __table_args__ = (
        db.UniqueConstraint('source_id', 'content_hash', name='uq_source_content_hash'),
        db.Index('idx_ingested_source_fetched', 'source_id', 'fetched_at'),
        db.Index('idx_ingested_published', 'published_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('input_source.id', ondelete='CASCADE'), nullable=False)

    # Content
    title = db.Column(db.String(500), nullable=False)
    url = db.Column(db.String(1000), nullable=True)  # Nullable for uploads
    source_name = db.Column(db.String(200))  # Denormalized for performance

    # Timing
    published_at = db.Column(db.DateTime, nullable=True)  # From source
    fetched_at = db.Column(db.DateTime, default=utcnow_naive)

    # Content
    content_text = db.Column(db.Text)  # Extracted text
    content_hash = db.Column(db.String(64), nullable=False)  # SHA-256 for deduplication
    metadata_json = db.Column(db.JSON)  # Author, tags, etc.

    # For uploads
    storage_key = db.Column(db.String(500), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    def to_dict(self):
        return {
            'id': self.id,
            'source_id': self.source_id,
            'title': self.title,
            'url': self.url,
            'source_name': self.source_name,
            'published_at': self.published_at.isoformat() if self.published_at else None,
            'fetched_at': self.fetched_at.isoformat() if self.fetched_at else None,
            'content_text': self.content_text[:500] if self.content_text else None,  # Truncate for API
            'metadata_json': self.metadata_json,
        }

    def __repr__(self):
        return f'<IngestedItem {self.title[:50]}>'


class Briefing(db.Model):
    """
    Multi-tenant brief configuration.
    Each user/org can have multiple briefings with custom sources and schedules.
    """
    __tablename__ = 'briefing'
    __table_args__ = (
        db.Index('idx_briefing_owner', 'owner_type', 'owner_id'),
        db.Index('idx_briefing_status', 'status'),
        db.Index('idx_briefing_visibility', 'visibility'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Ownership
    owner_type = db.Column(db.String(20), nullable=False)  # 'user' | 'org'
    owner_id = db.Column(db.Integer, nullable=False)  # User.id or CompanyProfile.id

    # Configuration
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    theme_template_id = db.Column(db.Integer, db.ForeignKey('brief_template.id'), nullable=True)

    # Schedule
    cadence = db.Column(db.String(20), default='daily')  # 'daily' | 'weekly'
    timezone = db.Column(db.String(50), default='UTC')  # e.g., 'Europe/London', 'America/New_York'
    preferred_send_hour = db.Column(db.Integer, default=18)  # 0-23 (hour of day)
    preferred_send_minute = db.Column(db.Integer, default=0, nullable=False)  # 0-59 (minute of hour)

    # Workflow
    mode = db.Column(db.String(20), default='auto_send')  # 'auto_send' | 'approval_required'

    # Visibility
    visibility = db.Column(db.String(20), default='private')  # 'private' | 'org_only' | 'public'

    # Status
    status = db.Column(db.String(20), default='active')  # 'active' | 'paused'

    # AI Generation Settings
    custom_prompt = db.Column(db.Text, nullable=True)  # Custom instructions for AI generation
    tone = db.Column(db.String(50), default='calm_neutral')  # 'calm_neutral' | 'formal' | 'conversational'
    include_summaries = db.Column(db.Boolean, default=True)  # Include bullet summaries
    max_items = db.Column(db.Integer, default=10)  # Max stories per brief

    # Guardrails (inherited from template, if any)
    # JSON with keys: no_outrage_framing, no_predictions, require_attribution,
    # perspective_balance, structure_template, visibility_locked
    guardrails = db.Column(JSONB, nullable=True)

    # User customization settings
    # Topic preferences: {"football": 3, "cricket": 1, "tennis": 2} - higher = more priority
    topic_preferences = db.Column(JSONB, nullable=True)
    # Content filters: {"include_keywords": ["premier league"], "exclude_keywords": ["betting"]}
    filters_json = db.Column(JSONB, nullable=True)

    # Visual Branding
    logo_url = db.Column(db.String(500), nullable=True)  # Logo image URL
    accent_color = db.Column(db.String(20), default='#3B82F6')  # Hex color for accents
    header_text = db.Column(db.String(200), nullable=True)  # Custom header text

    # Email config (for orgs)
    from_name = db.Column(db.String(200), nullable=True)
    from_email = db.Column(db.String(255), nullable=True)  # Must be from verified domain
    sending_domain_id = db.Column(db.Integer, db.ForeignKey('sending_domain.id', ondelete='SET NULL'), nullable=True)

    # Slack integration
    slack_webhook_url = db.Column(db.String(500), nullable=True)  # Slack incoming webhook URL
    slack_channel_name = db.Column(db.String(100), nullable=True)  # For display purposes

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    template = db.relationship('BriefTemplate', backref='briefings')
    sources = db.relationship('BriefingSource', backref='briefing', cascade='all, delete-orphan')
    runs = db.relationship('BriefRun', backref='briefing', lazy='dynamic', order_by='BriefRun.scheduled_at.desc()', passive_deletes=True)
    recipients = db.relationship('BriefRecipient', backref='briefing', lazy='dynamic', cascade='all, delete-orphan')
    sending_domain = db.relationship('SendingDomain', backref='briefings')

    @property
    def source_count(self):
        """Number of sources attached to this briefing."""
        return len(self.sources)

    @property
    def recipient_count(self):
        """Number of active recipients."""
        return self.recipients.filter_by(status='active').count()

    def to_dict(self):
        return {
            'id': self.id,
            'owner_type': self.owner_type,
            'owner_id': self.owner_id,
            'name': self.name,
            'description': self.description,
            'theme_template_id': self.theme_template_id,
            'cadence': self.cadence,
            'timezone': self.timezone,
            'preferred_send_hour': self.preferred_send_hour,
            'mode': self.mode,
            'visibility': self.visibility,
            'status': self.status,
            'guardrails': self.guardrails,
            'source_count': self.source_count,
            'recipient_count': self.recipient_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self):
        return f'<Briefing {self.name} ({self.owner_type}:{self.owner_id})>'


class BriefingSource(db.Model):
    """
    Many-to-many relationship between Briefings and InputSources.
    """
    __tablename__ = 'briefing_source'

    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id', ondelete='CASCADE'), primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('input_source.id', ondelete='CASCADE'), primary_key=True)
    priority = db.Column(db.Integer, default=1)  # 1-5, higher = more important
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationship to access source details
    source = db.relationship('InputSource', backref=db.backref('briefing_associations', overlaps='briefing_sources,input_source'), overlaps='briefing_sources,input_source')

    def __repr__(self):
        return f'<BriefingSource briefing:{self.briefing_id} source:{self.source_id} priority:{self.priority}>'


class BriefRun(db.Model):
    """
    Execution instance of a briefing.
    Each scheduled run creates a BriefRun (similar to DailyBrief but per-briefing).
    """
    __tablename__ = 'brief_run'
    __table_args__ = (
        db.Index('idx_brief_run_briefing', 'briefing_id'),
        db.Index('idx_brief_run_status', 'status'),
        db.Index('idx_brief_run_scheduled', 'scheduled_at'),
        db.Index('idx_brief_run_status_claimed', 'status', 'claimed_at'),
        # Prevent duplicate runs for same briefing at same time (race condition protection)
        db.UniqueConstraint('briefing_id', 'scheduled_at', name='uq_brief_run_briefing_scheduled'),
    )

    id = db.Column(db.Integer, primary_key=True)
    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id', ondelete='CASCADE'), nullable=False)

    # Status workflow
    status = db.Column(db.String(30), default='generated_draft')  # 'generated_draft' | 'awaiting_approval' | 'approved' | 'sent' | 'failed'

    # Content (markdown + HTML)
    draft_markdown = db.Column(db.Text)
    draft_html = db.Column(db.Text)
    approved_markdown = db.Column(db.Text, nullable=True)
    approved_html = db.Column(db.Text, nullable=True)

    # Approval tracking
    approved_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)

    # Timing
    scheduled_at = db.Column(db.DateTime, nullable=False)  # When it should run
    generated_at = db.Column(db.DateTime, nullable=True)
    sent_at = db.Column(db.DateTime, nullable=True)

    # Send claim tracking (for preventing duplicate sends)
    claimed_at = db.Column(db.DateTime, nullable=True)  # When a process claimed this for sending
    send_attempts = db.Column(db.Integer, default=0)  # Number of send attempts
    failure_reason = db.Column(db.String(500), nullable=True)  # Why the run failed (e.g. no recipients)

    # Analytics tracking
    emails_sent = db.Column(db.Integer, default=0)  # Count of emails sent
    unique_opens = db.Column(db.Integer, default=0)  # Count of unique email opens
    total_clicks = db.Column(db.Integer, default=0)  # Count of link clicks
    slack_sent = db.Column(db.Boolean, default=False)  # Whether Slack notification was sent

    # Relationships
    items = db.relationship('BriefRunItem', backref='run', cascade='all, delete-orphan', order_by='BriefRunItem.position')
    approved_by = db.relationship('User', backref='approved_brief_runs', foreign_keys=[approved_by_user_id])
    edits = db.relationship('BriefEdit', backref='brief_run', lazy='dynamic', order_by='BriefEdit.created_at.desc()', passive_deletes=True)
    opens = db.relationship('BriefEmailOpen', backref='brief_run', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'briefing_id': self.briefing_id,
            'status': self.status,
            'scheduled_at': self.scheduled_at.isoformat() if self.scheduled_at else None,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'approved_by_user_id': self.approved_by_user_id,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'item_count': len(self.items),
        }

    def __repr__(self):
        return f'<BriefRun {self.id} ({self.status})>'


class BriefRunItem(db.Model):
    """
    Individual items within a BriefRun.
    Similar to BriefItem but for BriefRun.
    """
    __tablename__ = 'brief_run_item'
    __table_args__ = (
        db.Index('idx_brief_run_item_run', 'brief_run_id'),
        db.UniqueConstraint('brief_run_id', 'position', name='uq_brief_run_position'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)
    position = db.Column(db.Integer, nullable=False)  # Display order

    # Source reference (optional - can reference IngestedItem or TrendingTopic)
    # SET NULL on delete to prevent orphaned references when source items are cleaned up
    ingested_item_id = db.Column(db.Integer, db.ForeignKey('ingested_item.id', ondelete='SET NULL'), nullable=True)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='SET NULL'), nullable=True)

    # Generated content (LLM-created)
    headline = db.Column(db.String(200))
    summary_bullets = db.Column(db.JSON)  # ['bullet1', 'bullet2', 'bullet3']
    content_markdown = db.Column(db.Text)
    content_html = db.Column(db.Text)
    source_name = db.Column(db.String(200), nullable=True)  # Denormalized for display
    source_url = db.Column(db.String(1000), nullable=True)  # Link to original article

    # Content metadata for scoring and diversity
    topic_category = db.Column(db.String(100), nullable=True)  # Category/topic of the item
    sentiment_score = db.Column(db.Float, nullable=True)  # -1.0 to 1.0 (negative to positive)

    # Engagement tracking (denormalized for faster queries)
    click_count = db.Column(db.Integer, default=0)  # Number of clicks on this item

    # Selection metadata (for learning/debugging)
    selection_score = db.Column(db.Float, nullable=True)  # Score at time of selection

    # Deeper context for "Want more detail?" feature
    deeper_context = db.Column(db.Text)  # Extended analysis and background

    # Audio/TTS integration (XTTS v2 - open source)
    audio_url = db.Column(db.String(500))  # URL to generated audio file
    audio_voice_id = db.Column(db.String(100))  # XTTS voice ID used
    audio_generated_at = db.Column(db.DateTime)  # When audio was generated

    # Metadata
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    ingested_item = db.relationship('IngestedItem', backref='brief_run_items')
    trending_topic = db.relationship('TrendingTopic', backref='brief_run_items')

    def to_dict(self):
        return {
            'id': self.id,
            'position': self.position,
            'headline': self.headline,
            'summary_bullets': self.summary_bullets,
            'content_markdown': self.content_markdown,
            'deeper_context': self.deeper_context,
            'audio_url': self.audio_url,
            'audio_voice_id': self.audio_voice_id,
        }

    def __repr__(self):
        return f'<BriefRunItem {self.position}. {self.headline}>'


class BriefEmailOpen(db.Model):
    """
    Tracks individual email opens for analytics.
    """
    __tablename__ = 'brief_email_open'
    __table_args__ = (
        db.Index('idx_brief_email_open_run', 'brief_run_id'),
        db.Index('idx_brief_email_open_recipient', 'recipient_email'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)
    recipient_email = db.Column(db.String(255), nullable=True)  # Hashed or anonymized
    opened_at = db.Column(db.DateTime, default=utcnow_naive)
    user_agent = db.Column(db.String(500), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)

    def __repr__(self):
        return f'<BriefEmailOpen {self.id} for run {self.brief_run_id}>'


class BriefEmailSend(db.Model):
    """
    Tracks individual email sends to prevent duplicate deliveries.

    Uses a two-phase commit pattern:
    1. Before send: INSERT with status='claimed' (claims the recipient)
    2. After send: UPDATE to status='sent' (confirms delivery)

    This prevents duplicates even if the process crashes between send and record.

    Status flow:
    - 'claimed' -> 'sent' (success)
    - 'claimed' -> 'failed' (can retry up to MAX_SEND_ATTEMPTS)
    - 'failed' -> 'claimed' -> 'sent' (retry succeeded)
    - 'failed' -> 'permanently_failed' (exceeded MAX_SEND_ATTEMPTS)
    """
    __tablename__ = 'brief_email_send'
    __table_args__ = (
        db.Index('idx_brief_email_send_run', 'brief_run_id'),
        db.Index('idx_brief_email_send_recipient', 'recipient_id'),
        db.Index('idx_brief_email_send_run_status', 'brief_run_id', 'status'),  # For cleanup queries
        # Unique constraint: each recipient can only receive each brief_run once
        db.UniqueConstraint('brief_run_id', 'recipient_id', name='uq_brief_run_recipient_send'),
    )

    # Maximum number of send attempts before marking as permanently failed
    MAX_SEND_ATTEMPTS = 3

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('brief_recipient.id', ondelete='CASCADE'), nullable=False)
    status = db.Column(db.String(20), default='sent')  # 'claimed' | 'sent' | 'failed' | 'permanently_failed'
    claimed_at = db.Column(db.DateTime, default=utcnow_naive)  # When claim was created
    sent_at = db.Column(db.DateTime, nullable=True)  # When email was actually sent
    resend_id = db.Column(db.String(100), nullable=True)  # Resend message ID for tracking
    attempt_count = db.Column(db.Integer, default=1)  # Number of send attempts
    failure_reason = db.Column(db.String(500), nullable=True)  # Why the send failed (for debugging)

    # Relationships
    brief_run = db.relationship('BriefRun', backref='email_sends')
    recipient = db.relationship('BriefRecipient', backref='email_sends')

    def __repr__(self):
        return f'<BriefEmailSend run={self.brief_run_id} recipient={self.recipient_id} status={self.status}>'


class BriefLinkClick(db.Model):
    """
    Tracks individual link clicks for analytics.
    """
    __tablename__ = 'brief_link_click'
    __table_args__ = (
        db.Index('idx_brief_link_click_run', 'brief_run_id'),
        db.Index('idx_brief_link_click_item', 'brief_run_item_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)
    brief_run_item_id = db.Column(db.Integer, db.ForeignKey('brief_run_item.id', ondelete='SET NULL'), nullable=True)
    recipient_email = db.Column(db.String(255), nullable=True)  # Hashed or anonymized
    target_url = db.Column(db.String(2000), nullable=False)
    link_type = db.Column(db.String(50), nullable=True)  # 'article', 'view', 'internal'
    clicked_at = db.Column(db.DateTime, default=utcnow_naive)
    user_agent = db.Column(db.String(500), nullable=True)

    def __repr__(self):
        return f'<BriefLinkClick {self.id} for run {self.brief_run_id}>'


class BriefRecipient(db.Model):
    """
    Per-briefing recipient list.
    Similar to DailyBriefSubscriber but per-briefing (not global).
    """
    __tablename__ = 'brief_recipient'
    __table_args__ = (
        db.UniqueConstraint('briefing_id', 'email', name='uq_briefing_recipient'),
        db.Index('idx_brief_recipient_status', 'briefing_id', 'status'),
        db.Index('idx_brief_recipient_token', 'magic_token'),
    )

    id = db.Column(db.Integer, primary_key=True)
    briefing_id = db.Column(db.Integer, db.ForeignKey('briefing.id', ondelete='CASCADE'), nullable=False)

    email = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(200), nullable=True)

    status = db.Column(db.String(20), default='active')  # 'active' | 'unsubscribed'
    unsubscribed_at = db.Column(db.DateTime, nullable=True)

    # Magic link auth (reuse pattern from DailyBriefSubscriber)
    magic_token = db.Column(db.String(64), unique=True, nullable=True)
    magic_token_expires_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    def generate_magic_token(self, expires_hours=48):
        """Generate a new magic link token with expiry"""
        import secrets
        from datetime import timedelta
        self.magic_token = secrets.token_urlsafe(32)
        self.magic_token_expires_at = utcnow_naive() + timedelta(hours=expires_hours)
        return self.magic_token

    def is_magic_token_valid(self) -> bool:
        """Check if magic token is still valid (not expired)"""
        if not self.magic_token:
            return False
        if not self.magic_token_expires_at:
            # Legacy tokens without expiry - consider valid but should be regenerated
            return True
        return utcnow_naive() < self.magic_token_expires_at

    def to_dict(self):
        return {
            'id': self.id,
            'briefing_id': self.briefing_id,
            'email': self.email,
            'name': self.name,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<BriefRecipient {self.email} ({self.status})>'


class SendingDomain(db.Model):
    """
    Custom email domain verification for organizations.
    Uses Resend Domain API for verification.
    """
    __tablename__ = 'sending_domain'
    __table_args__ = (
        db.Index('idx_sending_domain_org', 'org_id'),
        db.Index('idx_sending_domain_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    org_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='CASCADE'), nullable=False)

    domain = db.Column(db.String(255), nullable=False, unique=True)  # e.g., 'client.org'
    status = db.Column(db.String(30), default='pending_verification')  # 'pending_verification' | 'verified' | 'failed'

    # Resend API data
    resend_domain_id = db.Column(db.String(255), nullable=True)
    dns_records_required = db.Column(db.JSON)  # SPF, DKIM, etc.

    verified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Relationships
    org = db.relationship('CompanyProfile', backref='sending_domains')

    def to_dict(self):
        return {
            'id': self.id,
            'org_id': self.org_id,
            'domain': self.domain,
            'status': self.status,
            'dns_records_required': self.dns_records_required,
            'verified_at': self.verified_at.isoformat() if self.verified_at else None,
        }

    def __repr__(self):
        return f'<SendingDomain {self.domain} ({self.status})>'


class BriefEdit(db.Model):
    """
    Edit history for approval workflow (optional versioning).
    Tracks edits made to BriefRun drafts.
    """
    __tablename__ = 'brief_edit'
    __table_args__ = (
        db.Index('idx_brief_edit_run', 'brief_run_id'),
        db.Index('idx_brief_edit_user', 'edited_by_user_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    brief_run_id = db.Column(db.Integer, db.ForeignKey('brief_run.id', ondelete='CASCADE'), nullable=False)

    edited_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content_markdown = db.Column(db.Text)
    content_html = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    edited_by = db.relationship('User', backref='brief_edits', foreign_keys=[edited_by_user_id])

    def to_dict(self):
        return {
            'id': self.id,
            'brief_run_id': self.brief_run_id,
            'edited_by_user_id': self.edited_by_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self):
        return f'<BriefEdit {self.id} by user:{self.edited_by_user_id}>'
