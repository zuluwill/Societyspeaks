"""
Trending / news-clustering models.

TrendingTopic — a clustered news topic ready for deliberation, with
civic/quality/audience scoring and a review workflow (pending → held
→ approved / published / merged / discarded).
TrendingTopicArticle — M:N join between TrendingTopic and NewsArticle,
carrying per-pair similarity scores.
DiscussionSourceArticle — M:N join between Discussion and NewsArticle,
preserving source attribution when a topic ships as a Discussion.
UpcomingEvent — admin-curated and article-extracted events powering the
brief's "Week Ahead" section.
SocialPostEngagement — engagement metrics (likes/reposts/replies/
impressions) for X and Bluesky posts, refreshed by a scheduler job.

Moved here from app/models.py as part of the models-split refactor.
Cross-domain relationships (User, Discussion, NewsArticle) use string
references; this submodule has no inbound model imports.
"""

from datetime import timedelta

from app import db
from app.lib.time import utcnow_naive


class TrendingTopic(db.Model):
    """
    A clustered news topic ready for deliberation.
    Multiple articles are grouped into one topic.
    """
    __tablename__ = 'trending_topic'
    __table_args__ = (
        db.Index('idx_topic_status', 'status'),
        db.Index('idx_topic_created', 'created_at'),
        db.Index('idx_topic_hold_until', 'hold_until'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # The neutral framing question for discussion
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)

    # Canonical tags for long-term merging (LLM-derived)
    # e.g., ["uk", "nhs", "junior_doctors", "pay"]
    canonical_tags = db.Column(db.JSON)
    topic_slug = db.Column(db.String(200))  # Normalized slug from tags

    # Scoring (separate scores per ChatGPT's advice)
    civic_score = db.Column(db.Float)  # 0-1: Is this worthwhile for civic discussion?
    quality_score = db.Column(db.Float)  # 0-1: Non-clickbait, fact density, multi-source
    audience_score = db.Column(db.Float)  # 0-1: Appeal to target podcast audience
    risk_flag = db.Column(db.Boolean, default=False)  # Culture war / sensitive / defamation risk
    risk_reason = db.Column(db.String(200))  # Why it's flagged as risky

    # Primary topic category for the discussion
    primary_topic = db.Column(db.String(50))  # Maps to Discussion.TOPICS

    # Geographic scope (derived from source articles)
    geographic_scope = db.Column(db.String(20), default='global')  # 'global', 'country', 'regional'
    geographic_countries = db.Column(db.String(500))  # Comma-separated: "UK, US" or None for global

    source_count = db.Column(db.Integer, default=0)  # Number of unique sources

    # Embedding for question-level deduplication (last 30 days)
    topic_embedding = db.Column(db.JSON)

    # Workflow status
    status = db.Column(db.String(20), default='pending')
    # pending -> held -> pending_review -> approved -> published
    # pending -> held -> pending_review -> discarded
    # pending -> held -> pending_review -> merged

    hold_until = db.Column(db.DateTime)  # Cooldown window (30-90 mins)

    # If merged into another topic/discussion
    merged_into_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id'), nullable=True)
    merged_into_discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)

    # Generated seed statements (JSON array)
    seed_statements = db.Column(db.JSON)  # [{"content": "...", "position": "pro/con/neutral"}]

    # Timestamps
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    published_at = db.Column(db.DateTime)

    # Link to created discussion (if published)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True)

    # Relationships
    articles = db.relationship('TrendingTopicArticle', backref='topic', lazy='dynamic')
    merged_into_topic = db.relationship('TrendingTopic', remote_side=[id], backref='merged_topics')
    merged_into_discussion = db.relationship('Discussion', foreign_keys=[merged_into_discussion_id], backref='merged_topics')
    created_discussion = db.relationship('Discussion', foreign_keys=[discussion_id], backref='source_topic')
    reviewer = db.relationship('User', backref='reviewed_topics')

    HIGH_TRUST_SOURCES = [
        'bbc news', 'the guardian', 'financial times', 'the economist',
        'foreign affairs', 'the atlantic', 'the new yorker', 'bloomberg',
        'the rest is politics', 'the news agents', 'all-in podcast',
        'triggernometry', 'the tim ferriss show', 'diary of a ceo', 'modern wisdom',
        'unherd', 'politico eu', 'the telegraph', 'the independent', 'techcrunch', 'axios'
    ]

    @property
    def is_high_confidence(self):
        """
        High confidence for publishing:
        - From a trusted source
        - Has civic relevance (worth discussing)
        - Not flagged as risky
        """
        return (
            self.has_trusted_source and
            (self.civic_score or 0) >= 0.5 and
            not self.risk_flag
        )

    @property
    def has_trusted_source(self):
        """Check if any article is from a high-trust source."""
        for ta in self.articles:
            if ta.article and ta.article.source:
                if ta.article.source.name.lower() in self.HIGH_TRUST_SOURCES:
                    return True
        return False

    @property
    def should_auto_publish(self):
        """
        Auto-publish criteria:
        - Has civic relevance (worth discussing)
        - Not flagged as risky
        All curated sources are trusted by default.
        """
        return (
            (self.civic_score or 0) >= 0.5 and
            not self.risk_flag
        )

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'canonical_tags': self.canonical_tags,
            'civic_score': self.civic_score,
            'quality_score': self.quality_score,
            'risk_flag': self.risk_flag,
            'risk_reason': self.risk_reason,
            'source_count': self.source_count,
            'status': self.status,
            'hold_until': self.hold_until.isoformat() if self.hold_until else None,
            'seed_statements': self.seed_statements,
            'is_high_confidence': self.is_high_confidence,
            'created_at': self.created_at.isoformat(),
            'articles': [ta.article.title for ta in self.articles if ta.article]
        }

    def __repr__(self):
        return f'<TrendingTopic {self.title[:50]}...>'


class TrendingTopicArticle(db.Model):
    """
    Join table linking TrendingTopic to NewsArticle.
    Allows many-to-many with additional metadata.

    Foreign Key Behavior:
    - topic_id: CASCADE - auto-delete when topic is deleted
    - article_id: CASCADE - auto-delete when article is deleted
    """
    __tablename__ = 'trending_topic_article'
    __table_args__ = (
        db.Index('idx_tta_topic', 'topic_id'),
        db.Index('idx_tta_article', 'article_id'),
        db.UniqueConstraint('topic_id', 'article_id', name='uq_topic_article'),
    )

    id = db.Column(db.Integer, primary_key=True)
    topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='CASCADE'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id', ondelete='CASCADE'), nullable=False)

    # When this article was added to the topic
    added_at = db.Column(db.DateTime, default=utcnow_naive)

    # Similarity score to the topic centroid
    similarity_score = db.Column(db.Float)

    # Relationships
    article = db.relationship('NewsArticle', backref='topic_associations')


class DiscussionSourceArticle(db.Model):
    """
    Join table linking Discussion to NewsArticle for news-based discussions.
    Preserves source attribution when topics are published as discussions.

    Foreign Key Behavior:
    - discussion_id: CASCADE - auto-delete when discussion is deleted
    - article_id: SET NULL - preserve link record but clear article reference when article deleted
    """
    __tablename__ = 'discussion_source_article'
    __table_args__ = (
        db.Index('idx_dsa_discussion', 'discussion_id'),
        db.Index('idx_dsa_article', 'article_id'),
        db.UniqueConstraint('discussion_id', 'article_id', name='uq_discussion_article'),
    )

    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False)
    article_id = db.Column(db.Integer, db.ForeignKey('news_article.id', ondelete='CASCADE'), nullable=False)
    added_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    discussion = db.relationship('Discussion', backref='source_article_links')
    article = db.relationship('NewsArticle', backref='discussion_links')


class UpcomingEvent(db.Model):
    """
    Upcoming events for the "Week Ahead" brief section.

    Events can be:
    - Auto-extracted from news articles (source='article')
    - Admin-curated via the admin panel (source='admin')
    - Imported from external calendars (source='api')

    Events are surfaced in the brief's "The Week Ahead" section,
    showing readers what's coming up in the next 7 days.
    """
    __tablename__ = 'upcoming_event'
    __table_args__ = (
        db.Index('idx_upcoming_event_date', 'event_date'),
        db.Index('idx_upcoming_event_status', 'status'),
    )

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text)  # One-sentence context
    event_date = db.Column(db.Date, nullable=False)
    event_time = db.Column(db.String(50))  # Optional: "14:00 UTC" or "All day"
    category = db.Column(db.String(50))  # politics, economy, science, society, etc.
    region = db.Column(db.String(50))  # asia_pacific, europe, americas, middle_east_africa, global
    importance = db.Column(db.String(10), default='medium')  # high, medium, low

    # Source tracking
    source = db.Column(db.String(20), default='admin')  # admin, article, api
    source_url = db.Column(db.String(500))  # Link to official page/announcement
    source_article_id = db.Column(db.Integer, db.ForeignKey('news_article.id'), nullable=True)

    # Status
    status = db.Column(db.String(20), default='active')  # active, used, cancelled, past

    # Tracking
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Relationships
    source_article = db.relationship('NewsArticle', backref='upcoming_events')
    creator = db.relationship('User', backref='created_events')

    @classmethod
    def get_upcoming(cls, days_ahead=7, limit=10):
        """Get upcoming events within the next N days."""
        from datetime import date as date_type
        today = date_type.today()
        cutoff = today + timedelta(days=days_ahead)
        return cls.query.filter(
            cls.event_date >= today,
            cls.event_date <= cutoff,
            cls.status == 'active'
        ).order_by(cls.event_date.asc(), cls.importance.desc()).limit(limit).all()

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'event_date': self.event_date.isoformat(),
            'event_time': self.event_time,
            'category': self.category,
            'region': self.region,
            'importance': self.importance,
            'source': self.source,
            'source_url': self.source_url,
        }

    def __repr__(self):
        return f'<UpcomingEvent {self.event_date}: {self.title[:50]}>'


class SocialPostEngagement(db.Model):
    """
    Tracks engagement metrics for social media posts over time.

    Stores likes, retweets/reposts, replies, and impressions for posts
    on X and Bluesky. Updated periodically by scheduler job.
    """
    __tablename__ = 'social_post_engagement'

    id = db.Column(db.Integer, primary_key=True)

    # Link to discussion (nullable for non-discussion posts like daily brief)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=True, index=True)
    discussion = db.relationship('Discussion', backref=db.backref('social_engagements', lazy='dynamic'))

    # Platform and post identifier
    platform = db.Column(db.String(20), nullable=False)  # 'x' or 'bluesky'
    post_id = db.Column(db.String(500), nullable=False)  # Tweet ID or Bluesky URI

    # Content type for tracking different post types
    content_type = db.Column(db.String(50), nullable=False, default='discussion')  # 'discussion', 'daily_question', 'daily_brief', 'weekly_insights'

    # Hook variant used (for A/B testing)
    hook_variant = db.Column(db.String(50), nullable=True)

    # Engagement metrics
    likes = db.Column(db.Integer, default=0)
    reposts = db.Column(db.Integer, default=0)  # Retweets on X, reposts on Bluesky
    replies = db.Column(db.Integer, default=0)
    quotes = db.Column(db.Integer, default=0)
    impressions = db.Column(db.Integer, default=0)  # Views/impressions if available
    clicks = db.Column(db.Integer, default=0)  # Link clicks if available

    # Timestamps
    posted_at = db.Column(db.DateTime, nullable=False)
    last_updated = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Unique constraint on platform + post_id
    __table_args__ = (
        db.UniqueConstraint('platform', 'post_id', name='uq_platform_post_id'),
    )

    @property
    def total_engagement(self) -> int:
        """Total engagement (likes + reposts + replies + quotes)."""
        return (self.likes or 0) + (self.reposts or 0) + (self.replies or 0) + (self.quotes or 0)

    @property
    def engagement_rate(self) -> float:
        """Engagement rate as percentage of impressions."""
        if not self.impressions or self.impressions == 0:
            return 0.0
        return (self.total_engagement / self.impressions) * 100

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'platform': self.platform,
            'post_id': self.post_id,
            'content_type': self.content_type,
            'hook_variant': self.hook_variant,
            'likes': self.likes,
            'reposts': self.reposts,
            'replies': self.replies,
            'quotes': self.quotes,
            'impressions': self.impressions,
            'clicks': self.clicks,
            'total_engagement': self.total_engagement,
            'engagement_rate': self.engagement_rate,
            'posted_at': self.posted_at.isoformat() if self.posted_at else None,
            'last_updated': self.last_updated.isoformat() if self.last_updated else None,
        }
