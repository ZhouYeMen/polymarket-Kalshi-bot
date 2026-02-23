"""Polymarket Screener — browse all markets or zoom into a category.

Usage:
    python screener.py                         # All active markets
    python screener.py geopolitics             # Filter by tag
    python screener.py crypto                  # Filter by tag
    python screener.py --tags                  # List popular tags
    python screener.py geopolitics --refresh   # Auto-refresh every 60s
    python screener.py --min-vol 100000       # Override min volume filter
    python screener.py --img                  # Export as PNG image
    python screener.py geopolitics --img      # Export filtered view as PNG
    python screener.py --exclude-tags crypto-prices,sports-nba  # Exclude tags
    python screener.py --debug-api        # Dump raw API response for inspection
"""
import asyncio
import ssl
import json
import sys
import aiohttp
import certifi
from datetime import datetime, date
from typing import List, Dict, Any, Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

import config

console = Console()

# Popular tags grouped by category for the --tags listing
POPULAR_TAGS = {
    "Politics & World": [
        "geopolitics", "politics", "elections", "global-elections",
        "congress", "senate-elections", "trump", "trump-presidency",
        "foreign-policy", "immigration", "supreme-court",
    ],
    "Conflict & Military": [
        "military-action", "ukraine", "russia", "iran", "israel",
        "gaza", "middle-east", "nato", "syria",
    ],
    "Economy & Finance": [
        "economy", "fed", "fed-rates", "gdp", "stocks", "finance",
        "trade-war", "taxes", "deficit",
    ],
    "Crypto": [
        "crypto", "bitcoin", "crypto-prices", "stablecoins",
        "doge", "etfs", "airdrops",
    ],
    "Tech & AI": [
        "ai", "tech", "big-tech", "openai",
    ],
    "Sports": [
        "sports", "nba", "nhl", "soccer", "golf", "pga-tour",
        "champions-league", "EPL", "la-liga",
    ],
    "Culture": [
        "pop-culture", "celebrities", "movies", "music",
    ],
}


# ─── Data fetching ────────────────────────────────────────────────────────────

async def fetch_markets(
    session: aiohttp.ClientSession,
    tag_slug: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch active markets from Polymarket Gamma API.

    Args:
        session: aiohttp session
        tag_slug: Optional tag slug to filter (None = all markets)
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    all_markets = []
    offset = 0
    limit = 100

    label = tag_slug or "all"
    console.print(f"[dim]Fetching {label} markets...[/dim]", end="")

    while True:
        url = f"{config.POLYMARKET_GAMMA_BASE}/events"
        params = {
            "limit": limit,
            "offset": offset,
            "active": "true",
            "closed": "false",
        }
        if tag_slug:
            params["tag_slug"] = tag_slug

        try:
            async with session.get(url, params=params, headers=headers,
                                   timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                data = await resp.json()
                events = data if isinstance(data, list) else data.get("data", [])

                if not events:
                    break

                for event in events:
                    event_tags = event.get("tags", [])
                    # Normalize tags to list of slug strings
                    tag_slugs = []
                    if isinstance(event_tags, list):
                        for t in event_tags:
                            if isinstance(t, dict):
                                tag_slugs.append(t.get("slug", ""))
                            elif isinstance(t, str):
                                tag_slugs.append(t)

                    for m in event.get("markets", []):
                        # Skip resolved, closed, or non-trading markets
                        if m.get("closed"):
                            continue
                        if not m.get("active"):
                            continue
                        if not m.get("acceptingOrders"):
                            continue
                        if m.get("umaResolutionStatus") == "resolved":
                            continue
                        # Skip markets past their end date
                        end_iso = m.get("endDateIso") or ""
                        if end_iso:
                            try:
                                if date.fromisoformat(end_iso) < date.today():
                                    continue
                            except ValueError:
                                pass
                        m["_event_tags"] = tag_slugs
                        m["_event_title"] = event.get("title", "")
                        all_markets.append(m)

                if len(events) < limit:
                    break
                offset += limit

                if offset > 50000:
                    break
        except Exception as e:
            console.print(f"\n[red][ERROR] Failed to fetch markets: {e}[/red]")
            break

    console.print(f" [dim]got {len(all_markets)} markets[/dim]")
    return all_markets


async def debug_dump_api(tag_slug: Optional[str] = None) -> None:
    """Fetch one page of markets and dump the raw API response to a JSON file."""
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=connector) as session:
        headers = {"User-Agent": "Mozilla/5.0"}
        url = f"{config.POLYMARKET_GAMMA_BASE}/events"
        params = {"limit": 5, "offset": 0, "active": "true", "closed": "false"}
        if tag_slug:
            params["tag_slug"] = tag_slug

        async with session.get(url, params=params, headers=headers,
                               timeout=aiohttp.ClientTimeout(total=30)) as resp:
            resp.raise_for_status()
            data = await resp.json()

        out_path = "debug_api_response.json"
        with open(out_path, "w") as f:
            json.dump(data, f, indent=2)

        console.print(f"[bold green]Dumped raw API response → {out_path}[/bold green]")
        console.print(f"[dim]Contains {len(data) if isinstance(data, list) else '?'} events "
                      f"(first 5). Inspect the JSON for OI/liquidity fields.[/dim]")


def parse_market(m: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Parse raw API market data into a clean dictionary for display."""
    try:
        title = m.get("question") or m.get("title") or ""
        slug = m.get("slug") or ""

        # Parse YES/NO prices from outcomePrices
        yes_price = 0.0
        no_price = 0.0
        outcome_prices = m.get("outcomePrices")
        if outcome_prices:
            parsed = json.loads(outcome_prices) if isinstance(outcome_prices, str) else outcome_prices
            if len(parsed) >= 2:
                yes_price = float(parsed[0])
                no_price = float(parsed[1])

        volume = float(m.get("volumeNum") or m.get("volume") or 0)
        volume_1w = float(m.get("volume1wk") or 0)
        volume_1mo = float(m.get("volume1mo") or 0)

        # Attempt to extract 24-hour volume (field may not exist in API)
        _raw_1d = m.get("volume24hr") or m.get("volume_num_24hr") or m.get("volume24Hr")
        volume_1d = float(_raw_1d) if _raw_1d else None

        best_bid = m.get("bestBid")
        best_ask = m.get("bestAsk")

        # Compute spread from actual orderbook bid/ask if available
        if best_bid is not None and best_ask is not None:
            try:
                spread = float(best_ask) - float(best_bid)
                if spread < 0:
                    spread = 0.0
            except (ValueError, TypeError):
                spread = None
        else:
            spread = None

        one_day_chg = float(m.get("oneDayPriceChange") or 0)
        one_week_chg = float(m.get("oneWeekPriceChange") or 0)
        one_month_chg = float(m.get("oneMonthPriceChange") or 0)

        last_trade = float(m.get("lastTradePrice") or 0)
        tags = m.get("_event_tags", [])

        # Extract creation timestamp for "newly active" detection
        _created_raw = (
            m.get("startDate") or m.get("startDateIso")
            or m.get("createdAt") or m.get("created_at")
        )
        created_at = None
        if _created_raw:
            try:
                dt_str = str(_created_raw)
                if dt_str.endswith("Z"):
                    dt_str = dt_str[:-1]
                created_at = datetime.fromisoformat(dt_str)
            except (ValueError, TypeError):
                created_at = None

        url = f"https://polymarket.com/market/{slug}" if slug else ""

        return {
            "title": title,
            "slug": slug,
            "url": url,
            "yes": yes_price,
            "no": no_price,
            "spread": spread,
            "best_bid": float(best_bid) if best_bid is not None else None,
            "best_ask": float(best_ask) if best_ask is not None else None,
            "volume": volume,
            "volume_1w": volume_1w,
            "volume_1mo": volume_1mo,
            "volume_1d": volume_1d,
            "one_day_chg": one_day_chg,
            "one_week_chg": one_week_chg,
            "one_month_chg": one_month_chg,
            "last_trade": last_trade,
            "tags": tags,
            "created_at": created_at,
        }
    except Exception:
        return None


# ─── Formatting helpers ───────────────────────────────────────────────────────

def fmt_pct(val: float) -> str:
    return f"{val * 100:.1f}%"


def fmt_chg(val: float) -> Text:
    pct = val * 100
    if pct > 0:
        return Text(f"+{pct:.1f}%", style="green")
    elif pct < 0:
        return Text(f"{pct:.1f}%", style="red")
    return Text("0.0%", style="dim")


def fmt_chg_plain(val: float) -> str:
    """Plain string version of fmt_chg (no rich styling)."""
    pct = val * 100
    if pct > 0:
        return f"+{pct:.1f}%"
    elif pct < 0:
        return f"{pct:.1f}%"
    return "0.0%"


def fmt_vol(val: float) -> str:
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    elif val >= 1_000:
        return f"${val / 1_000:.1f}K"
    return f"${val:.0f}"


def fmt_spread(val: float) -> Text:
    pct = val * 100
    if pct <= 1:
        return Text(f"{pct:.1f}%", style="green")
    elif pct <= 3:
        return Text(f"{pct:.1f}%", style="yellow")
    return Text(f"{pct:.1f}%", style="red")


def truncate(text: str, max_len: int = 48) -> str:
    return text[:max_len - 1] + "…" if len(text) > max_len else text


# ─── Display: tag listing ─────────────────────────────────────────────────────

def show_tags() -> None:
    """Print available popular tags grouped by category."""
    console.print(Panel(
        "[bold]Usage:[/bold]  python screener.py <tag>\n"
        "   e.g. python screener.py geopolitics\n"
        "        python screener.py crypto\n"
        "        python screener.py nba",
        title="[bold cyan]Polymarket Screener — Available Tags[/bold cyan]",
        border_style="cyan",
        box=box.ROUNDED,
        padding=(1, 2),
    ))
    console.print()

    for category, tags in POPULAR_TAGS.items():
        tag_str = "  ".join(f"[bold cyan]{t}[/bold cyan]" for t in tags)
        console.print(f"  [bold]{category}:[/bold]  {tag_str}")

    console.print()
    console.print("[dim]Tip: Any tag_slug from Polymarket works, not just the ones listed above.[/dim]")


# ─── Display: summary panel ──────────────────────────────────────────────────

def show_summary(markets: List[Dict], tag_slug: Optional[str], timestamp: str,
                 target: Console = None,
                 excluded_count: int = 0,
                 exclude_tags: Optional[List[str]] = None) -> None:
    out = target or console
    total_vol = sum(m["volume"] for m in markets)
    total_vol_1w = sum(m["volume_1w"] for m in markets)
    spreads = [m["spread"] for m in markets if m["spread"] is not None]
    avg_spread = sum(spreads) / len(spreads) if spreads else 0

    # Top mover among non-settled markets only
    active_movers = [m for m in markets if 0.05 <= m["yes"] <= 0.95]
    top_mover = max(active_movers, key=lambda m: abs(m["one_day_chg"]), default=None)
    top_vol = max(markets, key=lambda m: m["volume_1w"], default=None)

    # Count markets with > $1M in 7D volume
    high_vol_7d = sum(1 for m in markets if m["volume_1w"] >= 1_000_000)

    stats = [
        f"[bold]Markets:[/bold] {len(markets)}",
        f"[bold]Total Volume:[/bold] {fmt_vol(total_vol)}",
        f"[bold]7D Volume:[/bold] {fmt_vol(total_vol_1w)}",
        f"[bold]Avg Spread:[/bold] {avg_spread * 100:.2f}%",
    ]

    if top_mover:
        chg = top_mover["one_day_chg"] * 100
        sign = "+" if chg > 0 else ""
        color = "green" if chg > 0 else "red"
        stats.append(
            f"[bold]Top Mover:[/bold] [{color}]{sign}{chg:.1f}%[/{color}] "
            f"{truncate(top_mover['title'], 35)}"
        )
    if top_vol:
        stats.append(
            f"[bold]Highest 7D Vol:[/bold] {fmt_vol(top_vol['volume_1w'])} "
            f"{truncate(top_vol['title'], 35)}"
        )
    if high_vol_7d > 0:
        stats.append(f"[bold]>$1M 7D Vol:[/bold] {high_vol_7d} markets")
    if excluded_count > 0 and exclude_tags:
        tag_list = ", ".join(exclude_tags[:5])
        stats.append(
            f"[bold]Excluded:[/bold] {excluded_count} markets "
            f"[dim]({tag_list})[/dim]"
        )

    line1 = "  |  ".join(stats[:4])
    line2 = "  |  ".join(stats[4:]) if len(stats) > 4 else ""
    content = line1 + ("\n" + line2 if line2 else "")

    label = tag_slug.upper() if tag_slug else "ALL MARKETS"
    panel = Panel(
        content,
        title=f"[bold cyan]POLYMARKET SCREENER — {label}[/bold cyan]  [dim]({timestamp})[/dim]",
        border_style="cyan",
        box=box.DOUBLE,
        padding=(0, 1),
    )
    out.print(panel)


# ─── Display: tables ─────────────────────────────────────────────────────────

def show_top_volume(markets: List[Dict], count: int = 30, target: Console = None) -> None:
    out = target or console
    # Sort by 7-day volume (recent activity), not all-time
    sorted_markets = sorted(markets, key=lambda m: m["volume_1w"], reverse=True)[:count]

    table = Table(
        title="[bold]Top Markets by 7D Volume[/bold]",
        title_style="bold white",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        pad_edge=False,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Market", ratio=1)
    table.add_column("YES", justify="right", width=6)
    table.add_column("Sprd", justify="right", width=5)
    table.add_column("7D Vol", justify="right", width=8)
    table.add_column("Total", justify="right", width=8)
    table.add_column("1D Chg", justify="right", width=7)

    for i, m in enumerate(sorted_markets, 1):
        yes_val = m["yes"] * 100
        if yes_val >= 70:
            yes_style = "bold green"
        elif yes_val >= 40:
            yes_style = "yellow"
        elif yes_val >= 10:
            yes_style = "white"
        else:
            yes_style = "dim"

        spread = m["spread"]
        if spread is not None:
            spread_text = fmt_spread(spread)
        else:
            spread_text = Text("-", style="dim")

        table.add_row(
            str(i),
            m["title"],
            Text(fmt_pct(m["yes"]), style=yes_style),
            spread_text,
            Text(fmt_vol(m["volume_1w"]), style="bold yellow"),
            Text(fmt_vol(m["volume"]), style="yellow"),
            fmt_chg(m["one_day_chg"]),
        )

    out.print(table)


def show_top_movers(markets: List[Dict], count: int = 15, target: Console = None) -> None:
    out = target or console
    # Filter: meaningful price change, actively traded, and sufficient liquidity
    # Exclude near-settled (YES <2% or >98%) and low-volume (<$500K) markets
    movers = [
        m for m in markets
        if abs(m["one_day_chg"]) > 0.001
        and 0.02 <= m["yes"] <= 0.98
        and m["volume"] >= 500_000
    ]
    sorted_movers = sorted(movers, key=lambda m: abs(m["one_day_chg"]), reverse=True)[:count]

    if not sorted_movers:
        return

    table = Table(
        title="[bold]Top Movers 24H (Price Change)[/bold]",
        title_style="bold white",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        pad_edge=False,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Market", ratio=1)
    table.add_column("YES", justify="right", width=6)
    table.add_column("1D Chg", justify="right", width=7)
    table.add_column("Volume", justify="right", width=8)
    table.add_column("Dir", justify="center", width=5)

    for i, m in enumerate(sorted_movers, 1):
        chg = m["one_day_chg"]
        direction = Text("YES↑", style="bold green") if chg > 0 else Text("NO↑", style="bold red")

        table.add_row(
            str(i),
            m["title"],
            Text(fmt_pct(m["yes"]), style="white"),
            fmt_chg(m["one_day_chg"]),
            Text(fmt_vol(m["volume"]), style="yellow"),
            direction,
        )

    out.print(table)


def show_top_movers_7d(markets: List[Dict], count: int = 15, target: Console = None) -> None:
    out = target or console
    movers = [
        m for m in markets
        if abs(m["one_week_chg"]) > 0.001
        and 0.02 <= m["yes"] <= 0.98
        and m["volume"] >= 500_000
    ]
    sorted_movers = sorted(movers, key=lambda m: abs(m["one_week_chg"]), reverse=True)[:count]

    if not sorted_movers:
        return

    table = Table(
        title="[bold]Top Movers 7D (Price Change)[/bold]",
        title_style="bold white",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        pad_edge=False,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Market", ratio=1)
    table.add_column("YES", justify="right", width=6)
    table.add_column("7D Chg", justify="right", width=7)
    table.add_column("Volume", justify="right", width=8)
    table.add_column("Dir", justify="center", width=5)

    for i, m in enumerate(sorted_movers, 1):
        chg = m["one_week_chg"]
        direction = Text("YES↑", style="bold green") if chg > 0 else Text("NO↑", style="bold red")

        table.add_row(
            str(i),
            m["title"],
            Text(fmt_pct(m["yes"]), style="white"),
            fmt_chg(m["one_week_chg"]),
            Text(fmt_vol(m["volume"]), style="yellow"),
            direction,
        )

    out.print(table)


def show_top_1d_volume(markets: List[Dict], count: int = 15, target: Console = None) -> None:
    """Display top markets by 24-hour trading volume.

    Skips entirely if 1D volume data is not available from the API.
    """
    out = target or console

    # Check if 1D volume data is available (any non-None, non-zero value)
    has_1d_vol = any(m.get("volume_1d") for m in markets)
    if not has_1d_vol:
        return

    vol_markets = [m for m in markets if m.get("volume_1d") and m["volume_1d"] > 0]
    sorted_markets = sorted(vol_markets, key=lambda m: m["volume_1d"], reverse=True)[:count]

    if not sorted_markets:
        return

    table = Table(
        title="[bold]Top Markets by 1D Volume[/bold]",
        title_style="bold white",
        box=box.SIMPLE_HEAVY,
        show_lines=False,
        pad_edge=False,
        padding=(0, 1),
        expand=True,
    )
    table.add_column("#", style="dim", width=3, justify="right")
    table.add_column("Market", ratio=1)
    table.add_column("YES", justify="right", width=6)
    table.add_column("NO", justify="right", width=6)
    table.add_column("Sprd", justify="right", width=5)
    table.add_column("1D Vol", justify="right", width=8)
    table.add_column("Total", justify="right", width=8)
    table.add_column("1D Chg", justify="right", width=7)

    for i, m in enumerate(sorted_markets, 1):
        yes_val = m["yes"] * 100
        if yes_val >= 70:
            yes_style = "bold green"
        elif yes_val >= 40:
            yes_style = "yellow"
        elif yes_val >= 10:
            yes_style = "white"
        else:
            yes_style = "dim"

        spread = m["spread"]
        if spread is not None:
            spread_text = fmt_spread(spread)
        else:
            spread_text = Text("-", style="dim")

        table.add_row(
            str(i),
            m["title"],
            Text(fmt_pct(m["yes"]), style=yes_style),
            Text(fmt_pct(m["no"]), style="white"),
            spread_text,
            Text(fmt_vol(m["volume_1d"]), style="bold yellow"),
            Text(fmt_vol(m["volume"]), style="yellow"),
            fmt_chg(m["one_day_chg"]),
        )

    out.print(table)


# ─── Image export ────────────────────────────────────────────────────────────

def _load_font(size: int):
    """Load a monospace font, falling back to default."""
    from PIL import ImageFont
    for path in (
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/SFMono-Regular.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _load_font_bold(size: int):
    """Load a bold monospace font, falling back to regular."""
    from PIL import ImageFont
    for path in (
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/SFMono-Bold.otf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return _load_font(size)


# Color palette for image rendering
_COLORS = {
    "bg": (15, 17, 23),
    "bg_alt": (22, 25, 33),
    "header_bg": (30, 55, 90),
    "border": (45, 50, 65),
    "title": (90, 200, 240),
    "text": (210, 215, 225),
    "dim": (100, 105, 120),
    "green": (75, 210, 115),
    "red": (235, 75, 75),
    "yellow": (240, 200, 60),
    "cyan": (80, 200, 230),
    "white": (235, 235, 240),
}


def _wrap_text(text: str, font, max_width: int, draw) -> List[str]:
    """Word-wrap text to fit within max_width pixels."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _draw_table(
    draw, font, font_bold,
    title: str,
    headers: List[str],
    rows: List[List[tuple]],
    col_widths: List[int],
    x_start: int, y_start: int,
    row_height: int = 28,
    wrap_col: int = 1,
) -> int:
    """Draw a styled table on the image with text wrapping.

    Args:
        rows: List of rows, each row is list of (text, color_name) tuples.
        col_widths: Pixel width for each column.
        wrap_col: Column index that supports text wrapping (default: 1 = Market).
        Returns: y position after the table.
    """
    C = _COLORS
    total_width = sum(col_widths) + 20

    # Title
    draw.text((x_start, y_start), title, fill=C["title"], font=font_bold)
    y = y_start + row_height + 4

    # Header row
    draw.rectangle(
        [x_start, y, x_start + total_width, y + row_height],
        fill=C["header_bg"],
    )
    cx = x_start + 8
    for i, header in enumerate(headers):
        draw.text((cx, y + 5), header, fill=C["cyan"], font=font_bold)
        cx += col_widths[i]
    y += row_height

    # Divider line
    draw.line(
        [(x_start, y), (x_start + total_width, y)],
        fill=C["border"], width=1,
    )

    # Data rows
    for row_idx, row in enumerate(rows):
        # Calculate row height based on wrapped text in the wrap column
        wrap_text = str(row[wrap_col][0]) if wrap_col < len(row) else ""
        wrap_font = font  # Market column uses regular font
        wrapped_lines = _wrap_text(wrap_text, wrap_font, col_widths[wrap_col] - 10, draw)
        actual_row_height = max(row_height, len(wrapped_lines) * (row_height - 6) + 6)

        bg = C["bg_alt"] if row_idx % 2 == 0 else C["bg"]
        draw.rectangle(
            [x_start, y, x_start + total_width, y + actual_row_height],
            fill=bg,
        )

        cx = x_start + 8
        for i, (text, color_name) in enumerate(row):
            color = C.get(color_name, C["text"])
            f = font_bold if color_name in ("green", "red", "yellow", "title") else font

            if i == wrap_col:
                # Draw wrapped text
                line_y = y + 5
                for line in wrapped_lines:
                    draw.text((cx, line_y), line, fill=color, font=f)
                    line_y += row_height - 6
            else:
                # Center other cells vertically
                draw.text((cx, y + 5), str(text), fill=color, font=f)

            cx += col_widths[i]

        y += actual_row_height

    # Bottom border
    draw.line(
        [(x_start, y), (x_start + total_width, y)],
        fill=C["border"], width=1,
    )

    return y + 10


def _render_single_table(
    title_text: str,
    table_title: str,
    headers: List[str],
    rows: List[List[tuple]],
    col_widths: List[int],
    timestamp: str,
    output_path: str,
) -> str:
    """Render a single table as a standalone JPG image.

    Returns:
        Path to the saved image file, or empty string on failure.
    """
    from PIL import Image, ImageDraw

    font_size = 15
    font = _load_font(font_size)
    font_bold = _load_font_bold(font_size)
    title_font = _load_font_bold(20)
    sub_font = _load_font(12)

    C = _COLORS
    padding = 35
    row_height = 28
    table_width = sum(col_widths) + 20
    img_width = table_width + padding * 2
    img_height_est = padding * 2 + 80 + (len(rows) + 5) * row_height * 3

    try:
        img = Image.new("RGB", (img_width, img_height_est), C["bg"])
        draw = ImageDraw.Draw(img)

        # Title banner
        draw.text((padding, padding), title_text, fill=C["title"], font=title_font)

        y = padding + 35

        # Draw the table
        y = _draw_table(
            draw, font, font_bold,
            table_title, headers, rows, col_widths,
            padding, y, row_height,
        )

        # Footer
        draw.text(
            (padding, y + 5),
            f"Polymarket Screener — {timestamp}",
            fill=C["dim"], font=sub_font,
        )

        # Crop to actual content
        final_height = y + padding
        img = img.crop((0, 0, img_width, final_height))

        img.save(output_path, "JPEG", quality=92)
        return output_path

    except Exception as e:
        console.print(f"[red]Failed to generate {output_path}: {e}[/red]")
        return ""


def export_to_image(
    markets: List[Dict],
    tag_slug: Optional[str],
    timestamp: str,
    output_prefix: str = "screener",
) -> List[str]:
    """Render each screener table as a separate JPG image.

    Returns:
        List of paths to the saved image files.
    """
    label = tag_slug.upper() if tag_slug else "ALL MARKETS"
    banner = f"POLYMARKET SCREENER — {label}"
    saved = []

    # ── Table 1: Top Movers 24H ────────────────────────────────────────────────
    movers = [
        m for m in markets
        if abs(m["one_day_chg"]) > 0.001
        and 0.02 <= m["yes"] <= 0.98
        and m["volume"] >= 500_000
    ]
    movers_sorted = sorted(movers, key=lambda m: abs(m["one_day_chg"]), reverse=True)[:15]
    mover_headers = ["#", "Market", "YES", "NO", "1D Chg", "7D Chg", "Volume", "Dir"]
    mover_widths = [35, 420, 70, 70, 80, 80, 90, 65]

    mover_rows = []
    for i, m in enumerate(movers_sorted, 1):
        chg_1d = m["one_day_chg"]
        chg_1d_color = "green" if chg_1d > 0 else "red"
        chg_7d = m["one_week_chg"]
        chg_7d_color = "green" if chg_7d > 0 else "red" if chg_7d < 0 else "dim"
        dir_text = "YES ↑" if chg_1d > 0 else "NO ↑"
        dir_color = "green" if chg_1d > 0 else "red"

        mover_rows.append([
            (str(i), "dim"),
            (m["title"], "text"),
            (fmt_pct(m["yes"]), "text"),
            (fmt_pct(m["no"]), "text"),
            (fmt_chg_plain(chg_1d), chg_1d_color),
            (fmt_chg_plain(chg_7d), chg_7d_color),
            (fmt_vol(m["volume"]), "yellow"),
            (dir_text, dir_color),
        ])

    if mover_rows:
        path = _render_single_table(
            banner, "TOP MOVERS 24H (PRICE CHANGE)",
            mover_headers, mover_rows, mover_widths,
            timestamp, f"{output_prefix}_movers_24h.jpg",
        )
        if path:
            saved.append(path)

    # ── Table 2: Top Movers 7D ──────────────────────────────────────────────
    movers_7d = [
        m for m in markets
        if abs(m["one_week_chg"]) > 0.001
        and 0.02 <= m["yes"] <= 0.98
        and m["volume"] >= 500_000
    ]
    movers_7d_sorted = sorted(movers_7d, key=lambda m: abs(m["one_week_chg"]), reverse=True)[:15]
    mover_7d_headers = ["#", "Market", "YES", "NO", "7D Chg", "1D Chg", "Volume", "Dir"]
    mover_7d_widths = [35, 420, 70, 70, 80, 80, 90, 65]

    mover_7d_rows = []
    for i, m in enumerate(movers_7d_sorted, 1):
        chg_7d = m["one_week_chg"]
        chg_7d_color = "green" if chg_7d > 0 else "red"
        chg_1d = m["one_day_chg"]
        chg_1d_color = "green" if chg_1d > 0 else "red" if chg_1d < 0 else "dim"
        dir_text = "YES ↑" if chg_7d > 0 else "NO ↑"
        dir_color = "green" if chg_7d > 0 else "red"

        mover_7d_rows.append([
            (str(i), "dim"),
            (m["title"], "text"),
            (fmt_pct(m["yes"]), "text"),
            (fmt_pct(m["no"]), "text"),
            (fmt_chg_plain(chg_7d), chg_7d_color),
            (fmt_chg_plain(chg_1d), chg_1d_color),
            (fmt_vol(m["volume"]), "yellow"),
            (dir_text, dir_color),
        ])

    if mover_7d_rows:
        path = _render_single_table(
            banner, "TOP MOVERS 7D (PRICE CHANGE)",
            mover_7d_headers, mover_7d_rows, mover_7d_widths,
            timestamp, f"{output_prefix}_movers_7d.jpg",
        )
        if path:
            saved.append(path)

    # ── Table 3: Top Markets by 7D Volume ────────────────────────────────────
    vol_sorted = sorted(markets, key=lambda m: m["volume_1w"], reverse=True)[:15]
    vol_headers = ["#", "Market", "YES", "NO", "Spread", "7D Vol", "Total", "1D Chg", "7D Chg"]
    vol_widths = [35, 420, 70, 70, 70, 90, 90, 80, 80]

    vol_rows = []
    for i, m in enumerate(vol_sorted, 1):
        chg_1d = m["one_day_chg"]
        chg_1d_color = "green" if chg_1d > 0 else "red" if chg_1d < 0 else "dim"
        chg_7d = m["one_week_chg"]
        chg_7d_color = "green" if chg_7d > 0 else "red" if chg_7d < 0 else "dim"
        yes_val = m["yes"]
        yes_color = "green" if yes_val >= 0.7 else "yellow" if yes_val >= 0.4 else "text"
        spread = m["spread"]
        if spread is not None:
            spread_color = "green" if spread <= 0.01 else "yellow" if spread <= 0.03 else "red"
            spread_str = f"{spread*100:.1f}%"
        else:
            spread_color = "dim"
            spread_str = "-"

        vol_rows.append([
            (str(i), "dim"),
            (m["title"], "text"),
            (fmt_pct(m["yes"]), yes_color),
            (fmt_pct(m["no"]), "text"),
            (spread_str, spread_color),
            (fmt_vol(m["volume_1w"]), "yellow"),
            (fmt_vol(m["volume"]), "yellow"),
            (fmt_chg_plain(chg_1d), chg_1d_color),
            (fmt_chg_plain(chg_7d), chg_7d_color),
        ])

    if vol_rows:
        path = _render_single_table(
            banner, "TOP MARKETS BY 7D VOLUME",
            vol_headers, vol_rows, vol_widths,
            timestamp, f"{output_prefix}_vol_7d.jpg",
        )
        if path:
            saved.append(path)

    # ── Table 4: Top 1D Volume (conditional) ─────────────────────────────────
    has_1d_vol = any(m.get("volume_1d") for m in markets)

    if has_1d_vol:
        vol_1d_sorted = sorted(
            [m for m in markets if m.get("volume_1d") and m["volume_1d"] > 0],
            key=lambda m: m["volume_1d"], reverse=True
        )[:15]
        vol_1d_headers = ["#", "Market", "YES", "NO", "Spread", "1D Vol", "Total", "1D Chg"]
        vol_1d_widths = [35, 420, 70, 70, 70, 90, 90, 80]

        vol_1d_rows = []
        for i, m in enumerate(vol_1d_sorted, 1):
            chg_1d = m["one_day_chg"]
            chg_1d_color = "green" if chg_1d > 0 else "red" if chg_1d < 0 else "dim"
            yes_color = "green" if m["yes"] >= 0.7 else "yellow" if m["yes"] >= 0.4 else "text"
            spread = m["spread"]
            if spread is not None:
                spread_color = "green" if spread <= 0.01 else "yellow" if spread <= 0.03 else "red"
                spread_str = f"{spread*100:.1f}%"
            else:
                spread_color = "dim"
                spread_str = "-"
            vol_1d_rows.append([
                (str(i), "dim"),
                (m["title"], "text"),
                (fmt_pct(m["yes"]), yes_color),
                (fmt_pct(m["no"]), "text"),
                (spread_str, spread_color),
                (fmt_vol(m["volume_1d"]), "yellow"),
                (fmt_vol(m["volume"]), "yellow"),
                (fmt_chg_plain(chg_1d), chg_1d_color),
            ])

        if vol_1d_rows:
            path = _render_single_table(
                banner, "TOP MARKETS BY 1D VOLUME",
                vol_1d_headers, vol_1d_rows, vol_1d_widths,
                timestamp, f"{output_prefix}_vol_1d.jpg",
            )
            if path:
                saved.append(path)

    return saved


# ─── Main ─────────────────────────────────────────────────────────────────────

async def run_screener(
    tag_slug: Optional[str] = None,
    refresh: bool = False,
    interval: int = 60,
    min_vol: float = 0,
    save_img: bool = False,
    exclude_tags: Optional[List[str]] = None,
) -> None:
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=connector) as session:
        while True:
            if not save_img:
                console.clear()

            raw_markets = await fetch_markets(session, tag_slug=tag_slug)
            markets = [m for m in (parse_market(r) for r in raw_markets) if m is not None]

            # Apply tag exclusion filter
            excluded_count = 0
            if exclude_tags:
                pre_count = len(markets)
                markets = [
                    m for m in markets
                    if not any(t in exclude_tags for t in m["tags"])
                ]
                excluded_count = pre_count - len(markets)
                if excluded_count > 0:
                    console.print(
                        f"[dim]Excluded {excluded_count} markets matching tags: "
                        f"{', '.join(exclude_tags)}[/dim]"
                    )

            if not markets:
                console.print("[red]No markets found.[/red]")
                if not refresh:
                    return
                await asyncio.sleep(interval)
                continue

            # Apply volume filter
            if min_vol > 0:
                filtered = [m for m in markets if m["volume"] >= min_vol]
            else:
                filtered = markets

            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

            # Image export mode
            if save_img:
                tag_part = f"_{tag_slug}" if tag_slug else ""
                prefix = f"screener{tag_part}"
                paths = export_to_image(
                    filtered, tag_slug, timestamp,
                    output_prefix=prefix,
                )
                if paths:
                    for p in paths:
                        console.print(f"[bold green]Saved → {p}[/bold green]")
                    console.print(f"[dim]{len(filtered)} markets, {len(paths)} images, {timestamp}[/dim]")
                else:
                    console.print("[red]No images generated (no data for any table).[/red]")
                return

            # Terminal output
            show_summary(filtered, tag_slug, timestamp,
                         excluded_count=excluded_count, exclude_tags=exclude_tags)
            console.print()

            # Price Movers
            show_top_movers(filtered, count=15)
            console.print()
            show_top_movers_7d(filtered, count=15)
            console.print()

            # Volume
            show_top_volume(filtered, count=15)
            console.print()
            show_top_1d_volume(filtered, count=15)
            console.print()

            vol_note = f" (>={fmt_vol(min_vol)} volume)" if min_vol > 0 else ""
            tag_note = f" [{tag_slug}]" if tag_slug else ""
            console.print(
                f"[dim]Showing {len(filtered)}{vol_note} out of {len(markets)} "
                f"total{tag_note} markets[/dim]"
            )

            if tag_slug:
                console.print(
                    f"[dim]Tip: run without a tag to see all markets, "
                    f"or try: python screener.py --tags[/dim]"
                )
            console.print(
                f"[dim]Tip: use --img to export as PNG image[/dim]"
            )

            if not refresh:
                return

            console.print(f"\n[dim]Auto-refreshing in {interval}s... Press Ctrl+C to stop.[/dim]")
            await asyncio.sleep(interval)


def main():
    args = sys.argv[1:]

    # --tags: list available tags and exit
    if "--tags" in args:
        show_tags()
        return

    # Parse flags
    refresh = "--refresh" in args or "-r" in args
    save_img = "--img" in args
    debug_api = "--debug-api" in args
    interval = 60
    min_vol = 0.0
    tag_slug = None
    exclude_tags = None

    i = 0
    positional = []
    while i < len(args):
        if args[i] in ("--interval", "-i") and i + 1 < len(args):
            interval = int(args[i + 1])
            i += 2
        elif args[i] in ("--min-vol",) and i + 1 < len(args):
            min_vol = float(args[i + 1])
            i += 2
        elif args[i] in ("--exclude-tags",) and i + 1 < len(args):
            exclude_tags = [t.strip() for t in args[i + 1].split(",") if t.strip()]
            i += 2
        elif args[i] in ("--refresh", "-r", "--img", "--debug-api"):
            i += 1
        else:
            positional.append(args[i])
            i += 1

    # First positional arg is the tag slug
    if positional:
        tag_slug = positional[0]

    # --debug-api: dump raw API response and exit
    if debug_api:
        asyncio.run(debug_dump_api(tag_slug))
        return

    # CLI --exclude-tags overrides env; if neither, use config default
    if exclude_tags is None:
        exclude_tags = config.EXCLUDE_TAGS

    try:
        asyncio.run(run_screener(
            tag_slug=tag_slug,
            refresh=refresh,
            interval=interval,
            min_vol=min_vol,
            save_img=save_img,
            exclude_tags=exclude_tags,
        ))
    except KeyboardInterrupt:
        console.print("\n[dim]Goodbye![/dim]")


if __name__ == "__main__":
    main()
