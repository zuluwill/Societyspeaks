"""
Polymarket Integration Module

Provides prediction market data as a "fourth perspective" signal alongside
left/center/right media coverage in briefs and discussions.

Key Components:
- PolymarketService: API client for Gamma and CLOB APIs
- MarketMatcher: Automated matching between topics and markets
- PolymarketSourceAdapter: Integration with paid briefing system
"""

from app.polymarket.service import PolymarketService, polymarket_service
from app.polymarket.matcher import MarketMatcher, market_matcher
from app.polymarket.source_adapter import PolymarketSourceAdapter, polymarket_source_adapter

__all__ = [
    'PolymarketService',
    'polymarket_service',
    'MarketMatcher',
    'market_matcher',
    'PolymarketSourceAdapter',
    'polymarket_source_adapter',
]
