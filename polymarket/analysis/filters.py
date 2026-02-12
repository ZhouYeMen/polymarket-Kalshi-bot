"""Filtering utilities for geopolitical market detection."""
from typing import List, Set
from models.market_event import MarketEvent
import config


def is_geopolitical(market: MarketEvent, keywords: List[str] = None) -> bool:
    """Check if a market matches geopolitical keywords.
    
    Args:
        market: MarketEvent to check
        keywords: Optional list of keywords (defaults to config.GEOPOLITICAL_KEYWORDS)
    
    Returns:
        True if market matches geopolitical criteria
    """
    if keywords is None:
        keywords = config.GEOPOLITICAL_KEYWORDS
    
    # Normalize keywords to lowercase
    keywords_lower = [kw.lower() for kw in keywords]
    
    # Check title (case-insensitive)
    title_lower = market.title.lower() if market.title else ""
    for keyword in keywords_lower:
        if keyword in title_lower:
            return True
    
    # Check description (case-insensitive)
    if market.description:
        desc_lower = market.description.lower()
        for keyword in keywords_lower:
            if keyword in desc_lower:
                return True
    
    # Check tags (case-insensitive)
    if market.tags:
        tags_lower = [tag.lower() if isinstance(tag, str) else str(tag).lower() 
                     for tag in market.tags]
        for tag in tags_lower:
            for keyword in keywords_lower:
                if keyword in tag or tag in keyword:
                    return True
    
    return False


def filter_new_markets(
    current_markets: List[MarketEvent],
    known_market_ids: Set[str]
) -> List[MarketEvent]:
    """Filter out markets that are already known.
    
    Args:
        current_markets: List of current MarketEvent objects
        known_market_ids: Set of known market unique IDs
    
    Returns:
        List of new MarketEvent objects that weren't in known_market_ids
    """
    new_markets = []
    
    for market in current_markets:
        unique_id = market.get_unique_id()
        if unique_id not in known_market_ids:
            new_markets.append(market)
            known_market_ids.add(unique_id)
    
    return new_markets


def filter_active_markets(markets: List[MarketEvent]) -> List[MarketEvent]:
    """Filter to only active/open markets.
    
    Args:
        markets: List of MarketEvent objects
    
    Returns:
        List of active MarketEvent objects
    """
    return [m for m in markets if m.is_active()]


def filter_geopolitical_markets(
    markets: List[MarketEvent],
    keywords: List[str] = None
) -> List[MarketEvent]:
    """Filter markets to only those matching geopolitical criteria.
    
    Args:
        markets: List of MarketEvent objects
        keywords: Optional list of keywords (defaults to config.GEOPOLITICAL_KEYWORDS)
    
    Returns:
        List of MarketEvent objects matching geopolitical criteria
    """
    return [m for m in markets if is_geopolitical(m, keywords)]
