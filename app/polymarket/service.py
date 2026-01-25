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

import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from functools import wraps
import time

import requests
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

        # API returns a list directly, not a dict with 'markets' key
        if isinstance(response, list):
            return response
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
                        active_only: bool = True, closed: bool = False) -> List[Dict]:
        """
        Get all markets (paginated) for full sync.

        Args:
            limit: Max markets to return
            offset: Pagination offset
            active_only: Only return active markets (legacy flag)
            closed: If False, only return unclosed (current) markets

        Returns:
            List of market dicts
        """
        params = {
            'limit': limit,
            'offset': offset,
            'closed': closed
        }
        response = self._gamma_request('/markets', params=params)
        if not response:
            return []
        # API returns a list directly, not a dict with 'markets' key
        if isinstance(response, list):
            return response
        return response.get('markets', [])

    @safe_api_call(default_return=None)
    def get_current_price(self, token_id: str) -> Optional[float]:
        """
        Get current price for a token (outcome).

        Returns:
            Price as float (0-1) or None
        """
        response = self._clob_request('/price', params={'token_id': token_id})
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
        response = self._clob_request('/book', params={'token_id': token_id})
        return response

    # =========================================================================
    # EMBEDDING GENERATION
    # =========================================================================

    def generate_embedding(self, text: str) -> Optional[List[float]]:
        """
        Generate embedding for market question text.
        Uses the same OpenAI model as trending topics for consistency.

        Returns:
            Embedding vector or None on failure
        """
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, skipping embedding generation")
            return None

        try:
            import openai
            client = openai.OpenAI(api_key=api_key)

            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=text
            )

            return response.data[0].embedding

        except Exception as e:
            logger.warning(f"Embedding generation failed: {e}")
            return None

    def generate_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """
        Generate embeddings for multiple texts efficiently.

        Returns:
            List of embeddings (None for any that failed)
        """
        if not texts:
            return []

        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            logger.warning("OPENAI_API_KEY not set, skipping batch embedding generation")
            return [None] * len(texts)

        try:
            import openai
            client = openai.OpenAI(api_key=api_key)

            response = client.embeddings.create(
                model="text-embedding-3-small",
                input=texts
            )

            return [item.embedding for item in response.data]

        except Exception as e:
            logger.warning(f"Batch embedding generation failed: {e}")
            return [None] * len(texts)

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
        stats = {'created': 0, 'updated': 0, 'deactivated': 0, 'errors': 0, 'embeddings_generated': 0}
        seen_condition_ids = set()

        offset = 0
        limit = 500

        # Collect markets that need embeddings
        markets_needing_embeddings = []

        while True:
            # Fetch unclosed (current) markets - closed=False ensures we get active markets
            markets = self.get_all_markets(limit=limit, offset=offset, closed=False)
            if not markets:
                break

            for market_data in markets:
                try:
                    result, market_obj = self._upsert_market(market_data)
                    stats[result] += 1
                    condition_id = market_data.get('conditionId') or market_data.get('condition_id')
                    seen_condition_ids.add(condition_id)

                    # Track markets that need embeddings
                    if result == 'created' and market_obj and market_obj.is_high_quality:
                        markets_needing_embeddings.append(market_obj)

                except Exception as e:
                    logger.warning(f"Error syncing market {market_data.get('conditionId')}: {e}")
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

        # Generate embeddings for new high-quality markets (in batches)
        if markets_needing_embeddings:
            stats['embeddings_generated'] = self._generate_embeddings_for_markets(
                markets_needing_embeddings
            )

        logger.info(f"Polymarket sync complete: {stats}")
        return stats

    def _generate_embeddings_for_markets(self, markets: List[PolymarketMarket],
                                          batch_size: int = 50) -> int:
        """
        Generate embeddings for a list of markets in batches.

        Returns:
            Number of embeddings successfully generated
        """
        generated = 0

        for i in range(0, len(markets), batch_size):
            batch = markets[i:i + batch_size]
            texts = [m.question for m in batch]

            embeddings = self.generate_embeddings_batch(texts)

            for market, embedding in zip(batch, embeddings):
                if embedding:
                    market.question_embedding = embedding
                    generated += 1

            db.session.commit()

        return generated

    def refresh_prices(self, priority_market_ids: List[int] = None) -> Dict[str, int]:
        """
        Refresh prices for tracked markets.
        Called by scheduler every 5 minutes.

        Args:
            priority_market_ids: Optional list of market IDs to prioritize

        Returns:
            Stats dict: {'updated': N, 'errors': N}
        """
        stats = {'updated': 0, 'errors': 0}

        # Get markets that need price refresh
        stale_threshold = datetime.utcnow() - timedelta(seconds=self.CACHE_PRICE_DURATION)

        # Build query - prioritize specified markets
        if priority_market_ids:
            # Refresh priority markets first
            priority_markets = PolymarketMarket.query.filter(
                PolymarketMarket.id.in_(priority_market_ids),
                PolymarketMarket.is_active == True
            ).all()
        else:
            priority_markets = []

        # Then get other stale markets
        other_markets = PolymarketMarket.query.filter(
            PolymarketMarket.is_active == True,
            or_(
                PolymarketMarket.last_price_update_at == None,
                PolymarketMarket.last_price_update_at < stale_threshold
            )
        )

        if priority_market_ids:
            other_markets = other_markets.filter(
                ~PolymarketMarket.id.in_(priority_market_ids)
            )

        other_markets = other_markets.limit(200 - len(priority_markets)).all()

        markets = priority_markets + other_markets

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
                    # Only update if we don't have one, or if it's been 24 hours
                    if market.probability is not None:
                        if market.probability_24h_ago is None:
                            # First time setting it
                            market.probability_24h_ago = market.probability
                        elif market.last_price_update_at:
                            # Check if 24 hours have passed since last update
                            hours_since_last = (datetime.utcnow() - market.last_price_update_at).total_seconds() / 3600
                            if hours_since_last >= 24:
                                market.probability_24h_ago = market.probability
                        else:
                            # No previous update time, set it now
                            market.probability_24h_ago = market.probability

                    # Update probability (first outcome is typically "Yes")
                    if outcome_idx == 0:
                        market.probability = price

                    # Update outcomes array
                    if market.outcomes and len(market.outcomes) > outcome_idx:
                        outcomes = list(market.outcomes)  # Make mutable copy
                        outcomes[outcome_idx]['price'] = price
                        market.outcomes = outcomes

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

    def _upsert_market(self, data: Dict) -> tuple:
        """
        Insert or update market from API data.

        Returns:
            Tuple of ('created' or 'updated', market object)
        """
        import json
        
        # Map camelCase API fields to our expected format
        condition_id = data.get('conditionId') or data.get('condition_id')
        if not condition_id:
            raise ValueError("Market data missing conditionId")

        # Parse JSON strings if needed (API returns outcomes/clobTokenIds as JSON strings)
        outcomes = data.get('outcomes', [])
        if isinstance(outcomes, str):
            try:
                outcomes = json.loads(outcomes)
            except (json.JSONDecodeError, TypeError):
                outcomes = []
        
        clob_token_ids = data.get('clobTokenIds') or data.get('clob_token_ids', [])
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json.loads(clob_token_ids)
            except (json.JSONDecodeError, TypeError):
                clob_token_ids = []

        # Extract numeric values with fallbacks
        volume_24h = data.get('volume24hr') or data.get('volume_24h') or 0
        volume_total = data.get('volumeNum') or data.get('volume_total') or 0
        liquidity = data.get('liquidityNum') or data.get('liquidity') or 0
        
        market = PolymarketMarket.query.filter_by(condition_id=condition_id).first()

        if market:
            # Update existing
            market.slug = data.get('slug')
            market.question = data.get('question', market.question)
            market.description = data.get('description')
            market.category = data.get('category')
            market.tags = data.get('tags', [])
            market.outcomes = outcomes
            market.clob_token_ids = clob_token_ids
            market.volume_24h = volume_24h
            market.volume_total = volume_total
            market.liquidity = liquidity
            market.trader_count = data.get('trader_count', 0)
            market.end_date = self._parse_date(data.get('endDate') or data.get('end_date'))
            market.resolution = data.get('resolution')
            market.is_active = data.get('active', True)
            market.last_synced_at = datetime.utcnow()
            market.sync_failures = 0
            return ('updated', market)
        else:
            # Create new
            market = PolymarketMarket(
                condition_id=condition_id,
                slug=data.get('slug'),
                question=data.get('question', 'Unknown'),
                description=data.get('description'),
                category=data.get('category'),
                tags=data.get('tags', []),
                outcomes=outcomes,
                clob_token_ids=clob_token_ids,
                volume_24h=volume_24h,
                volume_total=volume_total,
                liquidity=liquidity,
                trader_count=data.get('trader_count', 0),
                end_date=self._parse_date(data.get('endDate') or data.get('end_date')),
                is_active=data.get('active', True),
                last_synced_at=datetime.utcnow()
            )
            db.session.add(market)
            return ('created', market)

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parse date string with multiple format support."""
        if not date_str:
            return None
        try:
            # Try standard ISO format first
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except (ValueError, AttributeError):
            # Fallback to dateutil parser for other formats
            try:
                from dateutil import parser as date_parser
                return date_parser.parse(date_str)
            except (ImportError, ValueError, TypeError):
                logger.warning(f"Failed to parse date: {date_str}")
                return None


# Singleton instance
polymarket_service = PolymarketService()
