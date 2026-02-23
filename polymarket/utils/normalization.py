"""Utilities for normalizing data between Polymarket and Kalshi formats."""
from typing import Any, List, Optional, Dict
from datetime import datetime, timezone


def normalize_probability(price: float, source: str) -> float:
    """Convert price to normalized probability (0.0-1.0).
    
    Args:
        price: Raw price from API
        source: 'polymarket' or 'kalshi'
    
    Returns:
        Normalized probability between 0.0 and 1.0
    """
    if source == "polymarket":
        # Polymarket prices are already 0.0-1.0
        return max(0.0, min(1.0, float(price)))
    elif source == "kalshi":
        # Kalshi prices are in cents (0-100), convert to 0.0-1.0
        return max(0.0, min(1.0, float(price) / 100.0))
    else:
        raise ValueError(f"Unknown source: {source}")


def normalize_volume(volume: Any, source: str) -> Optional[float]:
    """Standardize volume units to USD.
    
    Args:
        volume: Raw volume value from API
        source: 'polymarket' or 'kalshi'
    
    Returns:
        Volume in USD, or None if not available
    """
    if volume is None:
        return None
    
    try:
        vol = float(volume)
        if vol < 0:
            return None
        
        if source == "polymarket":
            # Polymarket volume is typically in USDC (1:1 with USD)
            return vol
        elif source == "kalshi":
            # Kalshi volume should already be in USD
            return vol
        else:
            return vol  # Default: assume USD
    except (ValueError, TypeError):
        return None


def extract_tags(data: Dict[str, Any], source: str) -> List[str]:
    """Extract tags/categories from API response.
    
    Args:
        data: Raw API response dictionary
        source: 'polymarket' or 'kalshi'
    
    Returns:
        List of tag strings
    """
    tags = []
    
    if source == "polymarket":
        # Polymarket may have 'tags', 'categories', or 'topics'
        if "tags" in data and isinstance(data["tags"], list):
            tags.extend([str(tag) for tag in data["tags"]])
        if "categories" in data and isinstance(data["categories"], list):
            tags.extend([str(cat) for cat in data["categories"]])
        if "topics" in data and isinstance(data["topics"], list):
            tags.extend([str(topic) for topic in data["topics"]])
    elif source == "kalshi":
        # Kalshi may have 'category', 'subcategory', or 'tags'
        if "category" in data:
            tags.append(str(data["category"]))
        if "subcategory" in data:
            tags.append(str(data["subcategory"]))
        if "tags" in data and isinstance(data["tags"], list):
            tags.extend([str(tag) for tag in data["tags"]])
    
    # Remove duplicates and empty strings
    return list(set([tag.lower().strip() for tag in tags if tag.strip()]))


def parse_datetime(dt_str: Optional[str], source: str) -> Optional[datetime]:
    """Parse datetime string from API response.
    
    Args:
        dt_str: Datetime string from API
        source: 'polymarket' or 'kalshi'
    
    Returns:
        Parsed datetime object or None
    """
    if not dt_str:
        return None
    
    try:
        # Handle Z suffix (UTC) - strip Z and parse as naive, then attach UTC
        if dt_str.endswith("Z"):
            dt_str_clean = dt_str[:-1]
            dt = datetime.fromisoformat(dt_str_clean)
            return dt.replace(tzinfo=timezone.utc)

        # Handle timezone offsets like +00:00, -05:00
        # (datetime.fromisoformat doesn't support these in Python 3.9)
        if "T" in dt_str and ("+" in dt_str[10:] or dt_str.count("-") > 2):
            for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
                try:
                    return datetime.strptime(dt_str, fmt)
                except ValueError:
                    continue

        # Try basic ISO format (no timezone)
        if "T" in dt_str:
            return datetime.fromisoformat(dt_str)

        # Try other common formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(dt_str, fmt)
            except ValueError:
                continue

        return None
    except (ValueError, TypeError):
        return None


def build_market_url(market_id: str, source: str) -> str:
    """Build deep link URL for a market.
    
    Args:
        market_id: Market identifier
        source: 'polymarket' or 'kalshi'
    
    Returns:
        Full URL to market page
    """
    if source == "polymarket":
        # Polymarket uses slug or market ID
        return f"https://polymarket.com/market/{market_id}"
    elif source == "kalshi":
        # Kalshi uses ticker under /markets/
        return f"https://kalshi.com/markets/{market_id}"
    else:
        return ""
