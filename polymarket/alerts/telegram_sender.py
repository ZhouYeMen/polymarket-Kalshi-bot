"""Telegram bot notification sender."""
import aiohttp
import asyncio
import html
import time
from typing import Optional, Dict


class TelegramSender:
    """Sends alert messages to a Telegram chat via Bot API."""

    TELEGRAM_API_BASE = "https://api.telegram.org"
    MAX_MESSAGE_LENGTH = 4096

    def __init__(self, bot_token: str, chat_id: str, rate_limit: float = 1.0):
        """Initialize Telegram sender.

        Args:
            bot_token: Telegram bot token from BotFather
            chat_id: Target chat/channel ID
            rate_limit: Maximum messages per second
        """
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.rate_limit = rate_limit
        self._last_send_time: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self.enabled = bool(bot_token and chat_id)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _rate_limit_wait(self) -> None:
        now = time.time()
        elapsed = now - self._last_send_time
        min_interval = 1.0 / self.rate_limit
        if elapsed < min_interval:
            await asyncio.sleep(min_interval - elapsed)
        self._last_send_time = time.time()

    async def verify(self) -> bool:
        """Verify bot token by calling getMe.

        Returns:
            True if token is valid
        """
        if not self.enabled:
            return False
        try:
            session = await self._get_session()
            url = f"{self.TELEGRAM_API_BASE}/bot{self.bot_token}/getMe"
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a message to the configured Telegram chat.

        Args:
            text: Message text (HTML formatted by default)
            parse_mode: Parse mode ('HTML', 'MarkdownV2', or '' for plain text)

        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False

        if len(text) > self.MAX_MESSAGE_LENGTH:
            text = text[:self.MAX_MESSAGE_LENGTH - 3] + "..."

        await self._rate_limit_wait()

        url = f"{self.TELEGRAM_API_BASE}/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "disable_web_page_preview": False,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            session = await self._get_session()
            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return True
                body = await resp.text()
                print(f"[WARN] Telegram API error {resp.status}: {body}")
                if resp.status == 429:
                    try:
                        data = await resp.json()
                        retry_after = data.get("parameters", {}).get("retry_after", 5)
                        await asyncio.sleep(retry_after)
                    except Exception:
                        await asyncio.sleep(5)
                return False
        except Exception as e:
            print(f"[WARN] Failed to send Telegram message: {e}")
            return False

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # --- Formatting methods ---

    def format_spike_alert(self, spike_data: Dict) -> str:
        market = spike_data["market"]
        change_pct = spike_data.get("change_percentage", 0)
        current_prob = spike_data.get("current_probability", 0)
        prev_prob = spike_data.get("previous_probability", 0)
        direction = spike_data.get("direction", "")
        direction_prob = spike_data.get("direction_prob")
        e = html.escape

        if direction == "YES":
            header = "🚨 PROBABILITY SPIKE — YES ↑"
        elif direction == "NO":
            header = "🚨 PROBABILITY SPIKE — NO ↑"
        else:
            header = "🚨 PROBABILITY SPIKE DETECTED"

        lines = [
            f"<b>{header}</b>",
            "",
            f"<b>Market:</b> {e(market.title)}",
            f"<b>Platform:</b> {e(market.source.upper())}",
        ]

        if direction:
            lines.append(
                f"<b>Direction:</b> {direction} moved +{change_pct:.1f}pp "
                f"(now {direction_prob:.2%})"
            )

        lines.extend([
            f"<b>YES Price:</b> {prev_prob:.2%} → {current_prob:.2%}",
            f"<b>NO Price:</b> {1.0 - prev_prob:.2%} → {1.0 - current_prob:.2%}",
            f"<b>Change:</b> {change_pct:.2f} percentage points",
            f"<b>Time:</b> {market.last_updated.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            f"<a href=\"{e(market.url)}\">{e(market.url)}</a>",
        ])

        return "\n".join(lines)

    def format_volume_surge_alert(self, surge_data: Dict) -> str:
        market = surge_data["market"]
        e = html.escape

        lines = [
            "<b>📈 VOLUME SURGE DETECTED</b>",
            "",
            f"<b>Market:</b> {e(market.title)}",
            f"<b>Platform:</b> {e(market.source.upper())}",
            f"<b>Current Volume:</b> ${surge_data['current_volume']:,.2f}",
            f"<b>Average Volume (1hr):</b> ${surge_data['average_volume']:,.2f}",
            f"<b>Multiplier:</b> {surge_data['multiplier']:.2f}x",
            f"<b>Time:</b> {market.last_updated.strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "",
            f"<a href=\"{e(market.url)}\">{e(market.url)}</a>",
        ]

        return "\n".join(lines)

    def format_new_market_alert(self, market) -> str:
        e = html.escape

        tags_str = ", ".join(market.tags[:5]) if market.tags else "No tags"
        if market.tags and len(market.tags) > 5:
            tags_str += f" (+{len(market.tags) - 5} more)"

        created_str = (
            market.created_time.strftime('%Y-%m-%d %H:%M:%S UTC')
            if market.created_time else 'Unknown'
        )

        lines = [
            "<b>🆕 NEW MARKET CREATED</b>",
            "",
            f"<b>Market:</b> {e(market.title)}",
            f"<b>Platform:</b> {e(market.source.upper())}",
            f"<b>Initial Probability:</b> {market.probability:.2%}",
            f"<b>Tags:</b> {e(tags_str)}",
        ]

        if market.description:
            desc = market.description[:200] + "..." if len(market.description) > 200 else market.description
            lines.append(f"<b>Description:</b> {e(desc)}")

        lines.extend([
            f"<b>Created:</b> {created_str}",
            "",
            f"<a href=\"{e(market.url)}\">{e(market.url)}</a>",
        ])

        return "\n".join(lines)

    def format_large_trade_alert(self, trade: Dict, event_title: str, event_url: str) -> str:
        e = html.escape

        usd_value = trade.get("calculated_usd_value") or trade.get("usdValue") or trade.get("value", 0)
        size = trade.get("size", 0)
        price = trade.get("price", 0)
        outcome = trade.get("outcome", "Unknown")
        timestamp = trade.get("timestamp") or trade.get("time") or trade.get("created_at", "Unknown")

        lines = [
            "<b>💰 LARGE TRADE DETECTED</b>",
            "",
            f"<b>Event:</b> {e(str(event_title))}",
            f"<b>Trade Value:</b> ${float(usd_value):,.2f}",
            f"<b>Size:</b> {float(size):,.2f}",
            f"<b>Price:</b> {float(price):.4f}",
            f"<b>Outcome:</b> {e(str(outcome))}",
            f"<b>Time:</b> {e(str(timestamp))}",
            "",
            f"<a href=\"{e(str(event_url))}\">{e(str(event_url))}</a>",
        ]

        return "\n".join(lines)
