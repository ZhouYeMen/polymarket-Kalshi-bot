"""Unified MarketEvent data model for normalizing Polymarket and Kalshi markets."""
from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class MarketEvent:
    """Unified representation of a market event from any platform.
    
    Normalizes differences between Polymarket (0.0-1.0 probability) 
    and Kalshi (1-99 cent pricing).
    """
    source: str  # 'polymarket' or 'kalshi'
    market_id: str  # Unique identifier (slug, ticker, token_id, etc.)
    title: str  # Market title / question
    description: Optional[str] = None
    tags: List[str] = field(default_factory=list)  # Keywords, categories/tags
    status: str = "open"  # 'open', 'closed', 'resolved', etc.
    probability: float = 0.0  # Normalized probability 0.0-1.0
    volume: Optional[float] = None  # Total volume/traded amount (in USD)
    liquidity: Optional[float] = None  # Bid-ask spread, depth, etc.
    created_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.utcnow)
    url: str = ""  # Deep link to market
    
    # Optional order book fields
    yes_bid: Optional[float] = None
    no_bid: Optional[float] = None
    yes_ask: Optional[float] = None
    no_ask: Optional[float] = None
    
    def __post_init__(self):
        """Validate probability is within bounds."""
        if not 0.0 <= self.probability <= 1.0:
            # Clamp to valid range
            self.probability = max(0.0, min(1.0, self.probability))
    
    def get_probability(self) -> float:
        """Returns the current implied probability (decimal 0-1).
        
        For Polymarket, probability is already 0-1.
        For Kalshi, should already be normalized from cents to 0-1.
        """
        return min(max(self.probability, 0.0), 1.0)
    
    def is_active(self) -> bool:
        """Check if market is currently active/open."""
        return self.status.lower() in ("open", "active", "trading")
    
    def get_unique_id(self) -> str:
        """Get a unique identifier combining source and market_id."""
        return f"{self.source}:{self.market_id}"
