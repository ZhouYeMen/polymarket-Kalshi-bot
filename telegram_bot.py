"""Polymarket Screener Telegram Bot.

Usage:
    python telegram_bot.py            # Run bot with daily schedule at configured hour
    python telegram_bot.py --test     # Run bot + send screener ~2 min after startup
"""
import asyncio
import ssl
import os
import sys
import json
import logging
from datetime import datetime, time, timedelta
from typing import List, Optional, Set
from functools import wraps

import aiohttp
import certifi

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from screener import (
    fetch_markets,
    parse_market,
    export_to_image,
    POPULAR_TAGS,
)

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("telegram_bot")

# ─── Chat Persistence ────────────────────────────────────────────────────────

CHATS_FILE = os.path.join(
    os.path.expanduser("~/.polymarket_monitor"),
    "telegram_chats.json",
)


def load_chat_ids() -> dict:
    """Load registered chat IDs from JSON file."""
    if not os.path.exists(CHATS_FILE):
        return {}
    try:
        with open(CHATS_FILE, "r") as f:
            data = json.load(f)
        return data.get("chats", {})
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("Failed to load chats file: %s", e)
        return {}


def save_chat_ids(chats: dict) -> None:
    """Save registered chat IDs to JSON file (atomic write)."""
    os.makedirs(os.path.dirname(CHATS_FILE), exist_ok=True)
    data = {"chats": chats, "last_saved": datetime.now().isoformat()}
    tmp = CHATS_FILE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, CHATS_FILE)
    except IOError as e:
        logger.error("Failed to save chats file: %s", e)


def get_all_chat_ids() -> Set[str]:
    """Return union of persisted chat IDs and TELEGRAM_CHAT_ID from .env."""
    chats = set(load_chat_ids().keys())
    if config.TELEGRAM_CHAT_ID:
        chats.add(str(config.TELEGRAM_CHAT_ID))
    return chats


# ─── Screener Image Generation ───────────────────────────────────────────────

async def generate_screener_images(tag_slug: Optional[str] = None) -> List[str]:
    """Fetch markets, parse, filter, and render to JPG images.

    Reuses fetch_markets(), parse_market(), and export_to_image() from screener.py.

    Returns:
        List of file paths to generated JPG images.
    """
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    async with aiohttp.ClientSession(connector=connector) as session:
        raw_markets = await fetch_markets(session, tag_slug=tag_slug)
        markets = [m for m in (parse_market(r) for r in raw_markets) if m is not None]

        # Apply tag exclusion filter (same as screener.py run_screener)
        if config.EXCLUDE_TAGS:
            markets = [
                m for m in markets
                if not any(t in config.EXCLUDE_TAGS for t in m["tags"])
            ]

        # Apply volume filter
        min_vol = config.MIN_VOLUME
        if min_vol > 0:
            markets = [m for m in markets if m["volume"] >= min_vol]

        if not markets:
            logger.warning("No markets found for tag=%s", tag_slug)
            return []

        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        tag_part = f"_{tag_slug}" if tag_slug else ""
        prefix = f"screener{tag_part}"

        paths = export_to_image(markets, tag_slug, timestamp, output_prefix=prefix)
        return paths


# ─── Send Images to All Chats ────────────────────────────────────────────────

async def send_screener_to_all(bot, tag_slug: Optional[str] = None) -> None:
    """Generate screener images and send to all registered chats."""
    chat_ids = get_all_chat_ids()
    if not chat_ids:
        logger.warning("No chat IDs registered. Send /start to the bot first.")
        return

    thread_id = config.TELEGRAM_MESSAGE_THREAD_ID
    logger.info("Generating screener images (tag=%s)...", tag_slug or "all")

    try:
        paths = await generate_screener_images(tag_slug=tag_slug)
    except Exception as e:
        logger.error("Failed to generate screener images: %s", e)
        for chat_id in chat_ids:
            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text=f"Failed to generate screener: {e}",
                    message_thread_id=thread_id,
                )
            except Exception:
                pass
        return

    if not paths:
        for chat_id in chat_ids:
            try:
                await bot.send_message(
                    chat_id=int(chat_id),
                    text="No screener data available at this time.",
                    message_thread_id=thread_id,
                )
            except Exception:
                pass
        return

    label = tag_slug.upper() if tag_slug else "ALL MARKETS"
    caption = (
        f"Polymarket Screener — {label}\n"
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )

    for chat_id in chat_ids:
        for i, path in enumerate(paths):
            try:
                with open(path, "rb") as photo_file:
                    await bot.send_photo(
                        chat_id=int(chat_id),
                        photo=photo_file,
                        caption=caption if i == 0 else None,
                        message_thread_id=thread_id,
                    )
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.error("Failed to send photo to chat %s: %s", chat_id, e)

    # Cleanup JPG files
    for path in paths:
        try:
            os.remove(path)
            logger.debug("Cleaned up %s", path)
        except OSError:
            pass

    logger.info("Screener sent to %d chat(s), %d images", len(chat_ids), len(paths))


# ─── Access Control ──────────────────────────────────────────────────────────

def authorized_only(func):
    """Decorator to restrict access to authorized chats."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat_id = str(update.effective_chat.id)
        allowed = config.TELEGRAM_ALLOWED_CHATS
        if allowed and chat_id not in allowed:
            logger.warning("Unauthorized access attempt from chat %s", chat_id)
            # Silently ignore or send a message
            # await update.message.reply_text("Unauthorized access.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


# ─── Command Handlers ────────────────────────────────────────────────────────

@authorized_only
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — Register this chat and show help."""
    chat_id = str(update.effective_chat.id)
    username = (
        update.effective_user.username
        or update.effective_user.first_name
        or "unknown"
    )

    # Persist chat ID
    chats = load_chat_ids()
    is_new = chat_id not in chats
    chats[chat_id] = {
        "registered_at": datetime.now().isoformat(),
        "username": username,
    }
    save_chat_ids(chats)

    if is_new:
        logger.info("New chat registered: %s (user: %s)", chat_id, username)

    help_text = (
        "Polymarket Screener Bot\n"
        "=======================\n\n"
        f"Your Chat ID: {chat_id}\n\n"
        "Commands:\n"
        "/start              — Register and show this help\n"
        "/tags               — List available market categories\n"
        "/screener           — Send screener for all markets\n"
        "/screener <tag>  — Send screener for a specific tag\n\n"
        f"Daily screener runs at {config.TELEGRAM_SCHEDULE_HOUR}:00 local time."
    )

    await update.message.reply_text(help_text)


@authorized_only
async def cmd_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tags — List available tag categories."""
    lines = ["Available Tags\n"]
    for category, tags in POPULAR_TAGS.items():
        tag_list = ", ".join(tags)
        lines.append(f"{category}:\n  {tag_list}\n")
    lines.append("Usage: /screener <tag>")
    lines.append("Example: /screener geopolitics")

    await update.message.reply_text("\n".join(lines))


@authorized_only
async def cmd_screener(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/screener [tag] — Generate and send screener images."""
    tag_slug = None
    if context.args:
        tag_slug = context.args[0].lower().strip()
        all_tags = [t for tags in POPULAR_TAGS.values() for t in tags]
        if tag_slug not in all_tags:
            await update.message.reply_text(
                f"Note: '{tag_slug}' is not in the popular tags list, "
                f"but will try it anyway.\nUse /tags to see known tags."
            )

    label = f" for [{tag_slug}]" if tag_slug else ""
    await update.message.reply_text(
        f"Generating screener{label}... This takes 10-30 seconds."
    )

    try:
        paths = await generate_screener_images(tag_slug=tag_slug)
    except Exception as e:
        await update.message.reply_text(f"Error generating screener: {e}")
        return

    if not paths:
        await update.message.reply_text("No market data available for this filter.")
        return

    label = tag_slug.upper() if tag_slug else "ALL MARKETS"
    caption = (
        f"Polymarket Screener — {label}\n"
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    )

    for i, path in enumerate(paths):
        try:
            with open(path, "rb") as photo_file:
                await update.message.reply_photo(
                    photo=photo_file,
                    caption=caption if i == 0 else None,
                )
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.error("Failed to send photo: %s", e)
            await update.message.reply_text(f"Failed to send image: {e}")

    # Cleanup
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


@authorized_only
async def handle_mention_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle messages like '@BotName /command' in groups."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    bot_user = await context.bot.get_me()
    mention = f"@{bot_user.username}"

    if text.startswith(mention):
        # Remove mention and strip whitespace
        cmd_part = text[len(mention):].strip()
        if cmd_part.startswith("/"):
            # Split command and args
            parts = cmd_part.split()
            cmd = parts[0][1:].lower()  # Strip leading '/'
            args = parts[1:]

            # Update context.args for the actual handlers
            context.args = args

            # Route to existing handlers
            if cmd == "start":
                await cmd_start(update, context)
            elif cmd == "tags":
                await cmd_tags(update, context)
            elif cmd in ("screener", "screen"):
                await cmd_screener(update, context)

# ─── Scheduled Jobs ──────────────────────────────────────────────────────────

async def scheduled_screener(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: daily screener send to all registered chats."""
    logger.info("Running scheduled screener...")
    await send_screener_to_all(context.bot, tag_slug=None)


async def test_screener(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: one-shot test send ~2 min after startup."""
    logger.info("Running test screener send...")
    await send_screener_to_all(context.bot, tag_slug=None)


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main() -> None:
    """Start the Telegram bot."""
    token = config.TELEGRAM_BOT_TOKEN
    if not token:
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)

    test_mode = "--test" in sys.argv

    # Build the Application
    application = Application.builder().token(token).build()

    # Register command handlers
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("tags", cmd_tags))
    application.add_handler(CommandHandler("screener", cmd_screener))

    # Support mentions like "@BotName /start" (common user error in groups)
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_mention_command))

    # Schedule daily screener
    job_queue = application.job_queue
    schedule_hour = config.TELEGRAM_SCHEDULE_HOUR
    target_time = time(hour=schedule_hour, minute=0, second=0)

    job_queue.run_daily(
        scheduled_screener,
        time=target_time,
        name="daily_screener",
    )
    logger.info("Scheduled daily screener at %02d:00 local time", schedule_hour)

    # Test mode: schedule a one-shot send ~2 minutes from now
    if test_mode:
        delay_seconds = 10
        job_queue.run_once(
            test_screener,
            when=delay_seconds,
            name="test_screener",
        )
        logger.info(
            "TEST MODE: Screener will send in %d seconds (at %s)",
            delay_seconds,
            (datetime.now() + timedelta(seconds=delay_seconds)).strftime("%H:%M:%S"),
        )

    # Start polling for commands
    logger.info("Bot starting... Send /start to register your chat.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
