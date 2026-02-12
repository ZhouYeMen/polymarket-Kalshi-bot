"""Alert notification system using rich console formatting and Telegram."""
import asyncio
from typing import Dict, List
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from models.market_event import MarketEvent
import config
from alerts.telegram_sender import TelegramSender


class AlertNotifier:
    """Formats and displays alerts using rich library, with optional Telegram delivery."""

    def __init__(self):
        """Initialize alert notifier."""
        self.console = Console()
        self.alert_count = 0
        self.telegram = TelegramSender(
            bot_token=config.TELEGRAM_BOT_TOKEN,
            chat_id=config.TELEGRAM_CHAT_ID,
            rate_limit=config.TELEGRAM_RATE_LIMIT,
        )
        self._send_status_to_telegram = config.TELEGRAM_SEND_STATUS

    def _schedule_telegram(self, coro) -> None:
        """Schedule an async Telegram send as a background task."""
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            pass

    def notify_spike(self, spike_data: Dict) -> None:
        """Display a probability spike alert.

        Args:
            spike_data: Dictionary with spike information from SpikeDetector
        """
        market = spike_data["market"]
        change_pct = spike_data.get("change_percentage", 0)
        current_prob = spike_data.get("current_probability", 0)
        direction = spike_data.get("direction", "")
        direction_prob = spike_data.get("direction_prob")

        # Create alert panel with direction
        if direction == "YES":
            title = Text(f"🚨 PROBABILITY SPIKE — YES ↑", style="bold red")
        elif direction == "NO":
            title = Text(f"🚨 PROBABILITY SPIKE — NO ↑", style="bold red")
        else:
            title = Text("🚨 PROBABILITY SPIKE DETECTED", style="bold red")

        # Build content
        prev_prob = spike_data.get("previous_probability") or spike_data.get("previous_mean", 0)
        content_lines = [
            f"[bold]Market:[/bold] {market.title}",
            f"[bold]Platform:[/bold] {market.source.upper()}",
        ]

        if direction:
            content_lines.append(
                f"[bold]Direction:[/bold] {direction} moved +{change_pct:.1f}pp "
                f"(now {direction_prob:.2%})"
            )

        content_lines.extend([
            f"[bold]YES Price:[/bold] {prev_prob:.2%} → {current_prob:.2%}",
            f"[bold]NO Price:[/bold] {1.0 - prev_prob:.2%} → {1.0 - current_prob:.2%}",
            f"[bold]Change:[/bold] {change_pct:.2f} percentage points",
            f"[bold]Time:[/bold] {market.last_updated.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            f"[link={market.url}]{market.url}[/link]",
        ])

        content = "\n".join(content_lines)

        panel = Panel(
            content,
            title=title,
            border_style="red",
            box=box.ROUNDED,
            padding=(1, 2),
        )

        self.console.print(panel)
        self.alert_count += 1

        if self.telegram.enabled:
            msg = self.telegram.format_spike_alert(spike_data)
            self._schedule_telegram(self.telegram.send_message(msg))

    def notify_volume_surge(self, surge_data: Dict) -> None:
        """Display a volume surge alert.

        Args:
            surge_data: Dictionary with volume surge information from SpikeDetector
        """
        market = surge_data["market"]
        current_volume = surge_data["current_volume"]
        avg_volume = surge_data["average_volume"]
        multiplier = surge_data["multiplier"]

        # Create alert panel
        title = Text("📈 VOLUME SURGE DETECTED", style="bold yellow")

        content_lines = [
            f"[bold]Market:[/bold] {market.title}",
            f"[bold]Platform:[/bold] {market.source.upper()}",
            f"[bold]Current Volume:[/bold] ${current_volume:,.2f}",
            f"[bold]Average Volume (1hr):[/bold] ${avg_volume:,.2f}",
            f"[bold]Multiplier:[/bold] {multiplier:.2f}x",
            f"[bold]Time:[/bold] {market.last_updated.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            f"[link={market.url}]{market.url}[/link]",
        ]

        content = "\n".join(content_lines)

        panel = Panel(
            content,
            title=title,
            border_style="yellow",
            box=box.ROUNDED,
            padding=(1, 2),
        )

        self.console.print(panel)
        self.alert_count += 1

        if self.telegram.enabled:
            msg = self.telegram.format_volume_surge_alert(surge_data)
            self._schedule_telegram(self.telegram.send_message(msg))

    def notify_new_market(self, market: MarketEvent) -> None:
        """Display a new market alert.

        Args:
            market: Newly created MarketEvent
        """
        title = Text("🆕 NEW MARKET CREATED", style="bold green")

        tags_str = ", ".join(market.tags[:5]) if market.tags else "No tags"
        if market.tags and len(market.tags) > 5:
            tags_str += f" (+{len(market.tags) - 5} more)"

        content_lines = [
            f"[bold]Market:[/bold] {market.title}",
            f"[bold]Platform:[/bold] {market.source.upper()}",
            f"[bold]Initial Probability:[/bold] {market.probability:.2%}",
            f"[bold]Tags:[/bold] {tags_str}",
            f"[bold]Created:[/bold] {market.created_time.strftime('%Y-%m-%d %H:%M:%S UTC') if market.created_time else 'Unknown'}",
            "",
            f"[link={market.url}]{market.url}[/link]",
        ]

        if market.description:
            # Truncate long descriptions
            desc = market.description[:200] + "..." if len(market.description) > 200 else market.description
            content_lines.insert(3, f"[bold]Description:[/bold] {desc}")

        content = "\n".join(content_lines)

        panel = Panel(
            content,
            title=title,
            border_style="green",
            box=box.ROUNDED,
            padding=(1, 2),
        )

        self.console.print(panel)
        self.alert_count += 1

        if self.telegram.enabled:
            msg = self.telegram.format_new_market_alert(market)
            self._schedule_telegram(self.telegram.send_message(msg))

    def notify_status(self, message: str, style: str = "blue") -> None:
        """Display a status message.

        Args:
            message: Status message to display
            style: Style for the message
        """
        self.console.print(f"[{style}]{message}[/{style}]")

        if self._send_status_to_telegram and self.telegram.enabled:
            self._schedule_telegram(self.telegram.send_message(message, parse_mode=""))

    def print_summary_table(self, markets: List[MarketEvent]) -> None:
        """Print a summary table of monitored markets.

        Args:
            markets: List of MarketEvent objects to display
        """
        if not markets:
            return

        table = Table(title="Monitored Markets", box=box.ROUNDED)
        table.add_column("Platform", style="cyan")
        table.add_column("Market", style="white")
        table.add_column("Probability", justify="right", style="green")
        table.add_column("Volume", justify="right", style="yellow")
        table.add_column("Status", style="magenta")

        for market in markets[:20]:  # Limit to 20 for readability
            volume_str = f"${market.volume:,.2f}" if market.volume else "N/A"
            table.add_row(
                market.source.upper(),
                market.title[:50] + "..." if len(market.title) > 50 else market.title,
                f"{market.probability:.2%}",
                volume_str,
                market.status,
            )

        if len(markets) > 20:
            table.add_row("", f"... and {len(markets) - 20} more", "", "", "")

        self.console.print(table)

    def notify_large_trade(self, trade: Dict, event_title: str, event_url: str) -> None:
        """Display a large trade alert.

        Args:
            trade: Trade dictionary with size, price, outcome, etc.
            event_title: Title of the event/market
            event_url: URL to the event/market
        """
        title = Text("💰 LARGE TRADE DETECTED", style="bold magenta")

        usd_value = trade.get("calculated_usd_value") or trade.get("usdValue") or trade.get("value", 0)
        size = trade.get("size", 0)
        price = trade.get("price", 0)
        outcome = trade.get("outcome", "Unknown")
        timestamp = trade.get("timestamp") or trade.get("time") or trade.get("created_at", "Unknown")

        content_lines = [
            f"[bold]Event:[/bold] {event_title}",
            f"[bold]Trade Value:[/bold] ${usd_value:,.2f}",
            f"[bold]Size:[/bold] {size:,.2f}",
            f"[bold]Price:[/bold] {price:.4f}",
            f"[bold]Outcome:[/bold] {outcome}",
            f"[bold]Time:[/bold] {timestamp}",
            "",
            f"[link={event_url}]{event_url}[/link]",
        ]

        content = "\n".join(content_lines)

        panel = Panel(
            content,
            title=title,
            border_style="magenta",
            box=box.ROUNDED,
            padding=(1, 2),
        )

        self.console.print(panel)
        self.alert_count += 1

        if self.telegram.enabled:
            msg = self.telegram.format_large_trade_alert(trade, event_title, event_url)
            self._schedule_telegram(self.telegram.send_message(msg))

    def get_alert_count(self) -> int:
        """Get total number of alerts generated.

        Returns:
            Total alert count
        """
        return self.alert_count

    async def close(self) -> None:
        """Close resources (Telegram session)."""
        await self.telegram.close()
