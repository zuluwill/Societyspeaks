"""
News-ingestion models and their SQLAlchemy event listeners.

NewsSource — curated allowlist of trusted sources (with claiming
workflow for CompanyProfile verification, political-leaning metadata,
and per-source branding).
NewsArticle — individual articles pulled from those sources, with
scoring, geographic-scope fields, title embeddings, and a
normalized-URL layer used by the Partner API for lookup.

The three event listeners MUST live in this module alongside the
classes they hook:

  auto_generate_source_slug   — NewsSource, before_insert
  news_article_before_insert  — NewsArticle, before_insert
  news_article_before_update  — NewsArticle, before_update

If a listener is left behind in app/models_legacy.py while the target
class moves, SQLAlchemy silently stops firing the hook — the
verify_models_split.py probe catches this by inserting a NewsSource
and asserting the slug got populated.
"""

from sqlalchemy import event

from app import db
from app.lib.time import utcnow_naive
from app.models._base import generate_slug


class NewsSource(db.Model):
    """
    Curated allowlist of trusted news sources.
    Only fetch from sources on this list.
    """
    __tablename__ = 'news_source'
    __table_args__ = (
        db.Index('idx_news_source_active', 'is_active'),
        db.Index('idx_news_source_slug', 'slug', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False, unique=True)
    feed_url = db.Column(db.String(500), nullable=False)
    source_type = db.Column(db.String(20), default='rss')  # 'rss', 'api', 'guardian', 'nyt'
    country = db.Column(db.String(100))  # Country the source primarily covers (e.g., 'United Kingdom', 'United States')

    reputation_score = db.Column(db.Float, default=0.8)  # 0-1 scale
    is_active = db.Column(db.Boolean, default=True)

    # Political leaning for coverage analysis (-3 to +3: left to right, 0 = center)
    political_leaning = db.Column(db.Float)  # -2=Left, -1=Lean Left, 0=Center, 1=Lean Right, 2=Right
    leaning_source = db.Column(db.String(50))  # 'allsides', 'mbfc', 'adfontesmedia', 'manual'
    leaning_updated_at = db.Column(db.DateTime)

    last_fetched_at = db.Column(db.DateTime)
    fetch_error_count = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Source profile fields
    slug = db.Column(db.String(200), nullable=True)
    source_category = db.Column(db.String(50), default='newspaper')  # 'podcast', 'newspaper', 'magazine', 'broadcaster'

    # Basic branding (for unclaimed sources)
    logo_url = db.Column(db.String(500), nullable=True)
    website_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=True)

    # Claiming fields
    claim_status = db.Column(db.String(20), default='unclaimed')  # 'unclaimed', 'pending', 'approved', 'rejected'
    claimed_by_profile_id = db.Column(db.Integer, db.ForeignKey('company_profile.id', ondelete='SET NULL'), nullable=True)
    claimed_at = db.Column(db.DateTime, nullable=True)
    claim_requested_at = db.Column(db.DateTime, nullable=True)
    claim_requested_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    # Relationships
    articles = db.relationship('NewsArticle', backref='source', lazy='dynamic')
    claimed_by = db.relationship('CompanyProfile', backref='claimed_sources', foreign_keys=[claimed_by_profile_id])
    claim_requested_by = db.relationship('User', backref='source_claims', foreign_keys=[claim_requested_by_id])

    @property
    def is_claimed(self):
        """Check if source has been claimed and approved."""
        return self.claim_status == 'approved' and self.claimed_by_profile_id is not None

    @property
    def display_logo(self):
        """
        Return logo info as a dict for template rendering.

        Returns:
            dict with 'type' ('profile' or 'url') and 'src' (filename or URL),
            or None if no logo is available.
        """
        if self.is_claimed and self.claimed_by and self.claimed_by.logo:
            return {'type': 'profile', 'src': self.claimed_by.logo}
        if self.logo_url:
            return {'type': 'url', 'src': self.logo_url}
        return None

    @property
    def display_description(self):
        """Return claimed profile description, or basic description."""
        if self.is_claimed and self.claimed_by and self.claimed_by.description:
            return self.claimed_by.description
        return self.description

    @property
    def political_leaning_label(self):
        """Return human-readable political leaning label based on AllSides ratings."""
        if self.political_leaning is None:
            return 'Unknown'
        if self.political_leaning <= -1.5:
            return 'Left'
        elif self.political_leaning <= -0.5:
            return 'Centre-Left'
        elif self.political_leaning <= 0.5:
            return 'Centre'
        elif self.political_leaning <= 1.5:
            return 'Centre-Right'
        else:
            return 'Right'

    def generate_slug(self):
        """Generate URL-friendly slug from name."""
        self.slug = generate_slug(self.name)

    def __repr__(self):
        return f'<NewsSource {self.name}>'


@event.listens_for(NewsSource, 'before_insert')
def auto_generate_source_slug(mapper, connection, target):
    """Auto-generate slug for new NewsSource records if not already set."""
    if not target.slug and target.name:
        base_slug = generate_slug(target.name)
        if not base_slug:
            import uuid
            base_slug = f"source-{uuid.uuid4().hex[:8]}"

        slug = base_slug
        suffix = 1
        while db.session.query(NewsSource).filter(NewsSource.slug == slug).first():
            slug = f"{base_slug}-{suffix}"
            suffix += 1
        target.slug = slug


class NewsArticle(db.Model):
    """
    Individual news articles fetched from sources.
    Stored separately for querying, deduplication, and auditing.

    URL Fields:
    - url: Raw URL from feed (preserved for audit/fallback)
    - normalized_url: Canonical form for partner API lookup (stripped tracking params, forced https, etc.)
    - url_hash: SHA-256 hash of normalized_url for fast indexing (first 32 chars)

    Lookup by article URL should use normalized_url, not url.
    See app/lib/url_normalizer.py for normalization rules.
    """
    __tablename__ = 'news_article'
    __table_args__ = (
        db.Index('idx_article_source', 'source_id'),
        db.Index('idx_article_fetched', 'fetched_at'),
        db.Index('idx_article_external_id', 'external_id'),
        db.Index('idx_article_normalized_url', 'normalized_url'),
        db.Index('idx_article_url_hash', 'url_hash'),
        db.UniqueConstraint('source_id', 'external_id', name='uq_source_article'),
    )

    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.Integer, db.ForeignKey('news_source.id'), nullable=False)

    external_id = db.Column(db.String(500))  # Source's unique ID for deduplication
    title = db.Column(db.String(500), nullable=False)
    summary = db.Column(db.Text)
    url = db.Column(db.String(1000), nullable=False)

    # Partner API lookup fields (see docstring above)
    normalized_url = db.Column(db.String(1000), nullable=True)  # Canonical URL for lookup
    url_hash = db.Column(db.String(32), nullable=True)  # SHA-256 hash for fast indexing

    published_at = db.Column(db.DateTime)
    fetched_at = db.Column(db.DateTime, default=utcnow_naive)

    # Scoring (computed at fetch time)
    sensationalism_score = db.Column(db.Float)  # 0-1: higher = more clickbait
    relevance_score = db.Column(db.Float)  # 0-1: discussion potential (1=policy debate, 0=product review)
    personal_relevance_score = db.Column(db.Float)  # 0-1: direct impact on daily life (economic/health/rights)

    # Geographic scope detection (AI-analyzed from content)
    geographic_scope = db.Column(db.String(20), default='unknown')  # 'global', 'regional', 'national', 'local', 'unknown'
    geographic_countries = db.Column(db.String(500))  # Comma-separated list of countries mentioned (e.g., "UK, US" or "Global")

    # Embedding for clustering (stored as JSON array of floats)
    title_embedding = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    def __repr__(self):
        return f'<NewsArticle {self.title[:50]}...>'

    def set_normalized_url(self):
        """
        Set normalized_url and url_hash from the raw url.
        Called automatically on before_insert and before_update events.
        """
        if self.url:
            from app.lib.url_normalizer import normalize_url, url_hash
            self.normalized_url = normalize_url(self.url)
            self.url_hash = url_hash(self.url) if self.normalized_url else None


@event.listens_for(NewsArticle, 'before_insert')
def news_article_before_insert(mapper, connection, target):
    """Automatically set normalized_url on insert."""
    target.set_normalized_url()


@event.listens_for(NewsArticle, 'before_update')
def news_article_before_update(mapper, connection, target):
    """Automatically update normalized_url if url changed."""
    # Only recalculate if url has changed
    from sqlalchemy.orm import object_session  # noqa: F401
    from sqlalchemy import inspect
    state = inspect(target)
    if state.attrs.url.history.has_changes():
        target.set_normalized_url()
