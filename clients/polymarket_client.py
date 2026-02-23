"""Polymarket API client for fetching market data."""
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
    build_market_url,
)
from utils.rate_limiter import RateLimitedSession, TokenBucketRateLimiter


class PolymarketClient:
    """Client for Polymarket Gamma and CLOB APIs."""
    
    def __init__(self, session: aiohttp.ClientSession):
        """Initialize Polymarket client.
        
        Args:
            session: aiohttp ClientSession
        """
        self.session = session
        self.rate_limiter = TokenBucketRateLimiter(config.POLYMARKET_RATE_LIMIT)
        self.rate_limited = RateLimitedSession(self.rate_limiter)
        self.gamma_base = config.POLYMARKET_GAMMA_BASE
        self.clob_base = config.POLYMARKET_CLOB_BASE
        self.data_base = "https://data-api.polymarket.com"  # Data API for trades
        self.headers = {"User-Agent": "Mozilla/5.0"}
        self.ws_connected = False
        self.ws_task: Optional[asyncio.Task] = None
    
    async def fetch_tags(self) -> List[Dict[str, Any]]:
        """Fetch available tags from Polymarket API.
        
        Returns:
            List of tag dictionaries
        """
        url = f"{self.gamma_base}/tags"
        params = {"limit": 200}
        
        try:
            async with self.rate_limited.get(
                self.session, url, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data.get("data", []) if isinstance(data, dict) else data
        except Exception as e:
            print(f"[WARN] Failed to fetch Polymarket tags: {e}")
            return []
    
    async def find_geopolitics_tag_id(self) -> Optional[str]:
        """Find the tag ID for geopolitics.
        
        Returns:
            Tag ID string or None
        """
        tags = await self.fetch_tags()
        for tag in tags:
            slug = tag.get("slug", "").lower()
            name = tag.get("name", "").lower()
            if "geopolitic" in slug or "geopolitic" in name:
                return str(tag.get("id") or tag.get("tag_id"))
        return None
    
    async def fetch_events(
        self,
        tag_slug: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        closed: bool = False
    ) -> List[Dict[str, Any]]:
        """Fetch events from Polymarket Gamma API.

        Args:
            tag_slug: Optional tag slug to filter by (e.g., "geopolitics")
            limit: Number of events to fetch per page
            offset: Pagination offset
            closed: Whether to include closed markets

        Returns:
            List of event dictionaries
        """
        url = f"{self.gamma_base}/events"
        params = {
            "limit": limit,
            "offset": offset,
            "closed": "true" if closed else "false",
            "active": "true",
        }
        if tag_slug:
            params["tag_slug"] = tag_slug

        try:
            async with self.rate_limited.get(
                self.session, url, params=params, headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                events = data.get("data", []) if isinstance(data, dict) else data
                if tag_slug:
                    print(f"[DEBUG] Fetched {len(events)} events with tag_slug={tag_slug}")
                return events
        except Exception as e:
            print(f"[ERROR] Failed to fetch Polymarket events: {e}")
            return []
    
    async def fetch_markets(
        self,
        limit: int = 100,
        offset: int = 0,
        closed: bool = False,
        tag_slug: Optional[str] = None
    ) -> List[MarketEvent]:
        """Fetch markets from Polymarket Gamma API.

        Args:
            limit: Number of markets to fetch per page
            offset: Pagination offset
            closed: Whether to include closed markets
            tag_slug: Optional tag slug to filter by (e.g., "geopolitics")

        Returns:
            List of MarketEvent objects
        """
        # Fetch events (better for category filtering via tag_slug)
        events = await self.fetch_events(tag_slug=tag_slug, limit=limit, offset=offset, closed=closed)

        markets = []
        for event in events:
            # Extract markets from event
            event_markets = event.get("markets", [])
            if not event_markets:
                market_event = self._parse_market(event)
                if market_event:
                    markets.append(market_event)
            else:
                for m in event_markets:
                    try:
                        market_event = self._parse_market(m)
                        if market_event:
                            markets.append(market_event)
                    except Exception as e:
                        print(f"[WARN] Failed to parse Polymarket market: {e}")
                        continue

        return markets
    
    async def fetch_all_active_markets(self, geopolitics_only: bool = True) -> List[MarketEvent]:
        """Fetch all active markets with pagination.

        Args:
            geopolitics_only: If True, only fetch geopolitics-tagged markets

        Returns:
            List of all active MarketEvent objects
        """
        all_markets = []
        offset = 0
        limit = 100
        tag_slug = "geopolitics" if geopolitics_only else None

        while True:
            batch = await self.fetch_markets(
                limit=limit,
                offset=offset,
                closed=False,
                tag_slug=tag_slug
            )
            if not batch:
                break

            all_markets.extend(batch)

            # If we got fewer than limit, we've reached the end
            if len(batch) < limit:
                break

            offset += limit

            # Safety limit to avoid infinite loops
            if offset > 10000:
                break

        return all_markets
    
    async def fetch_event_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Fetch an event by its slug.
        
        Args:
            slug: Event slug (e.g., "khamenei-out-as-supreme-leader-of-iran-by-january-31")
        
        Returns:
            Event dictionary with id, markets, etc., or None
        """
        url = f"{self.gamma_base}/events"
        params = {
            "slug": slug,
            "closed": "false",
            "active": "true",
        }
        
        try:
            async with self.rate_limited.get(
                self.session, url, params=params, headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

                # Response might be a list or dict with data field
                if isinstance(data, list) and len(data) > 0:
                    return data[0]
                elif isinstance(data, dict):
                    events = data.get("data", [])
                    if events:
                        return events[0]
                    # Sometimes the event itself is returned
                    if data.get("id") or data.get("slug"):
                        return data
                
                print(f"[WARN] Event not found for slug: {slug}")
                return None
        except Exception as e:
            print(f"[ERROR] Failed to fetch event by slug {slug}: {e}")
            return None
    
    async def fetch_trades_for_event(
        self,
        event_id: str,
        limit: int = 1000,
        offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Fetch trades for an event.
        
        Args:
            event_id: Event ID
            limit: Number of trades to fetch
            offset: Pagination offset
        
        Returns:
            List of trade dictionaries
        """
        url = f"{self.data_base}/trades"
        params = {
            "eventId": event_id,
            "limit": limit,
            "offset": offset,
        }
        
        try:
            async with self.rate_limited.get(
                self.session, url, params=params, headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

                # Response might be a list or dict with data field
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict):
                    return data.get("data", []) or data.get("trades", [])
                
                return []
        except Exception as e:
            print(f"[ERROR] Failed to fetch trades for event {event_id}: {e}")
            return []
    
    async def fetch_large_trades(
        self,
        event_id: str,
        min_usd: float = 5000.0,
        limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Fetch trades above a minimum USD value.
        
        Args:
            event_id: Event ID
            min_usd: Minimum trade value in USD
            limit: Maximum number of trades to fetch
        
        Returns:
            List of large trade dictionaries
        """
        all_trades = []
        offset = 0
        page_size = min(limit, 1000)
        
        while len(all_trades) < limit:
            trades = await self.fetch_trades_for_event(
                event_id,
                limit=page_size,
                offset=offset
            )
            
            if not trades:
                break
            
            # Calculate USD value for each trade
            # Trade format: size (shares), price (0-1), outcome, etc.
            for trade in trades:
                # Try multiple fields for USD value
                usd_value = (
                    trade.get("usdValue") or
                    trade.get("value") or
                    trade.get("usd_value") or
                    trade.get("amount") or
                    trade.get("cost")
                )
                
                if usd_value is None:
                    # Calculate from size and price
                    size = float(trade.get("size", 0) or trade.get("quantity", 0) or 0)
                    price = float(trade.get("price", 0) or trade.get("lastPrice", 0) or 0)
                    
                    # For Polymarket, if price is 0-1, it's a probability
                    # Size might be in shares or USD. Check if there's a priceUSD field
                    price_usd = trade.get("priceUSD") or trade.get("price_usd")
                    
                    if price_usd is not None:
                        # If we have USD price, use it
                        usd_value = size * float(price_usd)
                    elif price > 1.0:
                        # If price > 1, it might already be in USD
                        usd_value = size * price
                    else:
                        # Price is 0-1 (probability), size might be in USD already
                        # Or we need to multiply by some base value
                        # For now, assume size is in USD (common in prediction markets)
                        usd_value = size
                
                # Convert to float
                try:
                    usd_value = float(usd_value)
                except (ValueError, TypeError):
                    continue
                
                if usd_value >= min_usd:
                    trade["calculated_usd_value"] = usd_value
                    all_trades.append(trade)
            
            if len(trades) < page_size:
                break
            
            offset += page_size
            
            # Safety limit
            if offset > 100000:
                break
        
        # Sort by USD value descending
        all_trades.sort(key=lambda x: x.get("calculated_usd_value", 0), reverse=True)
        
        return all_trades[:limit]
    
    async def fetch_market_prices(self, market_id: str) -> Optional[Dict[str, Any]]:
        """Fetch current prices for a specific market from CLOB API.
        
        Args:
            market_id: Market identifier
        
        Returns:
            Dictionary with price data or None
        """
        url = f"{self.clob_base}/price"
        params = {"market": market_id}
        
        try:
            async with self.rate_limited.get(
                self.session, url, params=params, headers=self.headers,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data
        except Exception as e:
            print(f"[WARN] Failed to fetch price for market {market_id}: {e}")
            return None
    
    def _parse_market(self, data: Dict[str, Any]) -> Optional[MarketEvent]:
        """Parse Polymarket API response into MarketEvent.
        
        Args:
            data: Raw API response dictionary
        
        Returns:
            MarketEvent object or None
        """
        try:
            # Extract market ID (could be slug, id, or market_id)
            market_id = (
                data.get("slug") or
                data.get("id") or
                data.get("market_id") or
                data.get("token_id") or
                ""
            )
            
            if not market_id:
                return None
            
            # Extract title
            title = data.get("question") or data.get("title") or data.get("name") or ""
            
            # Extract description
            description = data.get("description") or data.get("long_description")
            
            # Extract tags
            tags = extract_tags(data, "polymarket")
            
            # Extract status
            status = data.get("status", "open").lower()
            if status in ("resolved", "closed"):
                status = "closed"
            else:
                status = "open"
            
            # Extract and normalize probability
            # outcomePrices is the most reliable field: '["0.45", "0.55"]' = [YES, NO]
            price = 0.0
            outcome_prices = data.get("outcomePrices")
            if outcome_prices:
                try:
                    parsed = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
                    if parsed:
                        price = float(parsed[0])
                except (json.JSONDecodeError, ValueError, IndexError):
                    pass
            if not price:
                price = (
                    data.get("last_price_decimal") or
                    data.get("probability") or
                    data.get("last_price") or
                    data.get("bestBid") or
                    0.0
                )
            probability = normalize_probability(price, "polymarket")
            
            # Extract volume
            volume = normalize_volume(
                data.get("volume") or data.get("volume_usd") or data.get("volume_24h"),
                "polymarket"
            )
            
            # Extract liquidity (if available)
            liquidity = None
            if "liquidity" in data:
                liquidity = float(data["liquidity"])
            elif "liquidity_usd" in data:
                liquidity = float(data["liquidity_usd"])
            
            # Parse timestamps
            created_time = parse_datetime(
                data.get("created_time") or data.get("created_at") or data.get("start_date"),
                "polymarket"
            )
            close_time = parse_datetime(
                data.get("close_time") or data.get("end_date") or data.get("expiration_date"),
                "polymarket"
            )
            
            # Build URL
            url = build_market_url(str(market_id), "polymarket")
            
            # Extract order book data — API provides bestBid/bestAsk per market
            best_bid = data.get("bestBid")
            best_ask = data.get("bestAsk")

            return MarketEvent(
                source="polymarket",
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
                yes_bid=float(best_bid) if best_bid is not None else None,
                yes_ask=float(best_ask) if best_ask is not None else None,
            )
        except Exception as e:
            print(f"[WARN] Error parsing Polymarket market: {e}")
            return None
    
    async def connect_websocket(self, callback) -> bool:
        """Attempt to connect to Polymarket WebSocket (if available).
        
        Args:
            callback: Async function to call with market updates
        
        Returns:
            True if connection successful, False otherwise
        """
        # Polymarket WebSocket endpoint may vary
        # This is a placeholder - actual implementation depends on API docs
        try:
            # TODO: Implement WebSocket connection when API details are available
            # For now, return False to use polling
            self.ws_connected = False
            return False
        except Exception as e:
            print(f"[WARN] WebSocket connection failed: {e}")
            self.ws_connected = False
            return False
    
    async def close(self):
        """Close client connections."""
        if self.ws_task:
            self.ws_task.cancel()
            try:
                await self.ws_task
            except asyncio.CancelledError:
                pass
        self.ws_connected = False
