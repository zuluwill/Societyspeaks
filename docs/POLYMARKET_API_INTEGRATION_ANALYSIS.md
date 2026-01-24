# Polymarket API Integration - Implementation Plan

**Date:** January 24, 2026
**Status:** Approved for Implementation
**Decision:** Full automated integration as "Fourth Perspective" signal

---

## Executive Summary

Polymarket integration adds **prediction market data as a fourth perspective** alongside left/center/right media coverage. This surfaces collective economic conviction—what people are willing to bet on—as a complementary signal to editorial framing.

**Key Value Propositions:**
1. **"Market Signal"** in Daily Briefs - automated topic matching
2. **Consensus Divergence** - highlight when user votes differ from market expectations
3. **Polymarket as Source** - first-class source type for paid personalized briefs

**Core Principle:** Polymarket data is **additive and optional**. If Polymarket is unavailable, has no matching markets, or fails entirely, all briefing systems continue working normally.

---

## Architecture Overview

### System Integration Points

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        POLYMARKET DATA LAYER                            │
├─────────────────────────────────────────────────────────────────────────┤
│  PolymarketMarket (cached)  ←──  PolymarketService (API + sync jobs)   │
│         ↓                                                               │
│  question_embedding (for automated matching)                            │
└─────────────────────────────────────────────────────────────────────────┘
                    ↓                              ↓
    ┌───────────────────────────┐    ┌───────────────────────────────────┐
    │   FREE DAILY BRIEF        │    │   PAID PERSONALIZED BRIEFS        │
    ├───────────────────────────┤    ├───────────────────────────────────┤
    │ TrendingTopic             │    │ InputSource (type='polymarket')   │
    │       ↓                   │    │       ↓                           │
    │ TopicMarketMatch (auto)   │    │ User configures categories        │
    │       ↓                   │    │       ↓                           │
    │ BriefItem.market_signal   │    │ IngestedItem (from markets)       │
    │       ↓                   │    │       ↓                           │
    │ "Market Signal" section   │    │ BriefRunItem with market data     │
    └───────────────────────────┘    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────┐
    │   DAILY QUESTION          │
    ├───────────────────────────┤
    │ DailyQuestion             │
    │       ↓                   │
    │ polymarket_market_id (FK) │
    │       ↓                   │
    │ Consensus Divergence UI   │
    └───────────────────────────┘
```

### Graceful Degradation Guarantee

**Every integration point MUST handle these scenarios:**

| Scenario | Behavior |
|----------|----------|
| Polymarket API down | Use cached data; if cache empty, omit market signal |
| No matching market for topic | Omit market signal section; brief renders normally |
| Market has low volume/liquidity | Exclude from matching (quality threshold) |
| Market resolved/closed | Exclude from active matching |
| Rate limit exceeded | Use cached data; log warning |
| Network timeout | Use cached data; retry in next sync |
| Invalid API response | Log error; continue without market data |

**Implementation Pattern:**
```python
def get_market_signal_for_topic(topic_id: int) -> Optional[dict]:
    """
    Returns market signal data or None.
    NEVER raises exceptions - failures return None silently.
    """
    try:
        # ... fetch logic
        return market_signal
    except Exception as e:
        logger.warning(f"Market signal fetch failed for topic {topic_id}: {e}")
        return None  # Brief continues without market signal
```

---

## Data Models

### 1. PolymarketMarket

Cached market data from Polymarket API. Single source of truth for all market information.

```python
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
        db.Index('idx_pm_market_quality', 'is_active', 'volume_24h', 'liquidity'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # === Polymarket Identifiers ===
    condition_id = db.Column(db.String(100), unique=True, nullable=False)
    slug = db.Column(db.String(200), index=True)
    clob_token_ids = db.Column(db.JSON)  # For CLOB API price fetching

    # === Content ===
    question = db.Column(db.String(500), nullable=False)
    description = db.Column(db.Text)
    category = db.Column(db.String(100), index=True)  # politics, economics, tech...
    tags = db.Column(db.JSON)  # ['uk', 'election', 'labour'] - for keyword matching

    # === Automated Matching ===
    question_embedding = db.Column(db.JSON)  # Vector for similarity search
    # Note: Reuses existing embedding infrastructure from TrendingTopic

    # === Outcomes & Pricing ===
    outcomes = db.Column(db.JSON)  # [{"name": "Yes", "token_id": "...", "price": 0.78}, ...]
    probability = db.Column(db.Float)  # Primary outcome probability (0-1)
    probability_24h_ago = db.Column(db.Float)  # For calculating 24h change

    # === Quality Signals (for filtering low-quality markets) ===
    volume_24h = db.Column(db.Float, default=0)
    volume_total = db.Column(db.Float, default=0)
    liquidity = db.Column(db.Float, default=0)
    trader_count = db.Column(db.Integer, default=0)

    # === Lifecycle ===
    is_active = db.Column(db.Boolean, default=True, index=True)
    end_date = db.Column(db.DateTime)  # When market resolves
    resolution = db.Column(db.String(50))  # null until resolved, then 'Yes'/'No'/etc
    resolved_at = db.Column(db.DateTime)

    # === Sync Tracking ===
    first_seen_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_synced_at = db.Column(db.DateTime)
    last_price_update_at = db.Column(db.DateTime)
    sync_failures = db.Column(db.Integer, default=0)  # Track consecutive failures

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # === Quality Thresholds ===
    MIN_VOLUME_24H = 1000    # $1k minimum daily volume
    MIN_LIQUIDITY = 5000     # $5k minimum liquidity
    HIGH_QUALITY_VOLUME = 10000  # $10k for "high quality" designation

    # === Relationships ===
    topic_matches = db.relationship('TopicMarketMatch', backref='market', lazy='dynamic',
                                    cascade='all, delete-orphan')
    daily_question_links = db.relationship('DailyQuestion', backref='polymarket_market', lazy='dynamic')

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
            return f"https://polymarket.com/event/{self.slug}"
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
        return f'<PolymarketMarket {self.id}: {self.question[:50]}...>'
```

### 2. TopicMarketMatch

Automated links between TrendingTopics and relevant markets.

```python
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

    # === Match Quality ===
    similarity_score = db.Column(db.Float, nullable=False)  # 0-1, higher = better match
    match_method = db.Column(db.String(20), nullable=False)  # 'embedding', 'keyword', 'category'

    # === Snapshot at Match Time (for historical analysis) ===
    probability_at_match = db.Column(db.Float)
    volume_at_match = db.Column(db.Float)

    # === Lifecycle ===
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # === Thresholds ===
    SIMILARITY_THRESHOLD = 0.75  # Minimum similarity to create match
    HIGH_CONFIDENCE_THRESHOLD = 0.85  # High confidence matches

    # === Relationships ===
    trending_topic = db.relationship('TrendingTopic', backref=db.backref('market_matches', lazy='dynamic'))
    # market relationship defined in PolymarketMarket

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
            'created_at': self.created_at.isoformat()
        }

    def __repr__(self):
        return f'<TopicMarketMatch topic={self.trending_topic_id} market={self.market_id} sim={self.similarity_score:.2f}>'
```

### 3. BriefItem Extension

Add market_signal JSON field to existing BriefItem model.

```python
# Add to BriefItem model:

# === Market Signal (optional, for Polymarket integration) ===
# Stored as JSON snapshot at brief generation time for historical accuracy
# Schema: see PolymarketMarket.to_signal_dict()
market_signal = db.Column(db.JSON)  # null if no matching market

# Update to_dict():
def to_dict(self):
    return {
        # ... existing fields ...
        'market_signal': self.market_signal,  # Add this
    }
```

### 4. DailyQuestion Extension

Add optional market link for consensus divergence feature.

```python
# Add to DailyQuestion model:

# === Market Link (optional, for consensus divergence) ===
polymarket_market_id = db.Column(db.Integer, db.ForeignKey('polymarket_market.id'), nullable=True)

@property
def market_divergence(self) -> Optional[dict]:
    """
    Calculate divergence between user votes and market probability.
    Returns None if no market linked or insufficient data.

    Returns:
        {
            'user_probability': 0.62,  # % of users who voted "agree"
            'market_probability': 0.78,
            'divergence': 0.16,
            'is_significant': True,  # divergence >= 0.15
            'direction': 'lower',  # users are 'higher' or 'lower' than market
            'market_question': "Will X happen?",
            'market_url': "https://polymarket.com/..."
        }
    """
    if not self.polymarket_market_id:
        return None

    market = PolymarketMarket.query.get(self.polymarket_market_id)
    if not market or market.probability is None:
        return None

    vote_pcts = self.vote_percentages
    if vote_pcts.get('total', 0) < 10:  # Need minimum votes for meaningful comparison
        return None

    # User "agree" percentage as probability estimate
    user_prob = vote_pcts.get('agree', 0) / 100
    market_prob = market.probability
    divergence = abs(user_prob - market_prob)

    return {
        'user_probability': user_prob,
        'market_probability': market_prob,
        'divergence': divergence,
        'is_significant': divergence >= 0.15,  # 15+ points = interesting
        'direction': 'higher' if user_prob > market_prob else 'lower',
        'market_question': market.question,
        'market_url': market.polymarket_url,
        'market_change_24h': market.change_24h_formatted
    }
```

### 5. InputSource Extension (Paid Briefs)

Add 'polymarket' as a source type for personalized briefings.

```python
# InputSource.type can now be: 'rss' | 'url_list' | 'webpage' | 'upload' | 'substack' | 'x' | 'polymarket'

# For type='polymarket', config_json schema:
{
    "categories": ["politics", "economics", "technology"],  # Polymarket categories to include
    "min_volume": 5000,  # Minimum 24h volume threshold
    "quality_tier": "medium",  # 'high', 'medium', 'low'
    "geographic_focus": ["UK", "US", "Global"],  # Optional geographic filter
    "exclude_tags": ["crypto", "sports"],  # Tags to exclude
    "max_items": 5  # Maximum markets per fetch
}
```

---

## Service Layer

### PolymarketService

Core service for all Polymarket API interactions.

**File:** `app/services/polymarket/service.py`

```python
"""
Polymarket API Service

Handles all interactions with Polymarket APIs:
- Gamma API: Market discovery and metadata
- CLOB API: Prices and orderbook data

Design Principles:
1. NEVER raise exceptions that break callers - return None/empty on failure
2. Cache aggressively - API data is additive, not critical
3. Log all failures for debugging but don't alert
4. Respect rate limits with exponential backoff
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from functools import wraps
import time

import requests
from flask import current_app
from sqlalchemy import or_

from app import db
from app.models import PolymarketMarket

logger = logging.getLogger(__name__)


class PolymarketAPIError(Exception):
    """Internal exception for API errors - never exposed to callers."""
    pass


def safe_api_call(default_return=None):
    """
    Decorator ensuring API calls never raise exceptions.
    Returns default_return on any failure.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"Polymarket API call failed ({func.__name__}): {e}")
                return default_return
        return wrapper
    return decorator


class PolymarketService:
    """
    Service for Polymarket API integration.

    Usage:
        service = PolymarketService()
        markets = service.search_markets("election")
        price = service.get_current_price(condition_id)

    All methods return None or empty list on failure - never raise exceptions.
    """

    GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
    CLOB_BASE_URL = "https://clob.polymarket.com"

    # Rate limiting
    GAMMA_RATE_LIMIT = 300  # requests per 10 seconds
    CLOB_RATE_LIMIT = 1500  # requests per 10 seconds

    # Timeouts
    REQUEST_TIMEOUT = 10  # seconds

    # Cache durations (in seconds)
    CACHE_METADATA_DURATION = 6 * 3600  # 6 hours for market metadata
    CACHE_PRICE_DURATION = 300  # 5 minutes for prices

    def __init__(self):
        self._last_gamma_request = 0
        self._last_clob_request = 0
        self._gamma_request_count = 0
        self._clob_request_count = 0

    # =========================================================================
    # PUBLIC API METHODS
    # =========================================================================

    @safe_api_call(default_return=[])
    def search_markets(self, query: str, limit: int = 20,
                       categories: List[str] = None,
                       active_only: bool = True) -> List[Dict]:
        """
        Search for markets matching query.

        Args:
            query: Search term
            limit: Maximum results
            categories: Optional category filter
            active_only: Only return active markets

        Returns:
            List of market dicts, or empty list on failure
        """
        params = {
            'query': query,
            'limit': limit,
            'active': active_only
        }
        if categories:
            params['categories'] = ','.join(categories)

        response = self._gamma_request('/markets', params=params)
        if not response:
            return []

        return response.get('markets', [])

    @safe_api_call(default_return=None)
    def get_market(self, condition_id: str) -> Optional[Dict]:
        """
        Get single market by condition ID.

        Returns:
            Market dict or None if not found/error
        """
        response = self._gamma_request(f'/markets/{condition_id}')
        return response

    @safe_api_call(default_return=[])
    def get_all_markets(self, limit: int = 500, offset: int = 0,
                        active_only: bool = True) -> List[Dict]:
        """
        Get all markets (paginated) for full sync.

        Returns:
            List of market dicts
        """
        params = {
            'limit': limit,
            'offset': offset,
            'active': active_only
        }
        response = self._gamma_request('/markets', params=params)
        if not response:
            return []
        return response.get('markets', [])

    @safe_api_call(default_return=None)
    def get_current_price(self, token_id: str) -> Optional[float]:
        """
        Get current price for a token (outcome).

        Returns:
            Price as float (0-1) or None
        """
        response = self._clob_request(f'/price', params={'token_id': token_id})
        if not response:
            return None
        return response.get('price')

    @safe_api_call(default_return={})
    def get_prices_batch(self, token_ids: List[str]) -> Dict[str, float]:
        """
        Get prices for multiple tokens in one request.

        Returns:
            Dict mapping token_id -> price
        """
        if not token_ids:
            return {}

        # CLOB API supports batch price requests
        response = self._clob_request('/prices', params={'token_ids': ','.join(token_ids)})
        if not response:
            return {}

        return {item['token_id']: item['price'] for item in response.get('prices', [])}

    @safe_api_call(default_return=None)
    def get_market_orderbook(self, token_id: str) -> Optional[Dict]:
        """
        Get orderbook for liquidity/depth analysis.

        Returns:
            Orderbook dict with bids/asks or None
        """
        response = self._clob_request(f'/book', params={'token_id': token_id})
        return response

    # =========================================================================
    # SYNC METHODS (for scheduled jobs)
    # =========================================================================

    def sync_all_markets(self) -> Dict[str, int]:
        """
        Full sync of all active markets from Polymarket.
        Called by scheduler every 2 hours.

        Returns:
            Stats dict: {'created': N, 'updated': N, 'deactivated': N, 'errors': N}
        """
        stats = {'created': 0, 'updated': 0, 'deactivated': 0, 'errors': 0}
        seen_condition_ids = set()

        offset = 0
        limit = 500

        while True:
            markets = self.get_all_markets(limit=limit, offset=offset, active_only=True)
            if not markets:
                break

            for market_data in markets:
                try:
                    result = self._upsert_market(market_data)
                    stats[result] += 1
                    seen_condition_ids.add(market_data.get('condition_id'))
                except Exception as e:
                    logger.warning(f"Error syncing market {market_data.get('condition_id')}: {e}")
                    stats['errors'] += 1

            if len(markets) < limit:
                break
            offset += limit

        # Deactivate markets no longer in API response
        deactivated = PolymarketMarket.query.filter(
            PolymarketMarket.is_active == True,
            ~PolymarketMarket.condition_id.in_(seen_condition_ids)
        ).update({'is_active': False}, synchronize_session=False)
        stats['deactivated'] = deactivated

        db.session.commit()
        logger.info(f"Polymarket sync complete: {stats}")
        return stats

    def refresh_prices(self) -> Dict[str, int]:
        """
        Refresh prices for all tracked markets.
        Called by scheduler every 5 minutes.

        Returns:
            Stats dict: {'updated': N, 'errors': N}
        """
        stats = {'updated': 0, 'errors': 0}

        # Get markets that need price refresh
        stale_threshold = datetime.utcnow() - timedelta(seconds=self.CACHE_PRICE_DURATION)
        markets = PolymarketMarket.query.filter(
            PolymarketMarket.is_active == True,
            or_(
                PolymarketMarket.last_price_update_at == None,
                PolymarketMarket.last_price_update_at < stale_threshold
            )
        ).limit(200).all()  # Batch size

        # Collect all token IDs for batch request
        token_id_map = {}  # token_id -> (market, outcome_index)
        for market in markets:
            if market.clob_token_ids:
                for idx, token_id in enumerate(market.clob_token_ids):
                    token_id_map[token_id] = (market, idx)

        if not token_id_map:
            return stats

        # Batch fetch prices
        prices = self.get_prices_batch(list(token_id_map.keys()))

        # Update markets
        for token_id, price in prices.items():
            if token_id in token_id_map:
                market, outcome_idx = token_id_map[token_id]
                try:
                    # Store previous probability for 24h change calculation
                    if market.probability is not None:
                        market.probability_24h_ago = market.probability

                    # Update probability (first outcome is typically "Yes")
                    if outcome_idx == 0:
                        market.probability = price

                    # Update outcomes array
                    if market.outcomes and len(market.outcomes) > outcome_idx:
                        market.outcomes[outcome_idx]['price'] = price

                    market.last_price_update_at = datetime.utcnow()
                    stats['updated'] += 1
                except Exception as e:
                    logger.warning(f"Error updating price for market {market.id}: {e}")
                    stats['errors'] += 1

        db.session.commit()
        logger.info(f"Polymarket price refresh complete: {stats}")
        return stats

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _gamma_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make request to Gamma API with rate limiting."""
        self._rate_limit_gamma()

        url = f"{self.GAMMA_BASE_URL}{endpoint}"
        try:
            response = requests.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"Gamma API request failed: {endpoint} - {e}")
            return None

    def _clob_request(self, endpoint: str, params: Dict = None) -> Optional[Dict]:
        """Make request to CLOB API with rate limiting."""
        self._rate_limit_clob()

        url = f"{self.CLOB_BASE_URL}{endpoint}"
        try:
            response = requests.get(url, params=params, timeout=self.REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"CLOB API request failed: {endpoint} - {e}")
            return None

    def _rate_limit_gamma(self):
        """Simple rate limiting for Gamma API."""
        # Reset counter every 10 seconds
        now = time.time()
        if now - self._last_gamma_request > 10:
            self._gamma_request_count = 0
            self._last_gamma_request = now

        if self._gamma_request_count >= self.GAMMA_RATE_LIMIT:
            sleep_time = 10 - (now - self._last_gamma_request)
            if sleep_time > 0:
                time.sleep(sleep_time)
            self._gamma_request_count = 0
            self._last_gamma_request = time.time()

        self._gamma_request_count += 1

    def _rate_limit_clob(self):
        """Simple rate limiting for CLOB API."""
        now = time.time()
        if now - self._last_clob_request > 10:
            self._clob_request_count = 0
            self._last_clob_request = now

        if self._clob_request_count >= self.CLOB_RATE_LIMIT:
            sleep_time = 10 - (now - self._last_clob_request)
            if sleep_time > 0:
                time.sleep(sleep_time)
            self._clob_request_count = 0
            self._last_clob_request = time.time()

        self._clob_request_count += 1

    def _upsert_market(self, data: Dict) -> str:
        """
        Insert or update market from API data.

        Returns:
            'created' or 'updated'
        """
        condition_id = data.get('condition_id')
        if not condition_id:
            raise ValueError("Market data missing condition_id")

        market = PolymarketMarket.query.filter_by(condition_id=condition_id).first()

        if market:
            # Update existing
            market.slug = data.get('slug')
            market.question = data.get('question', market.question)
            market.description = data.get('description')
            market.category = data.get('category')
            market.tags = data.get('tags', [])
            market.outcomes = data.get('outcomes', [])
            market.clob_token_ids = [o.get('token_id') for o in data.get('outcomes', []) if o.get('token_id')]
            market.volume_24h = data.get('volume_24h', 0)
            market.volume_total = data.get('volume_total', 0)
            market.liquidity = data.get('liquidity', 0)
            market.trader_count = data.get('trader_count', 0)
            market.end_date = self._parse_date(data.get('end_date'))
            market.resolution = data.get('resolution')
            market.is_active = data.get('active', True)
            market.last_synced_at = datetime.utcnow()
            market.sync_failures = 0
            return 'updated'
        else:
            # Create new
            market = PolymarketMarket(
                condition_id=condition_id,
                slug=data.get('slug'),
                question=data.get('question', 'Unknown'),
                description=data.get('description'),
                category=data.get('category'),
                tags=data.get('tags', []),
                outcomes=data.get('outcomes', []),
                clob_token_ids=[o.get('token_id') for o in data.get('outcomes', []) if o.get('token_id')],
                volume_24h=data.get('volume_24h', 0),
                volume_total=data.get('volume_total', 0),
                liquidity=data.get('liquidity', 0),
                trader_count=data.get('trader_count', 0),
                end_date=self._parse_date(data.get('end_date')),
                is_active=data.get('active', True),
                last_synced_at=datetime.utcnow()
            )
            db.session.add(market)
            return 'created'

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse ISO date string to datetime."""
        if not date_str:
            return None
        try:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            return None


# Singleton instance
polymarket_service = PolymarketService()
```

### MarketMatcher

Automated matching between TrendingTopics and markets.

**File:** `app/services/polymarket/matcher.py`

```python
"""
Market Matcher Service

Automatically matches TrendingTopics to relevant Polymarket markets using:
1. Category mapping (Society Speaks categories → Polymarket categories)
2. Embedding similarity (semantic matching)
3. Keyword overlap (fallback)

Design Principles:
1. High precision over recall - only match when confident
2. No false positives - better to miss a match than show irrelevant market
3. Batch operations for efficiency
4. Results cached in TopicMarketMatch table
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import numpy as np

from app import db
from app.models import TrendingTopic, PolymarketMarket, TopicMarketMatch

logger = logging.getLogger(__name__)


class MarketMatcher:
    """
    Service for matching TrendingTopics to Polymarket markets.

    Usage:
        matcher = MarketMatcher()
        matches = matcher.match_topic(topic)  # Returns list of matches
        matcher.run_batch_matching()  # Process all recent topics
    """

    # Category mapping: Society Speaks topic -> Polymarket categories
    CATEGORY_MAP = {
        'Politics': ['politics', 'elections', 'government'],
        'Economy': ['economics', 'fed', 'inflation', 'markets', 'finance'],
        'Technology': ['tech', 'ai', 'crypto', 'science'],
        'Geopolitics': ['geopolitics', 'international', 'war', 'diplomacy'],
        'Healthcare': ['health', 'covid', 'fda', 'medicine'],
        'Environment': ['climate', 'energy', 'environment'],
        'Business': ['business', 'companies', 'markets'],
        'Society': ['social', 'culture', 'legal'],
        'Infrastructure': ['infrastructure', 'transportation'],
        'Education': ['education'],
        'Culture': ['entertainment', 'sports', 'media'],
    }

    # Similarity thresholds
    EMBEDDING_THRESHOLD = 0.75  # Minimum cosine similarity for embedding match
    KEYWORD_MIN_OVERLAP = 2  # Minimum keyword overlap for fallback

    def __init__(self, embedding_service=None):
        """
        Args:
            embedding_service: Optional embedding service for generating embeddings.
                              If None, will use existing embeddings only.
        """
        self._embedding_service = embedding_service

    def match_topic(self, topic: TrendingTopic,
                    max_matches: int = 2,
                    min_quality_tier: str = 'medium') -> List[Dict]:
        """
        Find relevant markets for a single topic.

        Args:
            topic: TrendingTopic to match
            max_matches: Maximum number of matches to return
            min_quality_tier: Minimum market quality ('high', 'medium', 'low')

        Returns:
            List of match dicts with 'market', 'similarity', 'method' keys
            Empty list if no matches found
        """
        try:
            # Get candidate markets by category
            candidates = self._get_candidates(topic, min_quality_tier)
            if not candidates:
                return []

            matches = []

            # Method 1: Embedding similarity
            if topic.topic_embedding:
                embedding_matches = self._match_by_embedding(
                    topic.topic_embedding, candidates
                )
                matches.extend(embedding_matches)

            # Method 2: Keyword overlap (fallback for markets without embeddings)
            if len(matches) < max_matches and topic.canonical_tags:
                keyword_matches = self._match_by_keywords(
                    set(topic.canonical_tags), candidates,
                    exclude_ids=[m['market'].id for m in matches]
                )
                matches.extend(keyword_matches)

            # Sort by similarity and return top matches
            matches.sort(key=lambda x: x['similarity'], reverse=True)
            return matches[:max_matches]

        except Exception as e:
            logger.warning(f"Error matching topic {topic.id}: {e}")
            return []

    def run_batch_matching(self, days_back: int = 7,
                           reprocess_existing: bool = False) -> Dict[str, int]:
        """
        Batch match all recent topics to markets.
        Called by scheduler every 30 minutes.

        Args:
            days_back: Process topics created within this many days
            reprocess_existing: If True, reprocess topics that already have matches

        Returns:
            Stats dict: {'processed': N, 'matched': N, 'skipped': N, 'errors': N}
        """
        stats = {'processed': 0, 'matched': 0, 'skipped': 0, 'errors': 0}

        cutoff = datetime.utcnow() - timedelta(days=days_back)

        query = TrendingTopic.query.filter(
            TrendingTopic.created_at >= cutoff,
            TrendingTopic.status.in_(['approved', 'published', 'pending_review'])
        )

        if not reprocess_existing:
            # Only process topics without existing matches
            query = query.outerjoin(TopicMarketMatch).filter(
                TopicMarketMatch.id == None
            )

        topics = query.all()

        for topic in topics:
            stats['processed'] += 1
            try:
                matches = self.match_topic(topic)

                if not matches:
                    stats['skipped'] += 1
                    continue

                # Store matches
                for match in matches:
                    # Check if match already exists
                    existing = TopicMarketMatch.query.filter_by(
                        trending_topic_id=topic.id,
                        market_id=match['market'].id
                    ).first()

                    if existing:
                        # Update similarity score
                        existing.similarity_score = match['similarity']
                        existing.match_method = match['method']
                        existing.updated_at = datetime.utcnow()
                    else:
                        # Create new match
                        db.session.add(TopicMarketMatch(
                            trending_topic_id=topic.id,
                            market_id=match['market'].id,
                            similarity_score=match['similarity'],
                            match_method=match['method'],
                            probability_at_match=match['market'].probability,
                            volume_at_match=match['market'].volume_24h
                        ))
                    stats['matched'] += 1

            except Exception as e:
                logger.warning(f"Error processing topic {topic.id}: {e}")
                stats['errors'] += 1

        db.session.commit()
        logger.info(f"Market matching complete: {stats}")
        return stats

    def get_best_match_for_topic(self, topic_id: int) -> Optional[PolymarketMarket]:
        """
        Get the best matching market for a topic.
        Returns None if no match exists or market is inactive.

        This is the main method called by brief generator.
        """
        match = TopicMarketMatch.query.filter_by(
            trending_topic_id=topic_id
        ).join(PolymarketMarket).filter(
            PolymarketMarket.is_active == True
        ).order_by(
            TopicMarketMatch.similarity_score.desc()
        ).first()

        if match and match.similarity_score >= TopicMarketMatch.SIMILARITY_THRESHOLD:
            return match.market
        return None

    # =========================================================================
    # PRIVATE METHODS
    # =========================================================================

    def _get_candidates(self, topic: TrendingTopic,
                        min_quality_tier: str) -> List[PolymarketMarket]:
        """Get candidate markets based on category and quality."""

        # Map topic category to Polymarket categories
        pm_categories = self.CATEGORY_MAP.get(topic.primary_topic, [])

        # Quality threshold
        if min_quality_tier == 'high':
            min_volume = PolymarketMarket.HIGH_QUALITY_VOLUME
        elif min_quality_tier == 'medium':
            min_volume = PolymarketMarket.MIN_VOLUME_24H
        else:
            min_volume = 0

        query = PolymarketMarket.query.filter(
            PolymarketMarket.is_active == True,
            PolymarketMarket.volume_24h >= min_volume
        )

        if pm_categories:
            query = query.filter(PolymarketMarket.category.in_(pm_categories))

        return query.limit(100).all()

    def _match_by_embedding(self, topic_embedding: List[float],
                           candidates: List[PolymarketMarket]) -> List[Dict]:
        """Match using embedding similarity."""
        matches = []
        topic_vec = np.array(topic_embedding)

        for market in candidates:
            if not market.question_embedding:
                continue

            market_vec = np.array(market.question_embedding)
            similarity = self._cosine_similarity(topic_vec, market_vec)

            if similarity >= self.EMBEDDING_THRESHOLD:
                matches.append({
                    'market': market,
                    'similarity': similarity,
                    'method': 'embedding'
                })

        return matches

    def _match_by_keywords(self, topic_tags: set,
                          candidates: List[PolymarketMarket],
                          exclude_ids: List[int] = None) -> List[Dict]:
        """Match using keyword overlap (fallback)."""
        matches = []
        exclude_ids = exclude_ids or []

        for market in candidates:
            if market.id in exclude_ids:
                continue

            market_tags = set(market.tags or [])
            overlap = len(topic_tags & market_tags)

            if overlap >= self.KEYWORD_MIN_OVERLAP:
                # Convert overlap to similarity score (0.5-0.9 range)
                similarity = min(0.5 + overlap * 0.1, 0.9)
                matches.append({
                    'market': market,
                    'similarity': similarity,
                    'method': 'keyword'
                })

        return matches

    def _cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Calculate cosine similarity between two vectors."""
        if vec1.size == 0 or vec2.size == 0:
            return 0.0

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)


# Singleton instance
market_matcher = MarketMatcher()
```

### PolymarketSourceAdapter

Adapts Polymarket markets to the InputSource system for paid briefs.

**File:** `app/services/polymarket/source_adapter.py`

```python
"""
Polymarket Source Adapter

Adapts Polymarket markets to work as an InputSource for paid briefings.
Converts markets into IngestedItems that flow through the normal briefing pipeline.

This allows paid users to add "Prediction Markets" as a source alongside RSS feeds,
Substack newsletters, etc.
"""

import logging
from datetime import datetime
from typing import List, Optional
import hashlib

from app import db
from app.models import InputSource, IngestedItem, PolymarketMarket

logger = logging.getLogger(__name__)


class PolymarketSourceAdapter:
    """
    Adapter for treating Polymarket as an InputSource.

    Usage:
        adapter = PolymarketSourceAdapter()
        items = adapter.fetch_items(source)  # Returns IngestedItems
    """

    def fetch_items(self, source: InputSource) -> List[IngestedItem]:
        """
        Fetch markets matching this source's configuration and convert to IngestedItems.

        Args:
            source: InputSource with type='polymarket'

        Returns:
            List of IngestedItem objects (already added to session)
        """
        if source.type != 'polymarket':
            logger.warning(f"PolymarketSourceAdapter called with non-polymarket source {source.id}")
            return []

        try:
            config = source.config_json or {}
            markets = self._query_matching_markets(config)

            items = []
            for market in markets:
                item = self._upsert_ingested_item(source, market, config)
                if item:
                    items.append(item)

            db.session.commit()
            return items

        except Exception as e:
            logger.warning(f"Error fetching polymarket items for source {source.id}: {e}")
            db.session.rollback()
            return []

    def _query_matching_markets(self, config: dict) -> List[PolymarketMarket]:
        """Query markets based on source configuration."""

        categories = config.get('categories', [])
        min_volume = config.get('min_volume', PolymarketMarket.MIN_VOLUME_24H)
        quality_tier = config.get('quality_tier', 'medium')
        exclude_tags = set(config.get('exclude_tags', []))
        max_items = config.get('max_items', 10)

        # Base query
        query = PolymarketMarket.query.filter(
            PolymarketMarket.is_active == True
        )

        # Quality filter
        if quality_tier == 'high':
            query = query.filter(PolymarketMarket.volume_24h >= PolymarketMarket.HIGH_QUALITY_VOLUME)
        elif quality_tier == 'medium':
            query = query.filter(PolymarketMarket.volume_24h >= PolymarketMarket.MIN_VOLUME_24H)
        else:
            query = query.filter(PolymarketMarket.volume_24h >= min_volume)

        # Category filter
        if categories:
            query = query.filter(PolymarketMarket.category.in_(categories))

        # Order by volume (most liquid first)
        query = query.order_by(PolymarketMarket.volume_24h.desc())

        markets = query.limit(max_items * 2).all()  # Fetch extra for filtering

        # Filter out excluded tags
        if exclude_tags:
            markets = [m for m in markets if not (set(m.tags or []) & exclude_tags)]

        return markets[:max_items]

    def _upsert_ingested_item(self, source: InputSource,
                              market: PolymarketMarket,
                              config: dict) -> Optional[IngestedItem]:
        """Create or update IngestedItem for a market."""

        # Use condition_id as external_id for deduplication
        external_id = f"polymarket:{market.condition_id}"

        # Check for existing item
        item = IngestedItem.query.filter_by(
            source_id=source.id,
            external_id=external_id
        ).first()

        # Generate content
        content_text = self._format_market_content(market)
        content_hash = hashlib.md5(content_text.encode()).hexdigest()

        if item:
            # Update existing item with latest data
            item.title = market.question
            item.content_text = content_text
            item.content_hash = content_hash
            item.metadata_json = self._build_metadata(market)
            item.fetched_at = datetime.utcnow()
        else:
            # Create new item
            item = IngestedItem(
                source_id=source.id,
                external_id=external_id,
                title=market.question,
                url=market.polymarket_url,
                content_text=content_text,
                content_hash=content_hash,
                published_at=market.first_seen_at or market.created_at,
                fetched_at=datetime.utcnow(),
                metadata_json=self._build_metadata(market)
            )
            db.session.add(item)

        return item

    def _format_market_content(self, market: PolymarketMarket) -> str:
        """Format market data as readable content for brief generation."""

        change_str = market.change_24h_formatted
        volume_str = f"${market.volume_24h:,.0f}" if market.volume_24h else "—"
        liquidity_str = f"${market.liquidity:,.0f}" if market.liquidity else "—"

        end_date_str = ""
        if market.end_date:
            end_date_str = f"\nResolves: {market.end_date.strftime('%B %d, %Y')}"

        return f"""**{market.question}**

**Current Probability: {market.probability:.0%}**
24-hour change: {change_str}

Trading Volume (24h): {volume_str}
Liquidity: {liquidity_str}
Traders: {market.trader_count or '—'}
{end_date_str}

{market.description or ''}

---
*Market data from Polymarket. Prices reflect collective expectations based on trading activity. They can move on new information, rumours, and sentiment shifts.*
"""

    def _build_metadata(self, market: PolymarketMarket) -> dict:
        """Build metadata dict for IngestedItem."""
        return {
            'type': 'prediction_market',
            'source_platform': 'polymarket',
            'market_id': market.id,
            'condition_id': market.condition_id,
            'probability': market.probability,
            'change_24h': market.change_24h,
            'volume_24h': market.volume_24h,
            'liquidity': market.liquidity,
            'trader_count': market.trader_count,
            'category': market.category,
            'quality_tier': market.quality_tier,
            'end_date': market.end_date.isoformat() if market.end_date else None,
            'outcomes': market.outcomes
        }


# Singleton instance
polymarket_source_adapter = PolymarketSourceAdapter()
```

---

## Brief Generator Integration

### Free Daily Brief - Market Signal Enrichment

**File:** `app/brief/generator.py` (additions)

```python
"""
Additions to BriefGenerator for Polymarket integration.

These methods are called during brief generation to optionally enrich
BriefItems with market signal data. Failures are logged but never block
brief generation.
"""

from app.services.polymarket.matcher import market_matcher


class BriefGeneratorPolymarketMixin:
    """
    Mixin for BriefGenerator to add Polymarket enrichment.

    All methods return gracefully on failure - market data is always optional.
    """

    def enrich_item_with_market_signal(self, item: 'BriefItem') -> None:
        """
        Enrich a BriefItem with market signal data if available.

        Called after other enrichment (perspectives, coverage analysis).
        Sets item.market_signal to dict or None.

        Args:
            item: BriefItem to enrich (modified in place)
        """
        try:
            if not item.trending_topic_id:
                return

            # Find best matching market
            market = market_matcher.get_best_match_for_topic(item.trending_topic_id)

            if not market:
                item.market_signal = None
                return

            # Verify market quality
            if not market.is_high_quality:
                item.market_signal = None
                return

            # Set market signal
            item.market_signal = market.to_signal_dict()

        except Exception as e:
            # Log but don't fail - market signal is optional
            logger.warning(f"Error enriching item {item.id} with market signal: {e}")
            item.market_signal = None

    def enrich_all_items_with_market_signals(self, items: List['BriefItem']) -> None:
        """
        Batch enrich all items with market signals.

        Args:
            items: List of BriefItems to enrich
        """
        for item in items:
            self.enrich_item_with_market_signal(item)


# In the main generate_brief() method, add after other enrichment:
#
# # Enrich with market signals (optional, failures are silent)
# self.enrich_all_items_with_market_signals(brief_items)
```

### Paid Briefings - Polymarket Source Integration

**File:** `app/briefing/item_feed_service.py` (additions)

```python
"""
Additions to ItemFeedService for Polymarket source type.

When a Briefing has an InputSource with type='polymarket', this adapter
fetches relevant markets and converts them to IngestedItems that flow
through the normal briefing pipeline.
"""

from app.services.polymarket.source_adapter import polymarket_source_adapter


def fetch_items_for_source(source: InputSource) -> List[IngestedItem]:
    """
    Fetch items for any source type.

    Extended to handle type='polymarket'.
    """
    if source.type == 'polymarket':
        return polymarket_source_adapter.fetch_items(source)

    # ... existing logic for other source types ...
```

---

## Scheduled Jobs

**File:** `app/scheduler.py` (additions)

```python
"""
Scheduled jobs for Polymarket integration.

All jobs are designed to fail gracefully - if Polymarket is unavailable,
jobs log warnings but don't affect other scheduler operations.
"""

from app.services.polymarket.service import polymarket_service
from app.services.polymarket.matcher import market_matcher
from app.services.polymarket.source_adapter import polymarket_source_adapter


def setup_polymarket_jobs(scheduler):
    """Register Polymarket-related scheduled jobs."""

    # Full market sync - every 2 hours
    # Fetches all active markets from Polymarket API and updates local cache
    scheduler.add_job(
        func=safe_polymarket_sync,
        trigger='interval',
        hours=2,
        id='polymarket_full_sync',
        name='Polymarket: Full market sync',
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300
    )

    # Price refresh - every 5 minutes
    # Updates prices for all tracked markets
    scheduler.add_job(
        func=safe_polymarket_price_refresh,
        trigger='interval',
        minutes=5,
        id='polymarket_price_refresh',
        name='Polymarket: Price refresh',
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60
    )

    # Topic matching - every 30 minutes
    # Matches recent TrendingTopics to relevant markets
    scheduler.add_job(
        func=safe_polymarket_matching,
        trigger='interval',
        minutes=30,
        id='polymarket_topic_matching',
        name='Polymarket: Topic-market matching',
        max_instances=1,
        coalesce=True,
        misfire_grace_time=120
    )

    # Source fetch - every 15 minutes
    # Fetches items for all polymarket InputSources (paid briefs)
    scheduler.add_job(
        func=safe_polymarket_source_fetch,
        trigger='interval',
        minutes=15,
        id='polymarket_source_fetch',
        name='Polymarket: Fetch items for sources',
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60
    )


def safe_polymarket_sync():
    """
    Wrapper for full market sync with error handling.
    Failures are logged but don't raise exceptions.
    """
    try:
        with app.app_context():
            stats = polymarket_service.sync_all_markets()
            logger.info(f"Polymarket sync complete: {stats}")
    except Exception as e:
        logger.error(f"Polymarket sync failed: {e}")


def safe_polymarket_price_refresh():
    """
    Wrapper for price refresh with error handling.
    """
    try:
        with app.app_context():
            stats = polymarket_service.refresh_prices()
            logger.info(f"Polymarket price refresh complete: {stats}")
    except Exception as e:
        logger.error(f"Polymarket price refresh failed: {e}")


def safe_polymarket_matching():
    """
    Wrapper for topic-market matching with error handling.
    """
    try:
        with app.app_context():
            stats = market_matcher.run_batch_matching()
            logger.info(f"Polymarket matching complete: {stats}")
    except Exception as e:
        logger.error(f"Polymarket matching failed: {e}")


def safe_polymarket_source_fetch():
    """
    Wrapper for source item fetch with error handling.
    """
    try:
        with app.app_context():
            sources = InputSource.query.filter_by(type='polymarket', status='ready').all()
            for source in sources:
                try:
                    items = polymarket_source_adapter.fetch_items(source)
                    logger.info(f"Fetched {len(items)} items for polymarket source {source.id}")
                except Exception as e:
                    logger.warning(f"Failed to fetch items for polymarket source {source.id}: {e}")
    except Exception as e:
        logger.error(f"Polymarket source fetch failed: {e}")
```

---

## Templates

### Email Template - Market Signal Section

**File:** `app/templates/emails/daily_brief.html` (additions)

Add after "How It's Being Framed" section:

```html
{# Market Signal Section - Only shown if market_signal exists #}
{% if item.market_signal %}
<tr>
  <td style="padding: 20px 0;">
    <table width="100%" cellpadding="0" cellspacing="0" border="0"
           style="background: #f8fafc; border-left: 4px solid #6366f1; border-radius: 0 8px 8px 0;">
      <tr>
        <td style="padding: 20px;">
          {# Section Header #}
          <table width="100%">
            <tr>
              <td style="font-size: 11px; font-weight: 600; color: #6366f1;
                         letter-spacing: 0.5px; text-transform: uppercase; padding-bottom: 12px;">
                📊 MARKET SIGNAL
              </td>
            </tr>
          </table>

          {# Market Question #}
          <table width="100%">
            <tr>
              <td style="font-size: 16px; font-weight: 500; color: #1e293b; padding-bottom: 16px;">
                "{{ item.market_signal.question }}"
              </td>
            </tr>
          </table>

          {# Probability Bar #}
          <table width="100%">
            <tr>
              <td>
                <div style="background: #e2e8f0; height: 28px; border-radius: 4px; overflow: hidden;">
                  <div style="background: linear-gradient(90deg, #6366f1, #818cf8);
                              height: 100%; width: {{ (item.market_signal.probability * 100)|round }}%;
                              min-width: 40px; display: flex; align-items: center; justify-content: flex-end;">
                    <span style="color: white; font-weight: 600; font-size: 14px; padding-right: 8px;">
                      {{ (item.market_signal.probability * 100)|round }}%
                    </span>
                  </div>
                </div>
              </td>
            </tr>
          </table>

          {# Stats Row #}
          <table width="100%" style="margin-top: 12px;">
            <tr>
              <td style="font-size: 13px; color: #64748b;">
                {% if item.market_signal.change_24h_formatted and item.market_signal.change_24h_formatted != '—' %}
                  <span style="{% if item.market_signal.change_24h > 0 %}color: #16a34a;{% elif item.market_signal.change_24h < 0 %}color: #dc2626;{% endif %}">
                    {{ item.market_signal.change_24h_formatted }}
                  </span> today ·
                {% endif %}
                ${{ "{:,.0f}".format(item.market_signal.volume_24h or 0) }} volume ·
                <a href="{{ item.market_signal.url }}"
                   style="color: #6366f1; text-decoration: none;">
                  View market →
                </a>
              </td>
            </tr>
          </table>

          {# Disclaimer #}
          <table width="100%" style="margin-top: 16px;">
            <tr>
              <td style="font-size: 12px; color: #94a3b8; font-style: italic;
                         border-top: 1px solid #e2e8f0; padding-top: 12px;">
                Markets reflect collective expectations, not certainty.
                Prices move on new information, rumours, and sentiment.
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </td>
</tr>
{% endif %}
```

### Web Template - Market Signal Card

**File:** `app/templates/brief/view.html` (additions)

```html
{# Market Signal Card - Only shown if market_signal exists #}
{% if item.market_signal %}
<div class="mt-4 bg-slate-50 border-l-4 border-indigo-500 rounded-r-lg p-4">
  <div class="flex items-center gap-2 mb-3">
    <span class="text-xs font-semibold text-indigo-600 uppercase tracking-wide">
      📊 Market Signal
    </span>
    {% if item.market_signal.quality_tier == 'high' %}
    <span class="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">
      High Volume
    </span>
    {% endif %}
  </div>

  <p class="text-base font-medium text-slate-800 mb-3">
    "{{ item.market_signal.question }}"
  </p>

  {# Probability Bar #}
  <div class="mb-3">
    <div class="h-7 bg-slate-200 rounded overflow-hidden">
      <div class="h-full bg-gradient-to-r from-indigo-500 to-indigo-400 flex items-center justify-end pr-2"
           style="width: {{ (item.market_signal.probability * 100)|round }}%; min-width: 50px;">
        <span class="text-white font-semibold text-sm">
          {{ (item.market_signal.probability * 100)|round }}%
        </span>
      </div>
    </div>
  </div>

  {# Stats #}
  <div class="flex items-center gap-3 text-sm text-slate-500 mb-3">
    {% if item.market_signal.change_24h_formatted and item.market_signal.change_24h_formatted != '—' %}
    <span class="{% if item.market_signal.change_24h > 0 %}text-green-600{% elif item.market_signal.change_24h < 0 %}text-red-600{% endif %}">
      {{ item.market_signal.change_24h_formatted }} today
    </span>
    <span>·</span>
    {% endif %}
    <span>${{ "{:,.0f}".format(item.market_signal.volume_24h or 0) }} volume</span>
    <span>·</span>
    <a href="{{ item.market_signal.url }}" target="_blank" rel="noopener"
       class="text-indigo-600 hover:text-indigo-700">
      View market →
    </a>
  </div>

  {# Disclaimer #}
  <p class="text-xs text-slate-400 italic border-t border-slate-200 pt-3">
    Markets reflect collective expectations, not certainty.
    Prices move on new information, rumours, and sentiment.
  </p>
</div>
{% endif %}
```

### Consensus Divergence Template

**File:** `app/templates/daily/question_detail.html` (additions)

```html
{# Consensus Divergence Card - Only shown when significant #}
{% if question.market_divergence and question.market_divergence.is_significant %}
<div class="mt-6 bg-amber-50 border border-amber-200 rounded-lg p-4">
  <div class="flex items-center gap-2 mb-3">
    <span class="text-amber-700 text-lg">🔍</span>
    <span class="text-sm font-semibold text-amber-800 uppercase tracking-wide">
      Interesting Divergence
    </span>
  </div>

  <div class="space-y-2 mb-3">
    <div class="flex items-center justify-between">
      <span class="text-sm text-slate-600">Our community</span>
      <span class="font-semibold text-slate-800">
        {{ (question.market_divergence.user_probability * 100)|round }}% expect yes
      </span>
    </div>
    <div class="flex items-center justify-between">
      <span class="text-sm text-slate-600">Prediction markets</span>
      <span class="font-semibold text-slate-800">
        {{ (question.market_divergence.market_probability * 100)|round }}% probability
      </span>
    </div>
  </div>

  {# Visual comparison #}
  <div class="flex gap-2 mb-3">
    <div class="flex-1">
      <div class="text-xs text-slate-500 mb-1">Community</div>
      <div class="h-3 bg-slate-200 rounded overflow-hidden">
        <div class="h-full bg-blue-500"
             style="width: {{ (question.market_divergence.user_probability * 100)|round }}%"></div>
      </div>
    </div>
    <div class="flex-1">
      <div class="text-xs text-slate-500 mb-1">Market</div>
      <div class="h-3 bg-slate-200 rounded overflow-hidden">
        <div class="h-full bg-indigo-500"
             style="width: {{ (question.market_divergence.market_probability * 100)|round }}%"></div>
      </div>
    </div>
  </div>

  <p class="text-sm text-amber-800">
    {% if question.market_divergence.direction == 'higher' %}
    Our community is <strong>more optimistic</strong> than prediction markets on this outcome.
    {% else %}
    Prediction markets are <strong>more confident</strong> than our community on this outcome.
    {% endif %}
    <a href="{{ question.market_divergence.market_url }}" target="_blank" rel="noopener"
       class="text-amber-700 hover:text-amber-900 underline ml-1">
      View market →
    </a>
  </p>
</div>
{% endif %}
```

---

## Database Migration

**File:** `migrations/versions/xxxx_add_polymarket_integration.py`

```python
"""Add Polymarket integration tables and fields

Revision ID: xxxx
Revises: previous_revision
Create Date: 2026-01-24
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'xxxx'
down_revision = 'previous_revision'
branch_labels = None
depends_on = None


def upgrade():
    # Create polymarket_market table
    op.create_table('polymarket_market',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('condition_id', sa.String(100), nullable=False),
        sa.Column('slug', sa.String(200), nullable=True),
        sa.Column('clob_token_ids', postgresql.JSON(), nullable=True),
        sa.Column('question', sa.String(500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(100), nullable=True),
        sa.Column('tags', postgresql.JSON(), nullable=True),
        sa.Column('question_embedding', postgresql.JSON(), nullable=True),
        sa.Column('outcomes', postgresql.JSON(), nullable=True),
        sa.Column('probability', sa.Float(), nullable=True),
        sa.Column('probability_24h_ago', sa.Float(), nullable=True),
        sa.Column('volume_24h', sa.Float(), default=0),
        sa.Column('volume_total', sa.Float(), default=0),
        sa.Column('liquidity', sa.Float(), default=0),
        sa.Column('trader_count', sa.Integer(), default=0),
        sa.Column('is_active', sa.Boolean(), default=True),
        sa.Column('end_date', sa.DateTime(), nullable=True),
        sa.Column('resolution', sa.String(50), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('last_price_update_at', sa.DateTime(), nullable=True),
        sa.Column('sync_failures', sa.Integer(), default=0),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('condition_id')
    )

    # Indexes for polymarket_market
    op.create_index('idx_pm_market_condition', 'polymarket_market', ['condition_id'])
    op.create_index('idx_pm_market_category', 'polymarket_market', ['category'])
    op.create_index('idx_pm_market_active', 'polymarket_market', ['is_active'])
    op.create_index('idx_pm_market_quality', 'polymarket_market', ['is_active', 'volume_24h', 'liquidity'])

    # Create topic_market_match table
    op.create_table('topic_market_match',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trending_topic_id', sa.Integer(), nullable=False),
        sa.Column('market_id', sa.Integer(), nullable=False),
        sa.Column('similarity_score', sa.Float(), nullable=False),
        sa.Column('match_method', sa.String(20), nullable=False),
        sa.Column('probability_at_match', sa.Float(), nullable=True),
        sa.Column('volume_at_match', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['trending_topic_id'], ['trending_topic.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['market_id'], ['polymarket_market.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trending_topic_id', 'market_id', name='uq_topic_market')
    )

    # Indexes for topic_market_match
    op.create_index('idx_tmm_topic', 'topic_market_match', ['trending_topic_id'])
    op.create_index('idx_tmm_market', 'topic_market_match', ['market_id'])
    op.create_index('idx_tmm_similarity', 'topic_market_match', ['similarity_score'])

    # Add market_signal to brief_item
    op.add_column('brief_item', sa.Column('market_signal', postgresql.JSON(), nullable=True))

    # Add polymarket_market_id to daily_question
    op.add_column('daily_question',
        sa.Column('polymarket_market_id', sa.Integer(),
                  sa.ForeignKey('polymarket_market.id'), nullable=True))


def downgrade():
    # Remove foreign key from daily_question
    op.drop_column('daily_question', 'polymarket_market_id')

    # Remove market_signal from brief_item
    op.drop_column('brief_item', 'market_signal')

    # Drop topic_market_match
    op.drop_index('idx_tmm_similarity', 'topic_market_match')
    op.drop_index('idx_tmm_market', 'topic_market_match')
    op.drop_index('idx_tmm_topic', 'topic_market_match')
    op.drop_table('topic_market_match')

    # Drop polymarket_market
    op.drop_index('idx_pm_market_quality', 'polymarket_market')
    op.drop_index('idx_pm_market_active', 'polymarket_market')
    op.drop_index('idx_pm_market_category', 'polymarket_market')
    op.drop_index('idx_pm_market_condition', 'polymarket_market')
    op.drop_table('polymarket_market')
```

---

## Edge Cases & Error Handling

### Comprehensive Edge Case Matrix

| Scenario | Detection | Handling | User Impact |
|----------|-----------|----------|-------------|
| **API Failures** ||||
| Polymarket API timeout | `requests.Timeout` | Return None, use cache | None - brief generates without market signal |
| Rate limit exceeded | HTTP 429 | Exponential backoff, use cache | None - cached data shown |
| Invalid API response | JSON parse error | Log warning, return None | None |
| API returns empty data | Empty list check | Continue without markets | None |
| **Data Quality** ||||
| Market has no trades | `volume_24h < MIN_VOLUME` | Exclude from matching | Market not shown |
| Market is illiquid | `liquidity < MIN_LIQUIDITY` | Exclude from matching | Market not shown |
| Market already resolved | `is_active == False` | Exclude from matching | Market not shown |
| Market question is duplicate | Same condition_id | Update existing record | Deduplicated |
| **Matching Failures** ||||
| No matching market for topic | Empty match result | `item.market_signal = None` | No market signal section |
| Low similarity score | `similarity < 0.75` | Don't create match | No market signal section |
| Topic has no embedding | `topic_embedding is None` | Fall back to keyword matching | May still match |
| Market has no embedding | `question_embedding is None` | Use keyword matching only | May still match |
| **Database Issues** ||||
| FK constraint violation | SQLAlchemy error | Log, rollback, continue | None - other items unaffected |
| Deadlock | `OperationalError` | Retry with backoff | Slight delay |
| Connection pool exhausted | Connection error | Queue request, retry | Slight delay |
| **Rendering** ||||
| Missing market_signal fields | Template `{% if %}` guards | Section not rendered | Graceful degradation |
| Invalid probability value | `probability is None` | Show "—" | Clear indication of no data |
| Missing URL | `url is None` | Don't render link | Link not shown |

### Error Handling Patterns

**Pattern 1: Safe API Call Decorator**
```python
def safe_api_call(default_return=None):
    """Ensures API calls never raise exceptions to callers."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.warning(f"API call failed ({func.__name__}): {e}")
                return default_return
        return wrapper
    return decorator
```

**Pattern 2: Graceful Enrichment**
```python
def enrich_with_market_signal(item):
    """Enrichment that never fails the parent operation."""
    try:
        market = get_market_for_topic(item.topic_id)
        item.market_signal = market.to_signal_dict() if market else None
    except Exception as e:
        logger.warning(f"Market enrichment failed: {e}")
        item.market_signal = None  # Fail silently
```

**Pattern 3: Template Guards**
```html
{% if item.market_signal and item.market_signal.probability is not none %}
  {# Render market signal #}
{% endif %}
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_polymarket_service.py

class TestPolymarketService:
    """Tests for PolymarketService."""

    def test_search_markets_returns_empty_on_api_error(self, mock_requests):
        """API errors should return empty list, not raise."""
        mock_requests.get.side_effect = requests.Timeout()

        service = PolymarketService()
        result = service.search_markets("election")

        assert result == []

    def test_get_market_returns_none_on_404(self, mock_requests):
        """Missing market should return None."""
        mock_requests.get.return_value.status_code = 404

        service = PolymarketService()
        result = service.get_market("invalid_id")

        assert result is None

    def test_sync_handles_partial_failures(self, mock_requests, db_session):
        """Sync should continue even if some markets fail."""
        # ... test implementation


class TestMarketMatcher:
    """Tests for MarketMatcher."""

    def test_no_match_returns_empty_list(self, db_session):
        """Topics without matches should get empty list."""
        topic = create_topic(primary_topic="UnknownCategory")

        matcher = MarketMatcher()
        result = matcher.match_topic(topic)

        assert result == []

    def test_low_similarity_not_matched(self, db_session):
        """Low similarity scores should not create matches."""
        # ... test implementation


class TestBriefGeneratorPolymarket:
    """Tests for Polymarket enrichment in brief generator."""

    def test_enrichment_fails_silently(self, db_session, mock_matcher):
        """Enrichment failures should not break brief generation."""
        mock_matcher.get_best_match_for_topic.side_effect = Exception("DB error")

        item = create_brief_item()
        generator = BriefGenerator()

        # Should not raise
        generator.enrich_item_with_market_signal(item)

        assert item.market_signal is None
```

### Integration Tests

```python
# tests/integration/test_polymarket_integration.py

class TestPolymarketIntegration:
    """End-to-end integration tests."""

    def test_brief_generates_without_polymarket(self, app, db_session):
        """Brief generation works when Polymarket is unavailable."""
        # Disable Polymarket service
        with patch('app.services.polymarket.service.polymarket_service') as mock:
            mock.sync_all_markets.side_effect = Exception("API down")

            # Generate brief
            brief = generate_daily_brief()

            # Should succeed
            assert brief is not None
            assert len(brief.items) > 0

            # Market signals should be None
            for item in brief.items:
                assert item.market_signal is None

    def test_paid_brief_includes_market_items(self, app, db_session):
        """Paid briefs with polymarket source include market items."""
        # Create polymarket source
        source = InputSource(type='polymarket', config_json={'categories': ['politics']})

        # Generate brief
        brief_run = generate_brief_run(sources=[source])

        # Should include market items
        market_items = [i for i in brief_run.items if i.metadata_json.get('type') == 'prediction_market']
        assert len(market_items) > 0
```

---

## Monitoring & Observability

### Metrics to Track

```python
# app/services/polymarket/metrics.py

POLYMARKET_METRICS = {
    # API health
    'polymarket_api_requests_total': Counter('Total API requests'),
    'polymarket_api_errors_total': Counter('API errors by type'),
    'polymarket_api_latency_seconds': Histogram('API request latency'),

    # Sync health
    'polymarket_sync_markets_total': Gauge('Total markets synced'),
    'polymarket_sync_last_success': Gauge('Timestamp of last successful sync'),
    'polymarket_sync_errors_total': Counter('Sync errors'),

    # Matching health
    'polymarket_matches_created_total': Counter('Topic-market matches created'),
    'polymarket_match_similarity_avg': Gauge('Average match similarity'),

    # Usage
    'polymarket_brief_items_enriched': Counter('Brief items enriched with market signal'),
    'polymarket_source_items_fetched': Counter('Items fetched for polymarket sources'),
}
```

### Health Check Endpoint

```python
# app/api/health.py

@api.route('/health/polymarket')
def polymarket_health():
    """Health check for Polymarket integration."""

    # Check last sync time
    latest_market = PolymarketMarket.query.order_by(
        PolymarketMarket.last_synced_at.desc()
    ).first()

    last_sync = latest_market.last_synced_at if latest_market else None
    sync_stale = not last_sync or (datetime.utcnow() - last_sync) > timedelta(hours=4)

    # Check market count
    active_markets = PolymarketMarket.query.filter_by(is_active=True).count()

    # Check recent matches
    recent_matches = TopicMarketMatch.query.filter(
        TopicMarketMatch.created_at >= datetime.utcnow() - timedelta(hours=24)
    ).count()

    status = 'healthy'
    if sync_stale:
        status = 'degraded'
    if active_markets == 0:
        status = 'unhealthy'

    return jsonify({
        'status': status,
        'last_sync': last_sync.isoformat() if last_sync else None,
        'sync_stale': sync_stale,
        'active_markets': active_markets,
        'recent_matches_24h': recent_matches
    })
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1)
- [ ] Create database models and migration
- [ ] Implement `PolymarketService` with API integration
- [ ] Add scheduled jobs for sync and price refresh
- [ ] Basic admin view for market list

### Phase 2: Free Brief Integration (Week 2)
- [ ] Implement `MarketMatcher` with embedding similarity
- [ ] Add `enrich_item_with_market_signal` to brief generator
- [ ] Create email template for market signal section
- [ ] Create web template for market signal card

### Phase 3: Paid Brief Integration (Week 2-3)
- [ ] Implement `PolymarketSourceAdapter`
- [ ] Add 'polymarket' as InputSource type
- [ ] Update item feed service to handle polymarket sources
- [ ] Add source configuration UI for paid users

### Phase 4: Consensus Divergence (Week 3)
- [ ] Add `polymarket_market_id` to DailyQuestion
- [ ] Implement `market_divergence` property
- [ ] Create divergence UI templates
- [ ] Admin UI to link questions to markets

### Phase 5: Polish & Monitoring (Week 4)
- [ ] Add comprehensive logging and metrics
- [ ] Implement health check endpoint
- [ ] Write integration tests
- [ ] Documentation and deployment

---

## Configuration

### Environment Variables

```bash
# Optional - all have sensible defaults
POLYMARKET_SYNC_ENABLED=true           # Enable/disable Polymarket integration
POLYMARKET_SYNC_INTERVAL_HOURS=2       # Full sync interval
POLYMARKET_PRICE_REFRESH_MINUTES=5     # Price refresh interval
POLYMARKET_MIN_VOLUME=1000             # Minimum 24h volume for matching
POLYMARKET_MIN_LIQUIDITY=5000          # Minimum liquidity for matching
POLYMARKET_SIMILARITY_THRESHOLD=0.75   # Minimum similarity for matches
```

### Feature Flags

```python
# app/config.py

class Config:
    # Polymarket integration
    POLYMARKET_ENABLED = os.getenv('POLYMARKET_SYNC_ENABLED', 'true').lower() == 'true'
    POLYMARKET_SHOW_IN_FREE_BRIEFS = True
    POLYMARKET_ALLOW_AS_SOURCE = True  # For paid briefs
```

---

## Implementation Notes & Optimizations

### Embedding Generation Strategy

**When to Generate:**
- Generate on first sync when market is created
- Reuse existing embedding infrastructure from `TrendingTopic`
- Batch backfill job for any markets missing embeddings

**Implementation:**
```python
# In PolymarketService._upsert_market(), after creating new market:
if not market.question_embedding:
    # Queue for embedding generation (async to not slow sync)
    from app.services.embedding import embedding_service
    market.question_embedding = embedding_service.generate_embedding(market.question)
```

**Backfill Job:**
```python
def backfill_market_embeddings():
    """Scheduled job to generate missing embeddings."""
    markets = PolymarketMarket.query.filter(
        PolymarketMarket.question_embedding == None,
        PolymarketMarket.is_active == True
    ).limit(50).all()

    for market in markets:
        try:
            market.question_embedding = embedding_service.generate_embedding(market.question)
        except Exception as e:
            logger.warning(f"Embedding generation failed for market {market.id}: {e}")

    db.session.commit()
```

### Rate Limiting Enhancements

**Current:** Simple counter-based rate limiting (sufficient for single worker)

**Future Optimizations:**
1. **Token Bucket Algorithm** - Smoother request distribution
2. **Redis-based Rate Limiting** - Required if running multiple workers
3. **Exponential Backoff on 429** - Already handled by `safe_api_call` decorator returning cached data

**Enhanced Rate Limiter (for future):**
```python
class TokenBucketRateLimiter:
    def __init__(self, rate: float, capacity: int):
        self.rate = rate  # tokens per second
        self.capacity = capacity
        self.tokens = capacity
        self.last_update = time.time()

    def acquire(self) -> bool:
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_update = now

        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False
```

### Matching Performance Optimizations

**Current Approach:**
1. Pre-filter by category (reduces candidate set significantly)
2. Embedding similarity on filtered candidates
3. Keyword fallback for markets without embeddings

**Future Optimizations (when market count grows):**

1. **pgvector for Vector Similarity:**
```sql
-- Add vector column
ALTER TABLE polymarket_market ADD COLUMN question_embedding_vec vector(1536);

-- Create index for fast similarity search
CREATE INDEX idx_pm_embedding ON polymarket_market
USING ivfflat (question_embedding_vec vector_cosine_ops) WITH (lists = 100);

-- Query
SELECT * FROM polymarket_market
WHERE category IN ('politics', 'elections')
ORDER BY question_embedding_vec <=> $topic_embedding
LIMIT 10;
```

2. **Similarity Score Caching:**
```python
class TopicMarketSimilarityCache(db.Model):
    """Cache for frequently computed similarities."""
    topic_id = db.Column(db.Integer, primary_key=True)
    market_id = db.Column(db.Integer, primary_key=True)
    similarity_score = db.Column(db.Float)
    computed_at = db.Column(db.DateTime)
    # TTL: 24 hours
```

3. **Pre-computed Match Candidates:**
- Nightly job computes top 5 market candidates per active topic
- Matcher reads from cache, only recomputes if cache miss

### Price Refresh Prioritization

**Enhanced Strategy:**
```python
def refresh_prices(self) -> Dict[str, int]:
    """Refresh prices with prioritization."""

    # Priority 1: Markets matched to recent topics (last 7 days)
    matched_markets = PolymarketMarket.query.join(TopicMarketMatch).join(
        TrendingTopic
    ).filter(
        TrendingTopic.created_at >= datetime.utcnow() - timedelta(days=7),
        PolymarketMarket.is_active == True
    ).distinct().all()

    # Priority 2: High-volume markets not yet refreshed
    high_volume_markets = PolymarketMarket.query.filter(
        PolymarketMarket.is_active == True,
        PolymarketMarket.volume_24h >= PolymarketMarket.HIGH_QUALITY_VOLUME,
        PolymarketMarket.id.notin_([m.id for m in matched_markets])
    ).limit(100).all()

    # Combine and refresh
    markets_to_refresh = matched_markets + high_volume_markets
    # ... rest of refresh logic
```

**Tiered Refresh Intervals:**
| Market Type | Refresh Interval |
|-------------|------------------|
| Matched to recent topic | 2 minutes |
| High volume ($10k+) | 5 minutes |
| Medium volume ($1k-$10k) | 15 minutes |
| Low volume | 1 hour |

### Admin UI Requirements

**Phase 1 (Minimal):**
- Market list view with search/filter
- Quality tier badges
- Last sync status
- Manual market search (test API)

**Phase 2 (Enhanced):**
- Topic-market match viewer
- Manual match override capability
- Market health dashboard (sync errors, stale markets)
- Match quality histogram

**Admin Routes:**
```python
# app/admin/polymarket_routes.py

@admin.route('/polymarket/markets')
def list_markets():
    """View all cached markets with filtering."""

@admin.route('/polymarket/matches')
def list_matches():
    """View topic-market matches with similarity scores."""

@admin.route('/polymarket/health')
def health_dashboard():
    """Sync status, error rates, market counts."""

@admin.route('/polymarket/search')
def search_markets():
    """Test search against Polymarket API."""
```

### Testing Enhancements

**Load Testing:**
```python
# tests/load/test_matching_performance.py

def test_matching_with_large_topic_set():
    """Ensure matching completes in reasonable time with many topics."""
    # Create 1000 topics, 500 markets
    # Run batch matching
    # Assert completes in < 60 seconds

def test_price_refresh_under_load():
    """Ensure price refresh handles many markets."""
    # Create 1000 markets
    # Run refresh
    # Assert API calls are batched efficiently
```

**Chaos Engineering:**
```python
# tests/chaos/test_api_failures.py

def test_brief_generation_during_api_outage():
    """Brief generation succeeds even when Polymarket is down."""
    with patch('requests.get', side_effect=ConnectionError):
        brief = generate_daily_brief()
        assert brief is not None
        assert all(item.market_signal is None for item in brief.items)

def test_partial_api_failure():
    """Handle intermittent API failures gracefully."""
    # Fail every 3rd request
    # Verify sync continues, stats show partial success
```

**A/B Testing Framework (Future):**
```python
# Feature flag for market signal display
def should_show_market_signal(user, brief_item):
    """A/B test market signal display."""
    if not current_app.config['POLYMARKET_AB_TEST_ENABLED']:
        return True

    # Hash user ID for consistent bucketing
    bucket = hash(user.id) % 100
    return bucket < current_app.config['POLYMARKET_AB_TEST_PERCENT']
```

### Date Parsing Enhancement

**Robust Date Parsing:**
```python
from dateutil import parser as date_parser

def _parse_date(self, date_str: str) -> Optional[datetime]:
    """Parse date string with multiple format support."""
    if not date_str:
        return None
    try:
        return date_parser.parse(date_str)
    except (ValueError, TypeError):
        logger.warning(f"Failed to parse date: {date_str}")
        return None
```

### Migration Data Backfill

**Post-Migration Backfill:**
```python
# migrations/versions/xxxx_add_polymarket_integration.py

def upgrade():
    # ... schema changes ...

    # Schedule embedding backfill (don't block migration)
    # This runs after migration completes
    pass

def data_migration():
    """Run after schema migration to backfill embeddings."""
    from app.services.polymarket.service import polymarket_service

    # Initial sync to populate markets
    polymarket_service.sync_all_markets()

    # Generate embeddings for all markets
    backfill_market_embeddings()
```

---

## Summary

This implementation provides:

1. **Full Automation** - No manual curation required; markets are automatically matched to topics using embeddings and keywords

2. **Graceful Degradation** - Every integration point handles failures silently; briefs always generate successfully

3. **Polymarket as Source** - First-class source type for paid briefings alongside RSS, Substack, etc.

4. **Consensus Divergence** - Highlights when community votes differ from market expectations

5. **DRY Principles** - Reuses existing embedding infrastructure, follows existing service patterns

6. **Quality Controls** - Volume/liquidity thresholds filter low-quality markets

7. **Clear UX** - Markets always labeled as "collective expectations, not certainty"

**Document Status:** Implementation Plan Approved
**Next Step:** Begin Phase 1 implementation
