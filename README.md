# Polymarket & Kalshi Geopolitical Market Monitor

A real-time monitoring system for prediction markets on **Polymarket** and **Kalshi**. Includes a live screener (`screener.py`) for browsing markets and a background monitor (`main.py`) that alerts on probability spikes, volume surges, new markets, and large trades — with optional Telegram notifications.

---

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt
# Additional: pip install Pillow certifi

# Copy and edit your environment config
cp .env.example .env   # see "Environment Variables" below

# Run the screener
python screener.py                    # all active markets
python screener.py geopolitics        # filter by tag
python screener.py --img              # export as PNG

# Run the real-time monitor
python main.py                        # monitor geopolitical markets
python main.py ukraine-conflict       # also track a specific event for large trades
```

---

## How to Transfer to Another Computer

To run this bot on a new computer, follow these steps:

1.  **Transfer the folder** or **Clone from GitHub**:
    ```bash
    git clone https://github.com/ZhouYeMen/polymarket-Kalshi-bot
    ```
2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Restore/Create your .env file**:
    - If you *transferred* the folder, make sure the hidden `.env` file came with it.
    - If you *cloned* from GitHub, copy the example: `cp .env.example .env` and fill in your Token and IDs.
4.  **Run the bot**:
    ```bash
    python3 telegram_bot.py
    ```

---

## Project Structure

```
polymarket/
├── screener.py                  # Interactive market screener (CLI + PNG export)
├── main.py                      # Real-time monitoring loop
├── config.py                    # All configuration / environment variables
├── requirements.txt
├── clients/
│   ├── polymarket_client.py     # Polymarket Gamma & CLOB API client
│   └── kalshi_client.py         # Kalshi REST API client
├── models/
│   └── market_event.py          # Unified MarketEvent data model
├── alerts/
│   ├── notifier.py              # Alert dispatcher (console + Telegram)
│   └── telegram_sender.py       # Telegram Bot API sender
├── analysis/
│   ├── filters.py               # Geopolitical keyword filtering
│   └── spike_detection.py       # Z-score / rolling stats spike detection
└── utils/
    ├── normalization.py         # Price, volume, datetime normalization
    ├── rate_limiter.py          # Token-bucket rate limiter + exponential backoff
    └── persistence.py           # JSON file state persistence
```

---

## Scripts

### `screener.py` — Market Screener

Browse all active Polymarket markets or filter by tag. Outputs 4 tables (15 entries each):

**Price Movers:** Top Movers 24H, Top Movers 7D
**Volume:** Top Markets by 7D Volume, Top Markets by 1D Volume (if available)

#### CLI Usage

```
python screener.py [TAG] [OPTIONS]
```

| Argument / Flag | Description | Default |
|---|---|---|
| `TAG` (positional) | Polymarket tag slug to filter by (e.g. `geopolitics`, `crypto`, `nba`) | All markets |
| `--tags` | List all popular tags grouped by category, then exit | — |
| `--img` | Export tables as a PNG image instead of terminal output | Off |
| `--refresh`, `-r` | Auto-refresh the terminal view on a loop | Off |
| `--interval N`, `-i N` | Refresh interval in seconds (requires `--refresh`) | `60` |
| `--min-vol N` | Minimum total volume (USD) to include a market | `0` |
| `--exclude-tags TAGS` | Comma-separated tag slugs to exclude (e.g. `crypto-prices,sports-nba`). Overrides `EXCLUDE_TAGS` env var | `""` (none) |
| `--debug-api` | Dump raw API response for 5 events to `debug_api_response.json` and exit | Off |

#### Examples

```bash
python screener.py                          # All active markets
python screener.py geopolitics              # Geopolitics tag only
python screener.py --tags                   # List available tags
python screener.py geopolitics --img        # Export as screener_geopolitics.png
python screener.py --refresh --interval 30  # Auto-refresh every 30s
python screener.py --min-vol 500000         # Only markets with >$500K volume
python screener.py --exclude-tags crypto-prices,sports-nba  # Hide crypto and sports
python screener.py --debug-api              # Dump raw API JSON for field inspection
```

#### Key Functions

| Function | Parameters | Description |
|---|---|---|
| `fetch_markets(session, tag_slug=None)` | `session`: aiohttp session, `tag_slug`: optional tag filter | Fetches all active markets from Polymarket Gamma API. Filters out closed, resolved, and expired markets. |
| `parse_market(m)` | `m`: raw API market dict | Parses raw API data into a clean dict with `title`, `yes`, `no`, `spread`, `volume`, `volume_1w`, `one_day_chg`, etc. |
| `show_summary(markets, tag_slug, timestamp, target=None, excluded_count=0, exclude_tags=None)` | `markets`: list of parsed dicts, `tag_slug`: current filter, `timestamp`: display time, `target`: optional Console, `excluded_count`: int, `exclude_tags`: optional list | Renders a summary panel with market count, total volume, 7D volume, avg spread, top mover, highest 7D volume, >$1M 7D vol count, and excluded tag stats. |
| `show_top_volume(markets, count=15, target=None)` | `markets`: list of parsed dicts, `count`: number of rows, `target`: optional Console | Displays markets sorted by 7-day volume. Columns: #, Market, YES, Sprd, 7D Vol, Total, 1D Chg. |
| `show_top_movers(markets, count=15, target=None)` | `markets`: list of parsed dicts, `count`: number of rows, `target`: optional Console | Displays markets sorted by absolute 1D price change. Filters: change > 0.1%, YES between 2%-98%, volume >= $500K. Columns: #, Market, YES, 1D Chg, Volume, Dir. |
| `show_top_movers_7d(markets, count=15, target=None)` | `markets`: list of parsed dicts, `count`: number of rows, `target`: optional Console | Displays markets sorted by absolute 7D price change. Same filters as `show_top_movers` but using weekly change. |
| `show_top_1d_volume(markets, count=15, target=None)` | `markets`: list of parsed dicts, `count`: number of rows, `target`: optional Console | Top markets by 24-hour volume. Skips entirely if 1D volume data is unavailable from the API. |
| `debug_dump_api(tag_slug=None)` | `tag_slug`: optional tag filter | Fetches 5 events from Gamma API and dumps raw JSON to `debug_api_response.json`. Used via `--debug-api` flag. |
| `show_tags()` | (none) | Prints available popular tags grouped by category. |
| `export_to_image(markets, tag_slug, timestamp, output_path="screener.png")` | `markets`: list of parsed dicts, `tag_slug`: current filter, `timestamp`: display time, `output_path`: file name | Renders all 4 tables as a styled PNG image with text wrapping. Returns path to saved file. |
| `run_screener(tag_slug=None, refresh=False, interval=60, min_vol=0, save_img=False, exclude_tags=None)` | All optional — see table above. `exclude_tags`: list of tag slugs to exclude | Main async entry point. Fetches, parses, filters, and displays markets. |

#### Formatting Helpers

| Function | Parameters | Description |
|---|---|---|
| `fmt_pct(val)` | `val`: float 0.0-1.0 | Returns percentage string, e.g. `"45.2%"` |
| `fmt_chg(val)` | `val`: float 0.0-1.0 | Returns Rich `Text` with color: green for positive, red for negative |
| `fmt_chg_plain(val)` | `val`: float 0.0-1.0 | Returns plain string `"+3.2%"` or `"-1.5%"` (no Rich styling) |
| `fmt_vol(val)` | `val`: float USD | Returns formatted volume: `"$1.2M"`, `"$450.0K"`, `"$800"` |
| `fmt_spread(val)` | `val`: float 0.0-1.0 | Returns Rich `Text` colored green/yellow/red by spread tightness |
| `truncate(text, max_len=48)` | `text`: string, `max_len`: int | Truncates with ellipsis if needed |

---

### `main.py` — Real-Time Monitor

Continuously polls Polymarket and Kalshi for geopolitical markets. Alerts on probability changes, volume surges, new markets, and large trades.

#### CLI Usage

```
python main.py [EVENT_SLUG]
```

| Argument | Description | Default |
|---|---|---|
| `EVENT_SLUG` (positional) | Polymarket event slug to track for large trades | `TRACK_EVENT_SLUG` env var |

#### `MarketMonitor` Class

| Method | Parameters | Description |
|---|---|---|
| `initialize()` | (none) | Sets up aiohttp session, API clients, loads persisted state, verifies Telegram bot. |
| `process_market_update(market)` | `market`: `MarketEvent` | Processes a single market update. Detects probability changes above threshold. Tracks YES/NO direction. |
| `track_specific_event(event_slug, min_trade_usd=5000.0)` | `event_slug`: string, `min_trade_usd`: float | Starts tracking a Polymarket event for large trades. |
| `check_tracked_events_trades()` | (none) | Checks all tracked events for new large trades above the configured threshold. |
| `poll_tracked_events_trades()` | (none) | Loop that checks for large trades every 30 seconds. |
| `poll_polymarket()` | (none) | Loop that polls Polymarket geopolitical markets at `POLYMARKET_POLL_INTERVAL`. |
| `poll_kalshi()` | (none) | Loop that polls Kalshi Politics/World markets at `KALSHI_POLL_INTERVAL`. |
| `cleanup_known_trade_ids()` | (none) | Removes trade IDs older than `DATA_RETENTION_HOURS`. Returns count removed. |
| `periodic_state_save()` | (none) | Saves state to disk every 5 minutes. |
| `connect_websockets()` | (none) | Attempts WebSocket connection to Polymarket (falls back to polling). |
| `run(track_event_slug=None)` | `track_event_slug`: optional string | Main entry point. Starts all polling loops and waits. |
| `shutdown()` | (none) | Cancels tasks, saves state, closes connections, prints summary. |

---

## API Clients

### `clients/polymarket_client.py` — `PolymarketClient`

| Method | Parameters | Description |
|---|---|---|
| `__init__(session)` | `session`: aiohttp.ClientSession | Initialize with shared session. |
| `fetch_tags()` | (none) | Fetch available tags from the Gamma API. Returns list of tag dicts. |
| `find_geopolitics_tag_id()` | (none) | Find the tag ID for "geopolitics". Returns string or None. |
| `fetch_events(tag_slug=None, limit=100, offset=0, closed=False)` | `tag_slug`: filter tag, `limit`: page size, `offset`: pagination, `closed`: include closed | Fetch events from Gamma API. Returns list of event dicts. |
| `fetch_markets(limit=100, offset=0, closed=False, tag_slug=None)` | Same as above | Fetch events and parse nested markets into `MarketEvent` objects. |
| `fetch_all_active_markets(geopolitics_only=True)` | `geopolitics_only`: bool | Fetch all active markets with pagination. If `True`, filters by `tag_slug=geopolitics`. |
| `fetch_event_by_slug(slug)` | `slug`: event slug string | Fetch a single event by its slug. Returns event dict or None. |
| `fetch_trades_for_event(event_id, limit=1000, offset=0)` | `event_id`: string, `limit`: int, `offset`: int | Fetch trades for an event from the Data API. |
| `fetch_large_trades(event_id, min_usd=5000.0, limit=1000)` | `event_id`: string, `min_usd`: minimum USD value, `limit`: max trades | Fetch trades above a minimum USD value. Sorted by value descending. |
| `fetch_market_prices(market_id)` | `market_id`: string | Fetch current prices from the CLOB API. Returns price dict or None. |
| `connect_websocket(callback)` | `callback`: async function | Attempt WebSocket connection (placeholder, returns False). |
| `close()` | (none) | Close client connections and cancel WebSocket tasks. |

### `clients/kalshi_client.py` — `KalshiClient`

| Method | Parameters | Description |
|---|---|---|
| `__init__(session)` | `session`: aiohttp.ClientSession | Initialize with shared session. Uses `KALSHI_API_KEY`/`KALSHI_API_SECRET` if set. |
| `fetch_events(limit=100, cursor=None, status="open", with_nested_markets=True)` | `limit`: page size, `cursor`: pagination cursor, `status`: event status, `with_nested_markets`: bool | Fetch events from Kalshi API. Returns `(events_list, next_cursor)`. |
| `fetch_all_active_markets(geopolitics_only=True)` | `geopolitics_only`: bool | Fetch all active markets. If `True`, filters to Politics/World categories only. |
| `close()` | (none) | Close client connections. |

---

## Models

### `models/market_event.py` — `MarketEvent`

Unified dataclass for markets from any platform.

| Field | Type | Description |
|---|---|---|
| `source` | `str` | `"polymarket"` or `"kalshi"` |
| `market_id` | `str` | Unique identifier (slug, ticker, etc.) |
| `title` | `str` | Market title / question |
| `description` | `Optional[str]` | Market description |
| `tags` | `List[str]` | Keywords, categories |
| `status` | `str` | `"open"` or `"closed"` |
| `probability` | `float` | Normalized 0.0-1.0 |
| `volume` | `Optional[float]` | Total volume in USD |
| `liquidity` | `Optional[float]` | Market liquidity |
| `created_time` | `Optional[datetime]` | When market was created |
| `close_time` | `Optional[datetime]` | When market closes |
| `last_updated` | `datetime` | Last update timestamp |
| `url` | `str` | Deep link to market page |
| `yes_bid` | `Optional[float]` | Best bid price (from API `bestBid`) |
| `no_bid` | `Optional[float]` | NO bid price |
| `yes_ask` | `Optional[float]` | Best ask price (from API `bestAsk`) |
| `no_ask` | `Optional[float]` | NO ask price |

| Method | Returns | Description |
|---|---|---|
| `get_probability()` | `float` | Clamped probability 0.0-1.0 |
| `is_active()` | `bool` | True if status is open/active/trading |
| `get_spread()` | `Optional[float]` | Bid-ask spread (`yes_ask - yes_bid`), or `None` if orderbook data unavailable |
| `get_unique_id()` | `str` | `"{source}:{market_id}"` |

---

## Alerts

### `alerts/notifier.py` — `AlertNotifier`

Dispatches alerts to both the Rich console and Telegram.

| Method | Parameters | Description |
|---|---|---|
| `notify_spike(spike_data)` | `spike_data`: dict with `market`, `change_percentage`, `current_probability`, `previous_probability`, `direction`, `direction_prob` | Alert on probability spike. Shows YES/NO direction. |
| `notify_volume_surge(surge_data)` | `surge_data`: dict with `market`, `current_volume`, `average_volume`, `multiplier` | Alert on volume surge. |
| `notify_new_market(market)` | `market`: `MarketEvent` | Alert on new market creation. |
| `notify_large_trade(trade, event_title, event_url)` | `trade`: trade dict, `event_title`: string, `event_url`: string | Alert on large trade detected. |
| `notify_status(message, style="blue")` | `message`: string, `style`: Rich style | Status message. Only sent to Telegram if `TELEGRAM_SEND_STATUS=true`. |
| `print_summary_table(markets)` | `markets`: list of `MarketEvent` | Print a summary table of monitored markets (up to 20). |
| `get_alert_count()` | (none) | Returns total number of alerts generated. |
| `close()` | (none) | Close Telegram session. |

### `alerts/telegram_sender.py` — `TelegramSender`

| Method | Parameters | Description |
|---|---|---|
| `__init__(bot_token, chat_id, rate_limit=1.0)` | `bot_token`: string, `chat_id`: string, `rate_limit`: msgs/sec | Initialize. `enabled` is True only if both token and chat_id are set. |
| `verify()` | (none) | Verify bot token via `getMe`. Returns True if valid. |
| `send_message(text, parse_mode="HTML")` | `text`: message body, `parse_mode`: `"HTML"`, `"MarkdownV2"`, or `""` | Send a message. Auto-truncates to 4096 chars. Handles 429 rate limits. |
| `format_spike_alert(spike_data)` | `spike_data`: dict | Format probability spike as HTML string. |
| `format_volume_surge_alert(surge_data)` | `surge_data`: dict | Format volume surge as HTML string. |
| `format_new_market_alert(market)` | `market`: `MarketEvent` | Format new market as HTML string. |
| `format_large_trade_alert(trade, event_title, event_url)` | `trade`: dict, `event_title`: string, `event_url`: string | Format large trade as HTML string. |
| `close()` | (none) | Close the aiohttp session. |

---

## Analysis

### `analysis/filters.py`

| Function | Parameters | Description |
|---|---|---|
| `is_geopolitical(market, keywords=None)` | `market`: `MarketEvent`, `keywords`: optional list of strings | Check if market matches geopolitical keywords in title, description, or tags. Defaults to `config.GEOPOLITICAL_KEYWORDS`. |
| `filter_new_markets(current_markets, known_market_ids)` | `current_markets`: list of `MarketEvent`, `known_market_ids`: set of strings | Return markets not already in the known set. Mutates `known_market_ids` in place. |
| `filter_active_markets(markets)` | `markets`: list of `MarketEvent` | Return only open/active markets. |
| `filter_geopolitical_markets(markets, keywords=None)` | `markets`: list of `MarketEvent`, `keywords`: optional list | Return only markets matching geopolitical criteria. |

### `analysis/spike_detection.py` — `SpikeDetector`

| Method | Parameters | Description |
|---|---|---|
| `__init__(z_threshold=None, spike_window_minutes=None, spike_percentage=None, volume_surge_multiplier=None, retention_hours=None)` | All optional, default from config | Initialize detector with thresholds. |
| `update(market)` | `market`: `MarketEvent` | Add a market data point to the rolling history DataFrame. |
| `detect_spikes(market)` | `market`: `MarketEvent` | Detect probability spike via Z-score or percentage change. Returns spike dict or None. |
| `detect_volume_surge(market)` | `market`: `MarketEvent` | Detect volume surge (current vs 1-hour average). Returns surge dict or None. |
| `detect_anomalies(market)` | `market`: `MarketEvent` | Run all anomaly detectors. Returns list of anomaly dicts. |

---

## Utilities

### `utils/normalization.py`

| Function | Parameters | Description |
|---|---|---|
| `normalize_probability(price, source)` | `price`: float, `source`: `"polymarket"` or `"kalshi"` | Convert to 0.0-1.0. Polymarket prices are already 0-1; Kalshi prices are 0-100 cents. |
| `normalize_volume(volume, source)` | `volume`: any, `source`: string | Standardize volume to USD. Returns float or None. |
| `extract_tags(data, source)` | `data`: API response dict, `source`: string | Extract tags/categories from raw API data. Returns deduplicated lowercase list. |
| `parse_datetime(dt_str, source)` | `dt_str`: string or None, `source`: string | Parse datetime string. Handles `Z` suffix, timezone offsets, Python 3.9 compat. |
| `build_market_url(market_id, source)` | `market_id`: string, `source`: string | Build deep link URL. Polymarket: `/market/{id}`, Kalshi: `/markets/{id}`. |

### `utils/rate_limiter.py`

| Class | Constructor Parameters | Description |
|---|---|---|
| `TokenBucketRateLimiter(rate, capacity=None)` | `rate`: requests/sec, `capacity`: burst capacity (default `rate * 2`) | Token bucket rate limiter. Methods: `acquire(tokens=1.0)`, `wait(tokens=1.0)`. |
| `ExponentialBackoff(initial_delay=1.0, max_delay=60.0, multiplier=2.0, max_retries=5)` | All optional | Exponential backoff for retries. Method: `retry(func, *args, **kwargs)`. |
| `RateLimitedSession(rate_limiter)` | `rate_limiter`: `TokenBucketRateLimiter` | Wraps aiohttp session. Methods: `get(session, *args, **kwargs)`, `post(session, *args, **kwargs)` — return `RetryableRequest` async context managers. |

### `utils/persistence.py` — `StatePersistence`

| Method | Parameters | Description |
|---|---|---|
| `__init__(state_file="")` | `state_file`: path string, empty = `~/.polymarket_monitor/state.json` | Initialize persistence. Creates directory if needed. |
| `load_sets()` | (none) | Load state from JSON file. Returns `(known_market_ids: Set[str], known_trade_ids: Dict[str, datetime])`. Backward-compatible with old list format. |
| `save(known_market_ids, known_trade_ids)` | `known_market_ids`: set, `known_trade_ids`: dict | Atomic save (write to `.tmp`, then `os.replace`). |

---

## Environment Variables

All configuration is in `config.py` and can be overridden via a `.env` file or environment variables.

| Variable | Default | Description |
|---|---|---|
| **API Endpoints** | | |
| `POLYMARKET_GAMMA_BASE` | `https://gamma-api.polymarket.com` | Polymarket Gamma API base URL |
| `POLYMARKET_CLOB_BASE` | `https://clob.polymarket.com` | Polymarket CLOB API base URL |
| `KALSHI_BASE` | `https://api.elections.kalshi.com/trade-api/v2` | Kalshi REST API base URL |
| `KALSHI_WS_BASE` | `wss://api.elections.kalshi.com/trade-api/ws/v2` | Kalshi WebSocket base URL |
| **Monitoring** | | |
| `PROBABILITY_CHANGE_THRESHOLD` | `1.0` | Alert when probability changes by this many percentage points (e.g. 1.0 = alert on 50% -> 51%) |
| `POLYMARKET_POLL_INTERVAL` | `60` | Seconds between Polymarket polls |
| `KALSHI_POLL_INTERVAL` | `60` | Seconds between Kalshi polls |
| `POLYMARKET_RATE_LIMIT` | `10` | Max Polymarket API requests per second |
| `KALSHI_RATE_LIMIT` | `5` | Max Kalshi API requests per second |
| `MIN_VOLUME` | `250000.0` | Minimum market volume (USD) to include in monitoring |
| `MAX_SPREAD` | `0.0` | Max bid-ask spread to include (0 = disabled, e.g. `0.05` = 5 cents) |
| `EXCLUDE_TAGS` | `""` | Comma-separated tag slugs to exclude from screener results (e.g. `crypto-prices,sports-nba`) |
| `DATA_RETENTION_HOURS` | `24` | Hours of historical data to retain |
| **Platform Toggles** | | |
| `ENABLE_POLYMARKET` | `true` | Enable Polymarket polling in `main.py` |
| `ENABLE_KALSHI` | `false` | Enable Kalshi polling in `main.py` |
| **Event Tracking** | | |
| `TRACK_EVENT_SLUG` | `""` | Polymarket event slug to track for large trades |
| `MIN_TRADE_USD` | `1000.0` | Minimum trade size (USD) to alert on |
| **Persistence** | | |
| `STATE_FILE` | `""` | Path to state file (empty = `~/.polymarket_monitor/state.json`) |
| **Telegram** | | |
| `TELEGRAM_BOT_TOKEN` | `""` | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | `""` | Target Telegram chat/channel ID |
| `TELEGRAM_MESSAGE_THREAD_ID` | `""` | Topic/thread ID (0 or empty = General) |
| `TELEGRAM_SCHEDULE_HOUR` | `12` | Hour to send daily screener (0-23 local time) |
| `TELEGRAM_ALLOWED_CHATS` | `""` | Comma-separated list of authorized chat/user IDs |
| `TELEGRAM_RATE_LIMIT` | `1.0` | Max Telegram messages per second |
| `TELEGRAM_SEND_STATUS` | `false` | Send status messages to Telegram (not just alerts) |
| **Kalshi Auth** | | |
| `KALSHI_API_KEY` | `""` | Kalshi API key (optional) |
| `KALSHI_API_SECRET` | `""` | Kalshi API secret (optional) |

### Example `.env`

```env
# Telegram notifications
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=-1001234567890

# Monitor settings
PROBABILITY_CHANGE_THRESHOLD=2.0
MIN_VOLUME=500000
MAX_SPREAD=0.05
POLYMARKET_POLL_INTERVAL=30

# Platform toggles
ENABLE_POLYMARKET=true
ENABLE_KALSHI=false

# Track a specific event for large trades
TRACK_EVENT_SLUG=ukraine-conflict
MIN_TRADE_USD=5000
```

A full template with all variables is available in `.env.example`. Copy it and uncomment the values you want to override:

```bash
cp .env.example .env
```

---

## Dependencies

```
aiohttp>=3.8
websockets>=10.0
pandas>=1.5
rich>=13.0
python-dotenv>=0.21
numpy>=1.24
certifi
Pillow          # for --img PNG export in screener.py
```

Install all:
```bash
pip install -r requirements.txt
pip install Pillow certifi
```
