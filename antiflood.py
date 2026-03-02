"""
antiflood.py — Antiflood system: consecutive & timed flood detection + actions.
"""

import logging
import re
import time
from collections import defaultdict
from datetime import timedelta

from telegram import ChatPermissions, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from admin import admin_only, get_chat_lang, is_admin
from strings import t

logger = logging.getLogger(__name__)

# ─── Per-chat antiflood settings ─────────────────────────────────────────────
# {chat_id: {limit, action, action_dur, timed_count, timed_seconds, clear}}
_flood_settings: dict[int, dict] = {}

# ─── Per-chat per-user message tracking ──────────────────────────────────────
# Consecutive: {chat_id: {user_id: count}}
_consecutive: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
# Last user who sent a message: {chat_id: user_id}
_last_user: dict[int, int] = {}
# Timed: {chat_id: {user_id: [timestamp, ...]}}
_timed: dict[int, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))


def _get_settings(chat_id: int) -> dict:
    """Return or initialise flood settings for a chat."""
    if chat_id not in _flood_settings:
        _flood_settings[chat_id] = {
            "limit": 0,          # 0 = disabled
            "action": "mute",    # ban/mute/kick/tban/tmute
            "action_dur": 0,     # duration in seconds (for tban/tmute)
            "timed_count": 0,    # 0 = disabled
            "timed_seconds": 0,
            "clear": False,
        }
    return _flood_settings[chat_id]


# ─── Duration parsing ────────────────────────────────────────────────────────

_DUR_RE = re.compile(r"^(\d+)([smhd])$", re.IGNORECASE)
_DUR_MULTIPLIERS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(text: str) -> int | None:
    """Parse a duration string like '30s', '5m', '1h', '3d' into seconds."""
    m = _DUR_RE.match(text.strip())
    if not m:
        return None
    return int(m.group(1)) * _DUR_MULTIPLIERS[m.group(2).lower()]


def format_duration(seconds: int) -> str:
    """Format seconds into a human-readable string."""
    if seconds >= 86400:
        return f"{seconds // 86400}d"
    if seconds >= 3600:
        return f"{seconds // 3600}h"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


# ─── Flood action execution ─────────────────────────────────────────────────

async def _execute_action(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    user_name: str,
    settings: dict,
    lang: str,
) -> None:
    """Take the configured action against a flooding user."""
    chat_id = update.effective_chat.id
    action = settings["action"]
    dur = settings.get("action_dur", 0)

    try:
        if action == "ban":
            await context.bot.ban_chat_member(chat_id, user_id)
            await update.effective_message.reply_text(
                t(lang, "flood_action_ban", user=user_name), parse_mode="Markdown"
            )

        elif action == "mute":
            await context.bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await update.effective_message.reply_text(
                t(lang, "flood_action_mute", user=user_name), parse_mode="Markdown"
            )

        elif action == "kick":
            await context.bot.ban_chat_member(chat_id, user_id)
            await context.bot.unban_chat_member(chat_id, user_id)
            await update.effective_message.reply_text(
                t(lang, "flood_action_kick", user=user_name), parse_mode="Markdown"
            )

        elif action == "tban":
            until = timedelta(seconds=dur) if dur > 0 else timedelta(minutes=5)
            await context.bot.ban_chat_member(
                chat_id, user_id,
                until_date=until,
            )
            await update.effective_message.reply_text(
                t(lang, "flood_action_tban", user=user_name, dur=format_duration(dur or 300)),
                parse_mode="Markdown",
            )

        elif action == "tmute":
            until = timedelta(seconds=dur) if dur > 0 else timedelta(minutes=5)
            await context.bot.restrict_chat_member(
                chat_id, user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            await update.effective_message.reply_text(
                t(lang, "flood_action_tmute", user=user_name, dur=format_duration(dur or 300)),
                parse_mode="Markdown",
            )

    except (BadRequest, Forbidden) as exc:
        await update.effective_message.reply_text(
            t(lang, "flood_action_fail", user=user_name, err=str(exc)),
            parse_mode="Markdown",
        )


# ─── Message tracker (called for every group message) ───────────────────────

async def check_flood(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Track messages and trigger antiflood if thresholds are exceeded."""
    if not update.effective_message or not update.effective_user:
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return

    user = update.effective_user
    settings = _get_settings(chat.id)

    # Skip if antiflood is fully disabled
    if settings["limit"] <= 0 and settings["timed_count"] <= 0:
        return

    # Skip admins — they shouldn't be flood-restricted
    if await is_admin(chat.id, user.id, context.bot):
        return

    lang = get_chat_lang(chat.id)
    triggered = False

    # ── Consecutive flood check ──────────────────────────────────────────
    if settings["limit"] > 0:
        if _last_user.get(chat.id) == user.id:
            _consecutive[chat.id][user.id] += 1
        else:
            _consecutive[chat.id][user.id] = 1
            _last_user[chat.id] = user.id

        if _consecutive[chat.id][user.id] >= settings["limit"]:
            triggered = True
            _consecutive[chat.id][user.id] = 0

    # ── Timed flood check ────────────────────────────────────────────────
    if settings["timed_count"] > 0 and settings["timed_seconds"] > 0:
        now = time.time()
        window = settings["timed_seconds"]
        _timed[chat.id][user.id].append(now)
        # Prune old timestamps
        _timed[chat.id][user.id] = [
            ts for ts in _timed[chat.id][user.id] if now - ts <= window
        ]
        if len(_timed[chat.id][user.id]) >= settings["timed_count"]:
            triggered = True
            _timed[chat.id][user.id] = []

    # ── Execute action if triggered ──────────────────────────────────────
    if triggered:
        logger.info(
            "Antiflood triggered for user %s (%s) in chat %s",
            user.id, user.full_name, chat.id,
        )

        # Delete flood messages if enabled
        if settings.get("clear", False):
            try:
                await update.effective_message.delete()
            except (BadRequest, Forbidden):
                pass

        await _execute_action(
            update, context, user.id, user.full_name, settings, lang
        )


# ─── Admin command handlers ─────────────────────────────────────────────────

@admin_only
async def flood_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/flood — show current antiflood settings."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if settings["limit"] <= 0 and settings["timed_count"] <= 0:
        await update.message.reply_text(
            t(lang, "flood_status_off"), parse_mode="Markdown"
        )
        return

    text = ""
    if settings["limit"] > 0:
        text = t(
            lang, "flood_status_on",
            limit=settings["limit"],
            action=settings["action"],
            clear="ON" if settings["clear"] else "OFF",
        )
    else:
        text = t(lang, "flood_status_off")

    if settings["timed_count"] > 0:
        text += t(
            lang, "flood_status_timed",
            count=settings["timed_count"],
            duration=settings["timed_seconds"],
        )

    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def setflood_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setflood <number/off/no> — set consecutive flood limit."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "setflood_usage"))
        return

    val = context.args[0].lower()
    if val in ("0", "off", "no"):
        settings["limit"] = 0
        await update.message.reply_text(
            t(lang, "setflood_off"), parse_mode="Markdown"
        )
        return

    try:
        n = int(val)
        if n <= 0:
            raise ValueError
        settings["limit"] = n
        await update.message.reply_text(
            t(lang, "setflood_set", n=n), parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text(t(lang, "setflood_invalid"))


@admin_only
async def setfloodtimer_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setfloodtimer <count> <duration> — set timed flood detection."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "setfloodtimer_usage"))
        return

    if context.args[0].lower() in ("off", "no"):
        settings["timed_count"] = 0
        settings["timed_seconds"] = 0
        await update.message.reply_text(
            t(lang, "setfloodtimer_off"), parse_mode="Markdown"
        )
        return

    if len(context.args) < 2:
        await update.message.reply_text(t(lang, "setfloodtimer_usage"))
        return

    try:
        count = int(context.args[0])
        if count <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(lang, "setfloodtimer_usage"))
        return

    dur = parse_duration(context.args[1])
    if dur is None or dur <= 0:
        await update.message.reply_text(t(lang, "setfloodtimer_usage"))
        return

    settings["timed_count"] = count
    settings["timed_seconds"] = dur
    await update.message.reply_text(
        t(lang, "setfloodtimer_set", count=count, dur=format_duration(dur)),
        parse_mode="Markdown",
    )


@admin_only
async def floodmode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/floodmode <action> — set the action to take on flooding users."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "floodmode_usage"))
        return

    action = context.args[0].lower()
    valid = ("ban", "mute", "kick", "tban", "tmute")

    if action not in valid:
        await update.message.reply_text(t(lang, "floodmode_invalid"))
        return

    settings["action"] = action

    # For tban/tmute, parse optional duration argument
    if action in ("tban", "tmute") and len(context.args) >= 2:
        dur = parse_duration(context.args[1])
        if dur and dur > 0:
            settings["action_dur"] = dur

    display = action
    if action in ("tban", "tmute") and settings.get("action_dur", 0) > 0:
        display = f"{action} ({format_duration(settings['action_dur'])})"

    await update.message.reply_text(
        t(lang, "floodmode_set", mode=display), parse_mode="Markdown"
    )


@admin_only
async def clearflood_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/clearflood <yes/no/on/off> — whether to delete flood messages."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    settings = _get_settings(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "clearflood_usage"))
        return

    val = context.args[0].lower()
    if val in ("yes", "on"):
        settings["clear"] = True
        await update.message.reply_text(
            t(lang, "clearflood_set", val="ON"), parse_mode="Markdown"
        )
    elif val in ("no", "off"):
        settings["clear"] = False
        await update.message.reply_text(
            t(lang, "clearflood_set", val="OFF"), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(t(lang, "clearflood_usage"))
