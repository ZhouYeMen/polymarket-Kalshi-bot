"""Kalshi API client for fetching market data."""
import aiohttp
import asyncio
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
import config
from models.market_event import MarketEvent
from utils.normalization import (
    normalize_probability,
    normalize_volume,
    extract_tags,
    parse_datetime,
)
from utils.rate_limiter import RateLimitedSession, TokenBucketRateLimiter

# Categories on Kalshi that map to geopolitics
KALSHI_GEO_CATEGORIES = {"Politics", "World"}


class KalshiClient:
    """Client for Kalshi REST API."""

    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.rate_limiter = TokenBucketRateLimiter(config.KALSHI_RATE_LIMIT)
        self.rate_limited = RateLimitedSession(self.rate_limiter)
        self.base_url = config.KALSHI_BASE
        self.headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
        if config.KALSHI_API_KEY and config.KALSHI_API_SECRET:
            self.headers["Authorization"] = f"Bearer {config.KALSHI_API_KEY}"

    async def fetch_events(
        self,
        limit: int = 100,
        cursor: Optional[str] = None,
        status: str = "open",
        with_nested_markets: bool = True,
    ) -> tuple:
        """Fetch events from Kalshi API.

        Args:
            limit: Number of events per page
            cursor: Pagination cursor
            status: Event status filter
            with_nested_markets: Include nested market data

        Returns:
            Tuple of (events list, next_cursor string or None)
        """
        url = f"{self.base_url}/events"
        params = {
            "limit": limit,
            "status": status,
            "with_nested_markets": "true" if with_nested_markets else "false",
        }
        if cursor:
            params["cursor"] = cursor

        try:
            async with self.rate_limited.get(
                self.session, url, params=params, headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                events = data.get("events", [])
                next_cursor = data.get("cursor", "")
                return events, next_cursor if next_cursor else None
        except Exception as e:
            print(f"[ERROR] Failed to fetch Kalshi events: {e}")
            return [], None

    async def fetch_all_active_markets(self, geopolitics_only: bool = True) -> List[MarketEvent]:
        """Fetch all active geopolitical markets via the events endpoint.

        Args:
            geopolitics_only: If True, only return Politics/World category markets

        Returns:
            List of MarketEvent objects
        """
        all_markets = []
        cursor = None

        for page in range(10):  # Safety limit
            events, next_cursor = await self.fetch_events(
                limit=100, cursor=cursor, status="open"
            )
            if not events:
                break

            for event in events:
                category = event.get("category", "")
                if geopolitics_only and category not in KALSHI_GEO_CATEGORIES:
                    continue

                # Parse nested markets, passing event-level data for URL construction
                for m in event.get("markets", []):
                    market_event = self._parse_market(m, event)
                    if market_event:
                        all_markets.append(market_event)

            # Use cursor for next page
            if not next_cursor or len(events) < 100:
                break
            cursor = next_cursor

        return all_markets

    @staticmethod
    def _build_kalshi_url(data: Dict[str, Any], event: Optional[Dict[str, Any]]) -> str:
        """Build Kalshi web URL from event and market data.

        Uses format: https://kalshi.com/markets/{series_ticker}/{event_ticker}
        which auto-redirects to the canonical URL with the correct slug.
        The KX prefix is stripped as the web UI doesn't use it.
        """
        event = event or {}
        series_ticker = (event.get("series_ticker") or "").lower()
        event_ticker = (
            data.get("event_ticker") or event.get("event_ticker") or ""
        ).lower()

        # Strip KX prefix — web URLs don't use it
        if series_ticker.startswith("kx"):
            series_ticker = series_ticker[2:]
        if event_ticker.startswith("kx"):
            event_ticker = event_ticker[2:]

        if series_ticker and event_ticker:
            return f"https://kalshi.com/markets/{series_ticker}/{event_ticker}"
        elif event_ticker:
            return f"https://kalshi.com/markets/{event_ticker}"
        else:
            ticker = (data.get("ticker") or "").lower()
            if ticker.startswith("kx"):
                ticker = ticker[2:]
            return f"https://kalshi.com/markets/{ticker}"

    def _parse_market(self, data: Dict[str, Any], event: Optional[Dict[str, Any]] = None) -> Optional[MarketEvent]:
        """Parse Kalshi market data into MarketEvent."""
        try:
            market_id = data.get("ticker") or data.get("market_id") or data.get("id") or ""
            if not market_id:
                return None

            title = data.get("title") or data.get("question") or data.get("subtitle") or ""
            description = data.get("rules_primary") or data.get("subtitle")
            tags = extract_tags(data, "kalshi")

            status = data.get("status", "open").lower()
            if status in ("closed", "settled", "resolved"):
                status = "closed"
            else:
                status = "open"

            # Kalshi uses cent prices (0-100)
            price = (
                data.get("last_price") or
                data.get("yes_bid") or
                data.get("yes_ask") or
                0
            )
            probability = normalize_probability(price, "kalshi")

            volume = normalize_volume(
                data.get("volume") or data.get("volume_24h"),
                "kalshi"
            )

            liquidity = None
            if "liquidity" in data:
                liquidity = float(data["liquidity"])

            created_time = parse_datetime(
                data.get("created_time") or data.get("open_time"),
                "kalshi"
            )
            close_time = parse_datetime(
                data.get("close_time") or data.get("expiration_time"),
                "kalshi"
            )

            url = self._build_kalshi_url(data, event)

            yes_bid = data.get("yes_bid")
            no_bid = data.get("no_bid")
            yes_ask = data.get("yes_ask")
            no_ask = data.get("no_ask")

            return MarketEvent(
                source="kalshi",
                market_id=str(market_id),
                title=title,
                description=description,
                tags=tags,
                status=status,
                probability=probability,
                volume=volume,
                liquidity=liquidity,
                created_time=created_time,
                close_time=close_time,
                last_updated=datetime.utcnow(),
                url=url,
                yes_bid=float(yes_bid) if yes_bid is not None else None,
                no_bid=float(no_bid) if no_bid is not None else None,
                yes_ask=float(yes_ask) if yes_ask is not None else None,
                no_ask=float(no_ask) if no_ask is not None else None,
            )
        except Exception as e:
            print(f"[WARN] Error parsing Kalshi market: {e}")
            return None

    async def close(self):
        """Close client connections."""
        pass
