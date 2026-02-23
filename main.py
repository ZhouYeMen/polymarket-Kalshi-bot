"""Main monitoring loop for geopolitical market tracking."""
import asyncio
import ssl
import aiohttp
import certifi
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import signal
import sys
import traceback

import config
from clients.polymarket_client import PolymarketClient
from clients.kalshi_client import KalshiClient
from models.market_event import MarketEvent
from alerts.notifier import AlertNotifier
from utils.persistence import StatePersistence


class MarketMonitor:
    """Main monitoring system for geopolitical markets."""

    def __init__(self):
        """Initialize the market monitor."""
        self.session: aiohttp.ClientSession = None
        self.polymarket_client: PolymarketClient = None
        self.kalshi_client: KalshiClient = None
        self.notifier = AlertNotifier()
        # Track last known probability per market for change detection
        self.last_probability: Dict[str, float] = {}
        self.persistence = StatePersistence(
            state_file=config.STATE_FILE if config.STATE_FILE else ""
        )
        self.known_market_ids: set = set()
        self.running = False
        self.poll_tasks: List[asyncio.Task] = []
        # Track specific events to monitor
        self.tracked_events: Dict[str, Dict] = {}
        self.known_trade_ids: Dict[str, datetime] = {}

    async def initialize(self):
        """Initialize clients and connections."""
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)
        self.session = aiohttp.ClientSession(connector=connector)
        self.polymarket_client = PolymarketClient(self.session)
        self.kalshi_client = KalshiClient(self.session)

        # Load persisted state
        market_ids, trade_ids = self.persistence.load_sets()
        self.known_market_ids = market_ids
        self.known_trade_ids = trade_ids

        self.notifier.notify_status(
            f"Loaded {len(self.known_market_ids)} known markets and "
            f"{len(self.known_trade_ids)} known trades from state file",
            style="dim"
        )

        # Verify Telegram bot if configured
        if self.notifier.telegram.enabled:
            valid = await self.notifier.telegram.verify()
            if valid:
                self.notifier.notify_status(
                    "Telegram bot verified successfully", style="green"
                )
            else:
                self.notifier.notify_status(
                    "[WARN] Telegram bot token verification failed", style="yellow"
                )

        self.notifier.notify_status(
            "Geopolitical Market Monitor initialized",
            style="bold green"
        )

    async def process_market_update(self, market: MarketEvent) -> None:
        """Process a single market update.

        Args:
            market: MarketEvent to process
        """
        unique_id = market.get_unique_id()
        is_new = unique_id not in self.known_market_ids

        if is_new:
            self.known_market_ids.add(unique_id)
            # Store initial probability, no alert on first sight
            self.last_probability[unique_id] = market.probability
            return

        # Check for probability change
        prev_prob = self.last_probability.get(unique_id)
        curr_prob = market.probability

        if prev_prob is not None:
            # Signed change: positive = YES up, negative = NO up
            raw_change = curr_prob - prev_prob
            change_pp = abs(raw_change) * 100
            threshold = config.PROBABILITY_CHANGE_THRESHOLD

            if change_pp >= threshold:
                # Determine direction: YES price increased or NO price increased
                if raw_change > 0:
                    direction = "YES"
                    direction_prob = curr_prob
                else:
                    direction = "NO"
                    direction_prob = 1.0 - curr_prob

                self.notifier.notify_spike({
                    "type": "spike",
                    "market": market,
                    "current_probability": curr_prob,
                    "previous_probability": prev_prob,
                    "change_percentage": change_pp,
                    "direction": direction,
                    "direction_prob": direction_prob,
                    "z_score": None,
                    "method": "probability_change",
                })

        # Always update the stored probability
        self.last_probability[unique_id] = curr_prob

    async def track_specific_event(self, event_slug: str, min_trade_usd: float = 5000.0) -> None:
        """Track a specific event for large trades.

        Args:
            event_slug: Event slug
            min_trade_usd: Minimum trade size in USD to alert on
        """
        try:
            # Fetch event by slug
            event = await self.polymarket_client.fetch_event_by_slug(event_slug)
            if not event:
                self.notifier.notify_status(
                    f"[WARN] Could not find event: {event_slug}",
                    style="yellow"
                )
                return

            event_id = str(event.get("id") or event.get("event_id") or "")
            if not event_id:
                self.notifier.notify_status(
                    f"[WARN] Event {event_slug} has no ID",
                    style="yellow"
                )
                return

            # Store event info
            event_title = event.get("title") or event.get("question") or event_slug
            event_url = f"https://polymarket.com/event/{event_slug}"

            self.tracked_events[event_id] = {
                "slug": event_slug,
                "title": event_title,
                "url": event_url,
                "min_trade_usd": min_trade_usd,
                "last_check": datetime.utcnow(),
            }

            self.notifier.notify_status(
                f"Now tracking event: {event_title} (ID: {event_id})",
                style="green"
            )

            # Fetch markets from event
            event_markets = event.get("markets", [])
            if event_markets:
                for market_data in event_markets:
                    market = self.polymarket_client._parse_market(market_data)
                    if market:
                        await self.process_market_update(market)
        except Exception as e:
            self.notifier.notify_status(
                f"[ERROR] Failed to track event {event_slug}: {e}",
                style="red"
            )

    def cleanup_known_trade_ids(self) -> int:
        """Remove old trade IDs to prevent unbounded growth.

        Returns:
            Number of entries removed.
        """
        cutoff = datetime.utcnow() - timedelta(hours=config.DATA_RETENTION_HOURS)
        old_ids = [
            tid for tid, ts in self.known_trade_ids.items()
            if ts < cutoff
        ]
        for tid in old_ids:
            del self.known_trade_ids[tid]
        return len(old_ids)

    async def check_tracked_events_trades(self) -> None:
        """Check for large trades in tracked events."""
        for event_id, event_info in self.tracked_events.items():
            try:
                # Fetch large trades
                large_trades = await self.polymarket_client.fetch_large_trades(
                    event_id,
                    min_usd=event_info["min_trade_usd"]
                )

                # Alert on new large trades
                for trade in large_trades:
                    # Create unique trade ID
                    trade_id = f"{event_id}:{trade.get('id')}:{trade.get('timestamp')}"

                    if trade_id not in self.known_trade_ids:
                        self.known_trade_ids[trade_id] = datetime.utcnow()
                        self.notifier.notify_large_trade(
                            trade,
                            event_info["title"],
                            event_info["url"]
                        )

                if large_trades:
                    self.notifier.notify_status(
                        f"Found {len(large_trades)} large trades (>= ${event_info['min_trade_usd']:,.0f}) for {event_info['title']}",
                        style="dim"
                    )

                # Update last check time
                event_info["last_check"] = datetime.utcnow()
            except Exception as e:
                self.notifier.notify_status(
                    f"[ERROR] Failed to check trades for {event_info['title']}: {e}",
                    style="red"
                )

    async def poll_tracked_events_trades(self) -> None:
        """Poll tracked events for large trades (runs more frequently)."""
        while self.running:
            try:
                if self.tracked_events:
                    await self.check_tracked_events_trades()

                # Cleanup old trade IDs
                removed = self.cleanup_known_trade_ids()
                if removed > 0:
                    self.notifier.notify_status(
                        f"Cleaned up {removed} old trade IDs", style="dim"
                    )

                # Check every 30 seconds for trades
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.notifier.notify_status(
                    f"[ERROR] Trade tracking error: {e}",
                    style="red"
                )
                await asyncio.sleep(30)

    async def poll_polymarket(self) -> None:
        """Poll Polymarket for market updates."""
        while self.running:
            try:
                self.notifier.notify_status(
                    f"[{datetime.utcnow().strftime('%H:%M:%S')}] Polling Polymarket...",
                    style="dim"
                )

                # Fetch all active markets (geopolitics only via tag_slug)
                markets = await self.polymarket_client.fetch_all_active_markets(geopolitics_only=True)

                # Filter by minimum volume
                vol_markets = [
                    m for m in markets
                    if m.volume is not None and m.volume >= config.MIN_VOLUME
                ]

                # Filter by max spread (if configured)
                if config.MAX_SPREAD > 0:
                    vol_markets = [
                        m for m in vol_markets
                        if m.get_spread() is None or m.get_spread() <= config.MAX_SPREAD
                    ]

                self.notifier.notify_status(
                    f"Found {len(vol_markets)} geopolitical markets on Polymarket with >${config.MIN_VOLUME/1000:.0f}K volume "
                    f"(out of {len(markets)} total)",
                    style="dim"
                )

                # Process each market
                for market in vol_markets:
                    await self.process_market_update(market)

                # Wait for next poll
                await asyncio.sleep(config.POLYMARKET_POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.notifier.notify_status(
                    f"[ERROR] Polymarket polling error: {e}",
                    style="red"
                )
                await asyncio.sleep(config.POLYMARKET_POLL_INTERVAL)

    async def poll_kalshi(self) -> None:
        """Poll Kalshi for market updates."""
        while self.running:
            try:
                self.notifier.notify_status(
                    f"[{datetime.utcnow().strftime('%H:%M:%S')}] Polling Kalshi...",
                    style="dim"
                )

                # Fetch geopolitical markets (Politics + World categories)
                markets = await self.kalshi_client.fetch_all_active_markets(geopolitics_only=True)

                # Filter by minimum volume
                vol_markets = [
                    m for m in markets
                    if m.volume is not None and m.volume >= config.MIN_VOLUME
                ]

                # Filter by max spread (if configured)
                if config.MAX_SPREAD > 0:
                    vol_markets = [
                        m for m in vol_markets
                        if m.get_spread() is None or m.get_spread() <= config.MAX_SPREAD
                    ]

                self.notifier.notify_status(
                    f"Found {len(vol_markets)} geopolitical markets on Kalshi with >${config.MIN_VOLUME/1000:.0f}K volume "
                    f"(out of {len(markets)} total)",
                    style="dim"
                )

                # Process each market
                for market in vol_markets:
                    await self.process_market_update(market)

                # Wait for next poll
                await asyncio.sleep(config.KALSHI_POLL_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.notifier.notify_status(
                    f"[ERROR] Kalshi polling error: {e}",
                    style="red"
                )
                await asyncio.sleep(config.KALSHI_POLL_INTERVAL)

    async def websocket_polymarket_handler(self, market: MarketEvent) -> None:
        """Handle WebSocket updates from Polymarket."""
        await self.process_market_update(market)

    async def websocket_kalshi_handler(self, market: MarketEvent) -> None:
        """Handle WebSocket updates from Kalshi."""
        await self.process_market_update(market)

    async def connect_websockets(self) -> None:
        """Attempt to connect WebSockets for Polymarket."""
        try:
            polymarket_ws = await self.polymarket_client.connect_websocket(
                self.websocket_polymarket_handler
            )
            if polymarket_ws:
                self.notifier.notify_status(
                    "Connected to Polymarket WebSocket", style="green"
                )
            else:
                self.notifier.notify_status(
                    "Polymarket WebSocket not available, using polling", style="yellow"
                )
        except Exception as e:
            self.notifier.notify_status(
                f"Polymarket WebSocket failed: {e}, using polling", style="yellow"
            )

    async def periodic_state_save(self) -> None:
        """Periodically save state to disk."""
        while self.running:
            try:
                await asyncio.sleep(300)  # Every 5 minutes
                self.persistence.save(self.known_market_ids, self.known_trade_ids)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.notifier.notify_status(
                    f"[WARN] Failed to save state: {e}", style="yellow"
                )

    async def run(self, track_event_slug: Optional[str] = None) -> None:
        """Run the main monitoring loop.

        Args:
            track_event_slug: Optional event slug to track for large trades
        """
        await self.initialize()

        self.running = True

        # Track specific event if provided
        if track_event_slug:
            await self.track_specific_event(
                track_event_slug, min_trade_usd=config.MIN_TRADE_USD
            )

        # Attempt WebSocket connections (only if Polymarket is enabled)
        if config.ENABLE_POLYMARKET:
            await self.connect_websockets()

        # Start polling tasks (skip disabled platforms)
        self.poll_tasks = [
            asyncio.create_task(self.periodic_state_save()),
        ]
        if config.ENABLE_POLYMARKET:
            self.poll_tasks.append(asyncio.create_task(self.poll_polymarket()))
        else:
            self.notifier.notify_status("Polymarket polling disabled", style="yellow")
        if config.ENABLE_KALSHI:
            self.poll_tasks.append(asyncio.create_task(self.poll_kalshi()))
        else:
            self.notifier.notify_status("Kalshi polling disabled", style="yellow")

        # Add trade tracking task if we have tracked events
        if self.tracked_events:
            self.poll_tasks.append(
                asyncio.create_task(self.poll_tracked_events_trades())
            )

        self.notifier.notify_status(
            "Monitoring started. Press Ctrl+C to stop.",
            style="bold cyan"
        )

        try:
            # Wait for all tasks
            await asyncio.gather(*self.poll_tasks)
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Shutdown and cleanup."""
        self.notifier.notify_status("Shutting down...", style="yellow")

        self.running = False

        # Cancel polling tasks
        for task in self.poll_tasks:
            task.cancel()

        # Wait for tasks to finish
        if self.poll_tasks:
            await asyncio.gather(*self.poll_tasks, return_exceptions=True)

        # Save state before shutdown
        self.persistence.save(self.known_market_ids, self.known_trade_ids)
        self.notifier.notify_status("State saved to disk", style="dim")

        # Close clients
        if self.polymarket_client:
            await self.polymarket_client.close()
        if self.kalshi_client:
            await self.kalshi_client.close()

        # Close notifier (Telegram session)
        await self.notifier.close()

        # Close session
        if self.session:
            await self.session.close()

        # Print summary
        alert_count = self.notifier.get_alert_count()
        print(f"Shutdown complete. Total alerts: {alert_count}")


async def main():
    """Main entry point."""
    # Get event slug from config or CLI arg
    event_slug = config.TRACK_EVENT_SLUG
    if len(sys.argv) > 1:
        event_slug = sys.argv[1]

    monitor = MarketMonitor()

    # Set up signal handlers using the event loop
    loop = asyncio.get_running_loop()

    def _handle_signal():
        monitor.running = False
        for task in monitor.poll_tasks:
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    await monitor.run(track_event_slug=event_slug if event_slug else None)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nGoodbye!")
    except Exception:
        print("\n" + "="*50)
        print("FATAL ERROR ENCOUNTERED")
        print("="*50)
        traceback.print_exc()
        print("="*50 + "\n")
        sys.exit(1)
