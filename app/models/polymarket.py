"""
Polymarket integration models.

Caches Polymarket market metadata and tracks automated matches between
SocietySpeaks TrendingTopic rows and PolymarketMarket rows. Moved here
from app/models.py as part of the models-split refactor.

The TrendingTopic relationship at the bottom of TopicMarketMatch is a
string reference ('TrendingTopic') so this submodule does NOT import
app.models.trending — SQLAlchemy resolves the reference at mapper-
configuration time once every submodule has been loaded by
app/models/__init__.py.
"""

from typing import Optional

from app import db
from app.lib.time import utcnow_naive


class PolymarketMarket(db.Model):
    """
    Cached Polymarket market data.

    Sync Strategy:
    - Full sync every 2 hours (all active markets)
    - Price refresh every 5 minutes (tracked markets only)
    - Embedding generation on first sync (for matching)

    Quality Thresholds:
    - MIN_VOLUME_24H: $1,000 minimum daily volume
    - MIN_LIQUIDITY: $5,000 minimum liquidity
    - Markets below thresholds excluded from matching
    """
    __tablename__ = 'polymarket_market'
    __table_args__ = (
        db.Index('idx_pm_market_condition', 'condition_id'),
        db.Index('idx_pm_market_category', 'category'),
        db.Index('idx_pm_market_active', 'is_active'),
        db.Index('idx_pm_market_slug', 'slug'),
        db.Index('idx_pm_market_quality', 'is_active', 'volume_24h', 'liquidity'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # Polymarket Identifiers
    condition_id = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(200))
    clob_token_ids = db.Column(db.JSON)  # For CLOB API price fetching

    # Content
    question = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100))  # politics, economics, tech...
    tags = db.Column(db.JSON)  # ['uk', 'election', 'labour'] - for keyword matching

    # Automated Matching
    question_embedding = db.Column(db.JSON)  # Vector for similarity search

    # Outcomes & Pricing
    outcomes = db.Column(db.JSON)  # [{"name": "Yes", "token_id": "...", "price": 0.78}, ...]
    probability = db.Column(db.Float)  # Primary outcome probability (0-1)
    probability_24h_ago = db.Column(db.Float)  # For calculating 24h change

    # Quality Signals (for filtering low-quality markets)
    volume_24h = db.Column(db.Float, default=0)
    volume_total = db.Column(db.Float, default=0)
    liquidity = db.Column(db.Float, default=0)
    trader_count = db.Column(db.Integer, default=0)

    # Lifecycle
    is_active = db.Column(db.Boolean, default=True)
    end_date = db.Column(db.DateTime)  # When market resolves
    resolution = db.Column(db.String(50))  # null until resolved, then 'Yes'/'No'/etc
    resolved_at = db.Column(db.DateTime)

    # Sync Tracking
    first_seen_at = db.Column(db.DateTime, default=utcnow_naive)
    last_synced_at = db.Column(db.DateTime)
    last_price_update_at = db.Column(db.DateTime)
    sync_failures = db.Column(db.Integer, default=0)  # Track consecutive failures

    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Quality Thresholds (class constants)
    MIN_VOLUME_24H = 1000    # $1k minimum daily volume
    MIN_LIQUIDITY = 5000     # $5k minimum liquidity
    HIGH_QUALITY_VOLUME = 10000  # $10k for "high quality" designation

    # Relationships
    topic_matches = db.relationship('TopicMarketMatch', backref='market', lazy='dynamic',
                                    cascade='all, delete-orphan')

    @property
    def is_high_quality(self) -> bool:
        """Market meets minimum quality thresholds for matching."""
        return (
            self.is_active and
            (self.volume_24h or 0) >= self.MIN_VOLUME_24H and
            (self.liquidity or 0) >= self.MIN_LIQUIDITY
        )

    @property
    def quality_tier(self) -> str:
        """Returns quality tier for filtering in UI."""
        if not self.is_active:
            return 'inactive'
        if (self.volume_24h or 0) >= self.HIGH_QUALITY_VOLUME:
            return 'high'
        if (self.volume_24h or 0) >= self.MIN_VOLUME_24H:
            return 'medium'
        return 'low'

    @property
    def change_24h(self) -> Optional[float]:
        """24-hour probability change. Returns None if no historical data."""
        if self.probability is not None and self.probability_24h_ago is not None:
            return self.probability - self.probability_24h_ago
        return None

    @property
    def change_24h_formatted(self) -> str:
        """Formatted 24h change for display."""
        change = self.change_24h
        if change is None:
            return "—"
        if change > 0:
            return f"+{change:.1%}"
        return f"{change:.1%}"

    @property
    def polymarket_url(self) -> str:
        """Direct link to market on Polymarket."""
        if self.slug:
            return f"https://polymarket.com/market/{self.slug}"
        return f"https://polymarket.com/markets/{self.condition_id}"

    def to_signal_dict(self) -> dict:
        """
        Returns market data formatted for BriefItem.market_signal JSON field.
        Used by brief generator when attaching market signal to items.
        """
        return {
            'market_id': self.id,
            'condition_id': self.condition_id,
            'question': self.question,
            'probability': self.probability,
            'change_24h': self.change_24h,
            'change_24h_formatted': self.change_24h_formatted,
            'volume_24h': self.volume_24h,
            'liquidity': self.liquidity,
            'trader_count': self.trader_count,
            'quality_tier': self.quality_tier,
            'url': self.polymarket_url,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'fetched_at': self.last_price_update_at.isoformat() if self.last_price_update_at else None
        }

    def to_dict(self) -> dict:
        """Full serialization for API responses."""
        return {
            'id': self.id,
            'condition_id': self.condition_id,
            'slug': self.slug,
            'question': self.question,
            'description': self.description,
            'category': self.category,
            'tags': self.tags,
            'outcomes': self.outcomes,
            'probability': self.probability,
            'change_24h': self.change_24h,
            'volume_24h': self.volume_24h,
            'volume_total': self.volume_total,
            'liquidity': self.liquidity,
            'trader_count': self.trader_count,
            'quality_tier': self.quality_tier,
            'is_active': self.is_active,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'resolution': self.resolution,
            'url': self.polymarket_url,
            'last_synced_at': self.last_synced_at.isoformat() if self.last_synced_at else None
        }

    def __repr__(self):
        q = self.question[:50] if self.question else 'Unknown'
        return f'<PolymarketMarket {self.id}: {q}...>'


class TopicMarketMatch(db.Model):
    """
    Automated match between TrendingTopic and PolymarketMarket.

    Matching Strategy:
    1. Category mapping (Society Speaks topic → Polymarket categories)
    2. Embedding similarity (topic embedding vs market question embedding)
    3. Keyword overlap fallback (canonical_tags vs market tags)

    Only high-confidence matches (similarity >= 0.75) are stored.
    Matches are refreshed when topics are created/updated.
    """
    __tablename__ = 'topic_market_match'
    __table_args__ = (
        db.Index('idx_tmm_topic', 'trending_topic_id'),
        db.Index('idx_tmm_market', 'market_id'),
        db.Index('idx_tmm_similarity', 'similarity_score'),
        db.UniqueConstraint('trending_topic_id', 'market_id', name='uq_topic_market'),
    )

    id = db.Column(db.Integer, primary_key=True)
    trending_topic_id = db.Column(db.Integer, db.ForeignKey('trending_topic.id', ondelete='CASCADE'),
                                   nullable=False)
    market_id = db.Column(db.Integer, db.ForeignKey('polymarket_market.id', ondelete='CASCADE'),
                          nullable=False)

    # Match Quality
    similarity_score = db.Column(db.Float, nullable=False)  # 0-1, higher = better match
    match_method = db.Column(db.String(20), nullable=False)  # 'embedding', 'keyword', 'category'

    # Snapshot at Match Time (for historical analysis)
    probability_at_match = db.Column(db.Float)
    volume_at_match = db.Column(db.Float)

    # Lifecycle
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    # Thresholds (class constants)
    SIMILARITY_THRESHOLD = 0.75  # Minimum similarity to create match
    HIGH_CONFIDENCE_THRESHOLD = 0.85  # High confidence matches

    # Relationships
    trending_topic = db.relationship('TrendingTopic', backref=db.backref('market_matches', lazy='dynamic'))

    @property
    def is_high_confidence(self) -> bool:
        return self.similarity_score >= self.HIGH_CONFIDENCE_THRESHOLD

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'trending_topic_id': self.trending_topic_id,
            'market_id': self.market_id,
            'similarity_score': self.similarity_score,
            'match_method': self.match_method,
            'is_high_confidence': self.is_high_confidence,
            'probability_at_match': self.probability_at_match,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<TopicMarketMatch topic={self.trending_topic_id} market={self.market_id} sim={self.similarity_score:.2f}>'
