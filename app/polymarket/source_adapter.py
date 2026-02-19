"""
Polymarket Source Adapter

Adapts Polymarket markets to work as an InputSource for paid briefings.
Converts markets into IngestedItems that flow through the normal briefing pipeline.

This allows paid users to add "Prediction Markets" as a source alongside RSS feeds,
Substack newsletters, etc.
"""

import logging
from datetime import datetime
from app.lib.time import utcnow_naive
from typing import List, Optional
import hashlib

from app import db
from app.models import InputSource, IngestedItem, PolymarketMarket
from sqlalchemy.exc import IntegrityError

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

            try:
                db.session.commit()
            except IntegrityError as e:
                # Handle race condition: another process inserted the same content
                db.session.rollback()
                logger.warning(f"Duplicate content detected during polymarket ingestion for source {source.id}: {e}")
                return []
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
            exclude_tags_lower = {tag.lower() for tag in exclude_tags}
            markets = [
                m for m in markets
                if not (set((tag.lower() for tag in (m.tags or []))) & exclude_tags_lower)
            ]

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
            item.updated_at = utcnow_naive()
            return item
        else:
            # Create new item
            item = IngestedItem(
                source_id=source.id,
                external_id=external_id,
                title=market.question,
                content_text=content_text,
                content_hash=content_hash,
                url=market.polymarket_url,
                published_at=market.first_seen_at or market.created_at or utcnow_naive(),
                fetched_at=utcnow_naive(),
                metadata_json=self._build_metadata(market)
            )
            db.session.add(item)
            return item

    def _format_market_content(self, market: PolymarketMarket) -> str:
        """Format market data as readable content for the briefing."""
        parts = [market.question]

        if market.description:
            parts.append(market.description)

        # Add market stats
        stats = []
        if market.probability is not None:
            stats.append(f"Current probability: {market.probability:.0%}")
        if market.change_24h is not None:
            direction = "up" if market.change_24h > 0 else "down"
            stats.append(f"24h change: {abs(market.change_24h):.1%} {direction}")
        if market.volume_24h:
            stats.append(f"24h volume: ${market.volume_24h:,.0f}")
        if market.trader_count:
            stats.append(f"Traders: {market.trader_count:,}")

        if stats:
            parts.append(" | ".join(stats))

        return "\n\n".join(parts)

    def _build_metadata(self, market: PolymarketMarket) -> dict:
        """Build metadata JSON for the ingested item."""
        return {
            'source_type': 'polymarket',
            'market_id': market.id,
            'condition_id': market.condition_id,
            'category': market.category,
            'probability': market.probability,
            'change_24h': market.change_24h,
            'volume_24h': market.volume_24h,
            'liquidity': market.liquidity,
            'quality_tier': market.quality_tier,
            'end_date': market.end_date.isoformat() if market.end_date else None,
            'market_signal': market.to_signal_dict()
        }


# Singleton instance
polymarket_source_adapter = PolymarketSourceAdapter()
