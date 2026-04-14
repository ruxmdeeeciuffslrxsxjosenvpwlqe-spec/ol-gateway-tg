"""
Gateway TG Bot
──────────────
Entry point — registers all handlers and starts polling.
Full feature set: math captcha gateway, admin, antiflood, antiraid,
approvals, bans, blocklists, CAPTCHA verification, federations,
welcome messages, user tracking, inactivity kicker, service cleanup.
"""

import logging
import os
import random
import re
import time
from html import escape
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Conflict, Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    ChatMemberHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
except ImportError:
    TelegramClient = None
    StringSession = None

# ── Module imports ───────────────────────────────────────────────────────────
from admin import (
    admin_only,
    admincache_command,
    adminerror_command,
    adminlist_command,
    anonadmin_command,
    demote_command,
    get_chat_lang,
    is_admin,
    promote_command,
)
from antiflood import (
    check_flood,
    clearflood_command,
    flood_command,
    floodmode_command,
    setflood_command,
    setfloodtimer_command,
)
from antiraid import (
    antiraid_command,
    autoantiraid_command,
    check_raid,
    raidactiontime_command,
    raidtime_command,
)
from approval import (
    approval_command,
    approve_command,
    approved_command,
    unapprove_command,
    unapproveall_command,
)
from bans import (
    ban_command,
    dban_command,
    dkick_command,
    dmute_command,
    kick_command,
    kickme_command,
    mute_command,
    sban_command,
    skick_command,
    smute_command,
    tban_command,
    tmute_command,
    unban_callback,
    unban_command,
    unmute_command,
)
from blocklists import (
    addblocklist_command,
    blocklist_command,
    blocklistdelete_command,
    blocklistmode_command,
    check_blocklist,
    resetblocklistreason_command,
    rmblocklist_command,
    setblocklistreason_command,
    unblocklistall_command,
)
from captcha import captcha_callback, on_new_member, restrict_and_welcome
from cleanup import delete_service_message
from federation import (
    check_fedban_on_join,
    fedadmins_command,
    fedban_command,
    fedchats_command,
    feddemote_command,
    fedinfo_command,
    fedpromote_command,
    is_fedbanned,
    joinfed_command,
    leavefed_command,
    newfed_command,
    unfedban_command,
)
from inactivity import CHECK_INTERVAL_SECONDS, kick_inactive_job
from strings import t
from welcome import (
    info_action_callback,
    info_command,
    staff_command,
    track_message,
)

# ─── Configuration ──────────────────────────────────────────────────────────

load_dotenv()

BOT_TOKEN: str = os.environ["BOT_TOKEN"]
TELEGRAM_API_ID: str = os.environ.get("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH: str = os.environ.get("TELEGRAM_API_HASH", "")

def _parse_csv_env(key: str) -> list[str]:
    raw = os.environ.get(key, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


GROUP_IDS: list[int] = [int(gid) for gid in _parse_csv_env("GROUP_IDS")]

_group_names = _parse_csv_env("GROUP_NAMES")
GROUP_NAMES: list[str] = _group_names if _group_names else [str(gid) for gid in GROUP_IDS]

if len(GROUP_NAMES) < len(GROUP_IDS):
    GROUP_NAMES.extend(str(gid) for gid in GROUP_IDS[len(GROUP_NAMES):])

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── State ───────────────────────────────────────────────────────────────────
pending: dict[int, dict] = {}

STORE_COUNTRIES: dict[str, str] = {
    "US": "🇺🇸",
    "CA": "🇨🇦",
    "UK": "🇬🇧",
    "EU": "🇪🇺",
    "AUS": "🇦🇺",
    "MX": "🇲🇽",
}

STORE_TIMEFRAMES: dict[str, str] = {
    "TF_INSTANT": "Instant",
    "TF_1_5_DAYS": "1-5 Days",
    "TF_7_DAYS": "7 Days",
    "TF_1_2_WEEKS": "1-2 Weeks",
    "TF_2_3_WEEKS": "2-3 Weeks",
    "TF_3_4_WEEKS": "3-4 Weeks",
    "TF_4_WEEKS": "4 Weeks",
}

STORE_METHODS: dict[str, str] = {
    "M_FTID_V3": "FTIDv3",
    "M_WEIGHTED_FTID": "Weighted FTID",
    "M_LIT": "LIT",
    "M_DNA": "DNA",
    "M_EB": "EB",
    "M_FTID_ROS": "FTID ROS",
    "M_FTID_ROD": "FTID ROD",
    "M_FTIDNA": "FTIDNA",
    "M_DMG_RTS": "DMG RTS",
    "M_RTS": "RTS",
    "M_UTD": "UTD",
    "M_PTDNA": "PTDNA",
    "M_PEB": "PEB",
}

STORE_WATERMARK = "𝐎𝐋𝐈𝐌𝐏𝐎 Watermarked."

# Track users who completed the math captcha: {user_id: timestamp}
verified_users: dict[int, float] = {}

# Track bot messages in private chats for cleanup: {user_id: [message_ids]}
_dm_messages: dict[int, list[int]] = {}

# Pending join requests: {(chat_id, user_id): timestamp}
_pending_requests: dict[tuple[int, int], float] = {}
PENDING_APPROVAL_TIMEOUT = 36 * 3600  # 36 hours in seconds
_mtproto_client = None


# ─── Utilities ───────────────────────────────────────────────────────────────

def _is_manual_approval_chat(chat_id: int) -> bool:
    """True when this chat should always require manual admin approval."""
    for gid, gname in zip(GROUP_IDS, GROUP_NAMES):
        if gid == chat_id:
            return gname.strip().lower() == "main"
    return False

def generate_math_problem() -> tuple[str, int]:
    a = random.randint(1, 50)
    b = random.randint(1, 50)
    if random.choice(["+", "-"]) == "+":
        return f"{a} + {b}", a + b
    a, b = max(a, b), min(a, b)
    return f"{a} - {b}", a - b


def _store_country_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("USA", callback_data="store_country_US"),
            InlineKeyboardButton("CA", callback_data="store_country_CA"),
            InlineKeyboardButton("UK", callback_data="store_country_UK"),
        ],
        [
            InlineKeyboardButton("EU", callback_data="store_country_EU"),
            InlineKeyboardButton("AUS", callback_data="store_country_AUS"),
            InlineKeyboardButton("MX", callback_data="store_country_MX"),
        ],
    ])


def _store_timeframe_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Instant", callback_data="store_timeframe_TF_INSTANT")],
        [InlineKeyboardButton("1-5 Days", callback_data="store_timeframe_TF_1_5_DAYS")],
        [InlineKeyboardButton("7 Days", callback_data="store_timeframe_TF_7_DAYS")],
        [InlineKeyboardButton("1-2 Weeks", callback_data="store_timeframe_TF_1_2_WEEKS")],
        [InlineKeyboardButton("2-3 Weeks", callback_data="store_timeframe_TF_2_3_WEEKS")],
        [InlineKeyboardButton("3-4 Weeks", callback_data="store_timeframe_TF_3_4_WEEKS")],
        [InlineKeyboardButton("4 Weeks", callback_data="store_timeframe_TF_4_WEEKS")],
    ])


def _store_method_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("FTIDv3", callback_data="store_method_M_FTID_V3")],
        [InlineKeyboardButton("Weighted FTID", callback_data="store_method_M_WEIGHTED_FTID")],
        [InlineKeyboardButton("LIT", callback_data="store_method_M_LIT")],
        [InlineKeyboardButton("DNA", callback_data="store_method_M_DNA")],
        [InlineKeyboardButton("EB", callback_data="store_method_M_EB")],
        [InlineKeyboardButton("FTID ROS", callback_data="store_method_M_FTID_ROS")],
        [InlineKeyboardButton("FTID ROD", callback_data="store_method_M_FTID_ROD")],
        [InlineKeyboardButton("FTIDNA", callback_data="store_method_M_FTIDNA")],
        [InlineKeyboardButton("DMG RTS", callback_data="store_method_M_DMG_RTS")],
        [InlineKeyboardButton("RTS", callback_data="store_method_M_RTS")],
        [InlineKeyboardButton("UTD", callback_data="store_method_M_UTD")],
        [InlineKeyboardButton("PTDNA", callback_data="store_method_M_PTDNA")],
        [InlineKeyboardButton("PEB", callback_data="store_method_M_PEB")],
    ])


def _store_notes_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("N/A", callback_data="store_notes_na")],
    ])


def _store_preview_keyboard(store_url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Visit Store", url=store_url)],
        [
            InlineKeyboardButton("✅ Confirm", callback_data="store_preview_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="store_preview_cancel"),
        ],
    ])


def _build_store_caption(data: dict) -> str:
    country_code = data.get("country", "US")
    country_flag = STORE_COUNTRIES.get(country_code, "🇺🇸")

    store_name = escape(data.get("store_name", "N/A"))
    limit_text = escape(data.get("limit", "N/A"))
    method_text = escape(data.get("method", "N/A"))
    notes_text = escape(data.get("notes", "N/A"))
    timeframe_text = escape(data.get("timeframe", "N/A"))

    return (
        f"{country_flag} {store_name} {country_flag}\n"
        f"<code>{STORE_WATERMARK}</code>\n\n"
        f"<b>Limit:</b> {limit_text}\n"
        f"<b>Timeframe:</b> {timeframe_text}\n"
        f"<b>Method:</b> {method_text}\n"
        f"<b>Notes:</b> {notes_text}\n\n"
        f"<code>{STORE_WATERMARK}</code>"
    )


def _normalize_store_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    return f"https://{url}"


def _is_add_store_flow(user_id: int) -> bool:
    return (
        user_id in pending
        and pending[user_id].get("mode") == "add_store"
    )


def _is_custom_message_flow(user_id: int) -> bool:
    return (
        user_id in pending
        and pending[user_id].get("mode") == "custom_message"
    )


def _is_addstore_trigger_text(text: str) -> bool:
    import re

    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    for ch in ("<", ">", "[", "]", "(", ")", "{", "}", "`", '"', "'"):
        normalized = normalized.replace(ch, "")
    for dash in ("–", "—", "‑", "−", "_"):
        normalized = normalized.replace(dash, "-")

    normalized = re.sub(r"\s+", "", normalized)
    if normalized == "admin-addstore" or normalized == "adminaddstore":
        return True

    return "admin" in normalized and "addstore" in normalized


def _is_copymessages_trigger_text(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    for ch in ("<", ">", "[", "]", "(", ")", "{", "}", "`", '"', "'"):
        normalized = normalized.replace(ch, "")
    for dash in ("–", "—", "‑", "−", "_"):
        normalized = normalized.replace(dash, "-")

    normalized = re.sub(r"\s+", "", normalized)
    if normalized in {"admin-copymessages", "admincopymessages"}:
        return True

    return "admin" in normalized and "copymessages" in normalized


def _is_custommessage_trigger_text(text: str) -> bool:
    normalized = (text or "").strip().lower()
    if not normalized:
        return False

    for ch in ("<", ">", "[", "]", "(", ")", "{", "}", "`", '"', "'"):
        normalized = normalized.replace(ch, "")
    for dash in ("–", "—", "‑", "−", "_"):
        normalized = normalized.replace(dash, "-")

    normalized = re.sub(r"\s+", "", normalized)
    if normalized in {"admin-custommessage", "admincustommessage"}:
        return True

    return "admin" in normalized and "custommessage" in normalized


def _custom_keyboard_from_specs(button_specs: list[list[dict[str, str]]]) -> InlineKeyboardMarkup | None:
    if not button_specs:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row]
        for row in button_specs
    ])


def _custom_preview_keyboard(button_specs: list[list[dict[str, str]]]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if button_specs:
        rows.extend([
            [InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row]
            for row in button_specs
        ])
    rows.append([
        InlineKeyboardButton("✅ Confirm", callback_data="custom_preview_confirm"),
        InlineKeyboardButton("❌ Cancel", callback_data="custom_preview_cancel"),
    ])
    return InlineKeyboardMarkup(rows)


def _dynamic_bar(value: int, total: int, width: int = 12) -> str:
    total = max(1, total)
    value = max(0, min(value, total))
    filled = int((value / total) * width)
    return "[" + ("█" * filled) + ("░" * (width - filled)) + "]"


def _parse_custom_button_specs(raw_text: str) -> tuple[str, list[list[dict[str, str]]]]:
    button_specs: list[list[dict[str, str]]] = []

    def _repl(match: re.Match) -> str:
        body = (match.group(1) or "").strip()
        parsed = re.match(r"^(.+?)\((https?://[^)\s]+)\)$", body, flags=re.IGNORECASE)
        if not parsed:
            return ""
        label = parsed.group(1).strip()
        url = parsed.group(2).strip()
        if not label:
            return ""
        button_specs.append([{"text": label, "url": url}])
        return ""

    cleaned_text = re.sub(r"<button>(.*?)<button>", _repl, raw_text, flags=re.IGNORECASE | re.DOTALL)
    return cleaned_text, button_specs


def _parse_custom_dynamic_spec(raw_text: str) -> tuple[str, dict | None]:
    dynamic: dict | None = None

    def _repl_countdown(match: re.Match) -> str:
        nonlocal dynamic
        seconds = int(match.group(1))
        if dynamic is None:
            dynamic = {"type": "countdown", "total": max(1, seconds)}
        return ""

    text = re.sub(r"<countdown(\d+)>", _repl_countdown, raw_text, flags=re.IGNORECASE)

    if re.search(r"<progressbar>", text, flags=re.IGNORECASE):
        text = re.sub(r"<progressbar>", "", text, flags=re.IGNORECASE)
        if dynamic is None:
            dynamic = {"type": "progress_up", "total": 100}

    if re.search(r"<progressbardown>", text, flags=re.IGNORECASE):
        text = re.sub(r"<progressbardown>", "", text, flags=re.IGNORECASE)
        if dynamic is None:
            dynamic = {"type": "progress_down", "total": 100}

    return text, dynamic


def _render_custom_dynamic_line(dynamic: dict, elapsed_seconds: int) -> tuple[str, bool]:
    dynamic_type = dynamic.get("type")
    total = int(dynamic.get("total", 0))

    if dynamic_type == "countdown":
        seconds_left = max(0, total - elapsed_seconds)
        line = f"⏳ {seconds_left}s {_dynamic_bar(seconds_left, total)}"
        return line, seconds_left <= 0

    if dynamic_type == "progress_up":
        progress = min(total, elapsed_seconds)
        line = f"📈 Progress: {_dynamic_bar(progress, total)} {progress}%"
        return line, progress >= total

    if dynamic_type == "progress_down":
        left = max(0, total - elapsed_seconds)
        line = f"📉 Progress: {_dynamic_bar(left, total)} {left}%"
        return line, left <= 0

    return "", False


def _parse_custom_message_template(raw_text: str) -> tuple[str, list[list[dict[str, str]]], dict | None]:
    text_no_buttons, button_specs = _parse_custom_button_specs(raw_text)
    text_no_dynamic, dynamic = _parse_custom_dynamic_spec(text_no_buttons)

    placeholders: dict[str, str] = {}
    placeholder_index = 0

    def _hold(html_text: str) -> str:
        nonlocal placeholder_index
        token = f"__CMSG_PLACEHOLDER_{placeholder_index}__"
        placeholder_index += 1
        placeholders[token] = html_text
        return token

    def _sub_style(text_value: str, marker: str, html_tag: str) -> str:
        pattern = re.compile(rf"<{marker}>(.*?)<{marker}>", flags=re.IGNORECASE | re.DOTALL)
        return pattern.sub(lambda m: _hold(f"<{html_tag}>{escape((m.group(1) or '').strip())}</{html_tag}>"), text_value)

    parsed_text = text_no_dynamic

    parsed_text = re.sub(
        r"<url>(.+?)\((https?://[^)\s]+)\)",
        lambda m: _hold(f"<a href=\"{escape(m.group(2).strip())}\">{escape(m.group(1).strip())}</a>"),
        parsed_text,
        flags=re.IGNORECASE,
    )

    parsed_text = _sub_style(parsed_text, "bold", "b")
    parsed_text = _sub_style(parsed_text, "italic", "i")
    parsed_text = _sub_style(parsed_text, "underlined", "u")
    parsed_text = _sub_style(parsed_text, "spoiler", "tg-spoiler")
    parsed_text = _sub_style(parsed_text, "strike", "s")
    parsed_text = _sub_style(parsed_text, "monospace", "code")

    parsed_text = escape(parsed_text)
    for key, value in placeholders.items():
        parsed_text = parsed_text.replace(key, value)

    parsed_text = parsed_text.strip()
    return parsed_text, button_specs, dynamic


def _build_custom_rendered_text(base_text: str, dynamic: dict | None, elapsed_seconds: int = 0) -> tuple[str, bool]:
    body = (base_text or "").strip()
    should_delete = False

    if dynamic:
        dynamic_line, should_delete = _render_custom_dynamic_line(dynamic, elapsed_seconds)
        if dynamic_line:
            body = f"{body}\n\n{dynamic_line}" if body else dynamic_line

    if not body:
        body = "<i>Empty message</i>"

    return body, should_delete


async def _custom_dynamic_message_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    chat_id = data.get("chat_id")
    message_id = data.get("message_id")
    base_text = data.get("base_text", "")
    dynamic = data.get("dynamic")
    button_specs = data.get("button_specs", [])
    started_at = int(data.get("started_at", time.time()))

    if not chat_id or not message_id or not dynamic:
        context.job.schedule_removal()
        return

    elapsed_seconds = max(0, int(time.time()) - started_at)
    rendered_text, should_delete = _build_custom_rendered_text(base_text, dynamic, elapsed_seconds)

    try:
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=rendered_text,
            parse_mode="HTML",
            reply_markup=_custom_keyboard_from_specs(button_specs),
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            context.job.schedule_removal()
            return
    except Forbidden:
        context.job.schedule_removal()
        return

    if should_delete:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
        except (BadRequest, Forbidden):
            pass
        context.job.schedule_removal()


async def _start_custom_message_flow(update: Update) -> None:
    user_id = update.effective_user.id
    _dm_messages[user_id] = []
    _track_dm_message(user_id, update.message.message_id)
    pending[user_id] = {
        "mode": "custom_message",
        "step": "compose",
        "data": {},
    }
    await _reply_text_tracked(update.message, user_id, "👋 Sure! what message would you like me to send?")


def _track_dm_message(user_id: int, message_id: int) -> None:
    _dm_messages.setdefault(user_id, []).append(message_id)


async def _reply_text_tracked(message, user_id: int, text: str, **kwargs):
    sent = await message.reply_text(text, **kwargs)
    _track_dm_message(user_id, sent.message_id)
    return sent


async def _clear_tracked_dm_messages(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    message_ids = list(dict.fromkeys(_dm_messages.get(user_id, [])))
    for msg_id in message_ids:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
        except (BadRequest, Forbidden):
            pass
    _dm_messages.pop(user_id, None)


async def _start_add_store_flow(update: Update) -> None:
    user_id = update.effective_user.id
    _dm_messages[user_id] = []
    _track_dm_message(user_id, update.message.message_id)
    pending[user_id] = {
        "mode": "add_store",
        "step": "store_name",
        "data": {},
    }
    await _reply_text_tracked(update.message, user_id, "👋 To get started, please enter the <b>Store Name:</b>", parse_mode="HTML")


async def _start_copy_messages_flow(update: Update) -> None:
    user_id = update.effective_user.id
    _dm_messages[user_id] = []
    _track_dm_message(user_id, update.message.message_id)
    pending[user_id] = {
        "mode": "copy_messages",
        "step": "source_section",
        "data": {},
    }
    await _reply_text_tracked(
        update.message,
        user_id,
        "Sure, which messages would you like me to scrape?",
    )


def _parse_target_link(link: str) -> tuple[int | str, int | None, int | None] | None:
    raw = (link or "").strip()

    # Private supergroup/channel links: https://t.me/c/<internal_chat_id>/<message_id>
    # Topic links: https://t.me/c/<internal_chat_id>/<topic_id>/<message_id>
    m_private = re.match(
        r"^https?://t\.me/c/(\d+)/(\d+)(?:/(\d+))?/?$",
        raw,
        flags=re.IGNORECASE,
    )
    if m_private:
        internal_chat = int(m_private.group(1))
        second = int(m_private.group(2))
        third = m_private.group(3)
        chat_id = int(f"-100{internal_chat}")
        if third:
            topic_id = second
            message_id = int(third)
            return chat_id, message_id, topic_id
        return chat_id, second, None

    # Public links: https://t.me/<username>/<message_id>
    m_public = re.match(
        r"^https?://t\.me/([A-Za-z0-9_]{5,})/(\d+)/?$",
        raw,
        flags=re.IGNORECASE,
    )
    if m_public:
        username = m_public.group(1)
        message_id = int(m_public.group(2))
        return f"@{username}", message_id, None

    return None


def _parse_section_link(link: str) -> tuple[int, int, int] | None:
    raw = (link or "").strip()

    # Section/topic links:
    # - https://t.me/c/<internal_chat_id>/<topic_id>
    # - https://t.me/c/<internal_chat_id>/<topic_id>/<message_id>
    m = re.match(
        r"^https?://t\.me/c/(\d+)/(\d+)(?:/(\d+))?/?$",
        raw,
        flags=re.IGNORECASE,
    )
    if not m:
        return None

    internal_chat = int(m.group(1))
    topic_id = int(m.group(2))
    anchor_message_id = int(m.group(3)) if m.group(3) else topic_id
    chat_id = int(f"-100{internal_chat}")
    return chat_id, topic_id, anchor_message_id


def _is_copy_messages_flow(user_id: int) -> bool:
    return (
        user_id in pending
        and pending[user_id].get("mode") == "copy_messages"
    )


async def _is_user_admin_in_chat(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    user_id: int,
) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id, user_id)
    except (BadRequest, Forbidden):
        return False

    return member.status in {"administrator", "creator"}


async def _get_mtproto_client():
    global _mtproto_client

    if _mtproto_client is not None and _mtproto_client.is_connected():
        return _mtproto_client

    if TelegramClient is None or StringSession is None:
        logger.error("Telethon is not installed; copy-messages feature is unavailable")
        return None

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        logger.error("TELEGRAM_API_ID / TELEGRAM_API_HASH are missing")
        return None

    try:
        api_id = int(TELEGRAM_API_ID)
    except ValueError:
        logger.error("Invalid TELEGRAM_API_ID: must be an integer")
        return None

    client = TelegramClient(StringSession(), api_id, TELEGRAM_API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    _mtproto_client = client
    return _mtproto_client


def _mtproto_ready() -> bool:
    if TelegramClient is None or StringSession is None:
        return False
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return False
    try:
        int(TELEGRAM_API_ID)
    except ValueError:
        return False
    return True


def _progress_bar(done: int, total: int, width: int = 12) -> str:
    total = max(1, total)
    done = max(0, min(done, total))
    filled = int((done / total) * width)
    bar = "█" * filled + "░" * (width - filled)
    percent = int((done / total) * 100)
    return f"[{bar}] {percent}% ({done}/{total})"


def _countdown_bar(seconds_left: int, total_seconds: int = 60, width: int = 12) -> str:
    total_seconds = max(1, total_seconds)
    seconds_left = max(0, min(seconds_left, total_seconds))
    filled = int((seconds_left / total_seconds) * width)
    bar = "█" * filled + "░" * (width - filled)
    percent = int((seconds_left / total_seconds) * 100)
    return f"[{bar}] {percent}%"


def _gateway_links_text(seconds_left: int) -> str:
    return (
        f"🔗 Here are your invite links (valid for the next {seconds_left} seconds):\n"
        f"{_countdown_bar(seconds_left)}\n\n"
        "Tap the buttons below to join the rooms. 👇\n"
        "If they expire, no worries! Just type /start again to get new buttons. ⏰"
    )


def _math_answer_options(answer: int) -> list[int]:
    options = {answer}
    while len(options) < 4:
        delta = random.randint(1, 10)
        candidate = answer + random.choice((-delta, delta))
        if candidate < 0:
            candidate = answer + delta
        options.add(candidate)

    values = list(options)
    random.shuffle(values)
    return values


def _math_answer_keyboard(options: list[int]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for idx in range(0, len(options), 2):
        row_values = options[idx: idx + 2]
        rows.append([
            InlineKeyboardButton(str(value), callback_data=f"math_answer_{value}")
            for value in row_values
        ])
    return InlineKeyboardMarkup(rows)


def _links_keyboard_from_specs(button_specs: list[list[dict[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn["text"], url=btn["url"]) for btn in row]
        for row in button_specs
    ])


async def _start_math_challenge(message, user_id: int, lang: str, edit: bool = False):
    question, answer = generate_math_problem()
    options = _math_answer_options(answer)
    pending[user_id] = {
        "lang": lang,
        "question": question,
        "answer": answer,
        "options": options,
    }

    text = t(lang, "math_prompt", q=question)
    keyboard = _math_answer_keyboard(options)

    if edit:
        sent = await message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        sent = await message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    return sent


async def _links_countdown_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data or {}
    user_id = data.get("user_id")
    message_id = data.get("message_id")
    total_seconds = int(data.get("total_seconds", 60))
    started_at = float(data.get("started_at", time.time()))
    button_specs = data.get("button_specs", [])

    if not user_id or not message_id:
        context.job.schedule_removal()
        return

    elapsed = int(time.time() - started_at)
    seconds_left = max(0, total_seconds - elapsed)

    try:
        await context.bot.edit_message_text(
            chat_id=user_id,
            message_id=message_id,
            text=_gateway_links_text(seconds_left),
            reply_markup=_links_keyboard_from_specs(button_specs),
        )
    except BadRequest as exc:
        if "message is not modified" not in str(exc).lower():
            context.job.schedule_removal()
    except Forbidden:
        context.job.schedule_removal()

    if seconds_left <= 0:
        context.job.schedule_removal()


async def _complete_gateway_success(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int, lang: str) -> None:
    verified_users[user_id] = time.time()
    source_message = update.effective_message
    if not source_message:
        return

    invite_entries: list[dict] = []
    buttons: list[list[InlineKeyboardButton]] = []
    button_specs: list[list[dict[str, str]]] = []

    for gid, gname in zip(GROUP_IDS, GROUP_NAMES):
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=gid,
                expire_date=datetime.now(timezone.utc) + timedelta(seconds=60),
                creates_join_request=True,
                name=f"Gateway – {user_id}",
            )
            invite_entries.append({"chat_id": gid, "invite_link": invite})
            label = f"🔗 {gname}"
            buttons.append([InlineKeyboardButton(label, url=invite.invite_link)])
            button_specs.append([{"text": label, "url": invite.invite_link}])
            logger.info("Link created → %s (%s) | %s", gid, gname, invite.invite_link)
        except (Forbidden, BadRequest) as exc:
            logger.warning("Error creating link in %s (%s): %s", gid, gname, exc)

    if not buttons:
        msg = await source_message.reply_text(t(lang, "no_links"))
        _dm_messages.setdefault(user_id, []).append(msg.message_id)
        return

    links_msg = await source_message.reply_text(
        _gateway_links_text(60),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    _dm_messages.setdefault(user_id, []).append(links_msg.message_id)

    countdown_job_name = f"links_countdown_{user_id}_{int(time.time())}"
    context.application.job_queue.run_repeating(
        callback=_links_countdown_job,
        interval=1,
        first=1,
        data={
            "user_id": user_id,
            "message_id": links_msg.message_id,
            "total_seconds": 60,
            "started_at": time.time(),
            "button_specs": button_specs,
        },
        name=countdown_job_name,
    )

    context.application.job_queue.run_once(
        callback=revoke_links_job,
        when=60,
        data={
            "invite_entries": invite_entries,
            "user_id": user_id,
            "countdown_job_name": countdown_job_name,
        },
        name=f"revoke_{user_id}_{datetime.now(timezone.utc).timestamp():.0f}",
    )


async def _try_edit_status_message(status_message, text: str) -> bool:
    if not status_message:
        return False

    try:
        await status_message.edit_text(text)
        return True
    except BadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return True
    except Forbidden:
        pass

    return False


def _extract_topic_message_ids(messages, topic_id: int) -> list[int]:
    ids: list[int] = []
    for msg in messages:
        if not msg:
            continue

        msg_id = getattr(msg, "id", None)
        if not msg_id:
            continue

        if msg_id == topic_id:
            ids.append(msg_id)
            continue

        reply_to = getattr(msg, "reply_to", None)
        top_id = getattr(reply_to, "reply_to_top_id", None) if reply_to else None
        if top_id == topic_id:
            ids.append(msg_id)

    return sorted(set(ids))


async def _collect_topic_message_ids(chat_id: int, topic_id: int) -> list[int]:
    client = await _get_mtproto_client()
    if client is None:
        return []

    try:
        entity = await client.get_entity(chat_id)
    except Exception as exc:
        logger.warning("Could not resolve source chat %s: %s", chat_id, exc)
        return []

    collected = []
    try:
        root_msg = await client.get_messages(entity, ids=topic_id)
        if root_msg:
            collected.append(root_msg)

        async for msg in client.iter_messages(entity, reverse=True, reply_to=topic_id):
            collected.append(msg)
    except Exception as exc:
        logger.warning("Could not fetch topic messages for %s/%s: %s", chat_id, topic_id, exc)
        return []

    return _extract_topic_message_ids(collected, topic_id)


async def _copy_section_messages(
    context: ContextTypes.DEFAULT_TYPE,
    source_chat_id: int,
    source_topic_id: int,
    source_anchor_message_id: int,
    destination_chat_id: int,
    destination_topic_id: int,
    status_message=None,
) -> tuple[int, str | None]:
    message_ids: list[int] = []

    if _mtproto_ready():
        await _try_edit_status_message(
            status_message,
            "🔍 Scanning source section...\n" + _progress_bar(1, 1),
        )
        message_ids = await _collect_topic_message_ids(source_chat_id, source_topic_id)

    if not message_ids:
        return await _copy_messages_with_copy_probe(
            context=context,
            source_chat_id=source_chat_id,
            source_anchor_message_id=source_anchor_message_id,
            destination_chat_id=destination_chat_id,
            destination_topic_id=destination_topic_id,
            status_message=status_message,
        )

    total_to_copy = len(message_ids)
    await _try_edit_status_message(
        status_message,
        "📦 Copying messages...\n" + _progress_bar(0, total_to_copy),
    )

    copied = 0
    update_every = max(1, total_to_copy // 20)
    for idx, message_id in enumerate(message_ids, start=1):
        try:
            await context.bot.copy_message(
                chat_id=destination_chat_id,
                from_chat_id=source_chat_id,
                message_id=message_id,
                message_thread_id=destination_topic_id,
            )
            copied += 1
        except (BadRequest, Forbidden) as exc:
            logger.warning(
                "Could not copy message %s from %s to %s: %s",
                message_id,
                source_chat_id,
                destination_chat_id,
                exc,
            )

        if idx % update_every == 0 or idx == total_to_copy:
            await _try_edit_status_message(
                status_message,
                "📦 Copying messages...\n"
                + _progress_bar(idx, total_to_copy)
                + f"\n✅ Copied so far: {copied}",
            )

    if copied == 0:
        return 0, "I couldn't copy any messages. Check bot permissions in both sections and try again."

    return copied, None


def _looks_like_gateway_store_message(message) -> bool:
    blob = f"{getattr(message, 'text', '') or ''}\n{getattr(message, 'caption', '') or ''}"
    if STORE_WATERMARK in blob or "OLIMPO Watermarked" in blob:
        return True

    markup = getattr(message, "reply_markup", None)
    keyboard = getattr(markup, "inline_keyboard", None) if markup else None
    if keyboard:
        for row in keyboard:
            for button in row:
                label = (getattr(button, "text", "") or "").strip().lower()
                if label == "visit store":
                    return True

    return False


async def _copy_messages_with_copy_probe(
    context: ContextTypes.DEFAULT_TYPE,
    source_chat_id: int,
    source_anchor_message_id: int,
    destination_chat_id: int,
    destination_topic_id: int,
    status_message=None,
) -> tuple[int, str | None]:
    window_back = 200
    window_forward = 2000
    stop_after_miss = 180

    start_id = max(1, source_anchor_message_id - window_back)
    end_id = source_anchor_message_id + window_forward
    total_to_check = end_id - start_id + 1

    copied = 0
    checked = 0
    found_any = False
    misses_after_found = 0
    update_every = max(1, total_to_check // 25)

    for message_id in range(start_id, end_id + 1):
        checked += 1
        copied_message = None

        try:
            copied_message = await context.bot.copy_message(
                chat_id=destination_chat_id,
                from_chat_id=source_chat_id,
                message_id=message_id,
                message_thread_id=destination_topic_id,
                disable_notification=True,
            )
        except (BadRequest, Forbidden):
            copied_message = None

        if copied_message and _looks_like_gateway_store_message(copied_message):
            copied += 1
            found_any = True
            misses_after_found = 0
        else:
            if copied_message:
                try:
                    await context.bot.delete_message(
                        chat_id=destination_chat_id,
                        message_id=copied_message.message_id,
                    )
                except (BadRequest, Forbidden):
                    pass

            if found_any:
                misses_after_found += 1
                if misses_after_found >= stop_after_miss:
                    break

        if checked % update_every == 0 or checked == total_to_check:
            await _try_edit_status_message(
                status_message,
                "🔍 Scanning source section...\n"
                + _progress_bar(checked, total_to_check)
                + f"\n📨 Bot messages found: {copied}",
            )

    if copied == 0:
        return 0, (
            "I couldn't find matching bot messages from that link point. "
            "Send an older link in the same section and try again."
        )

    return copied, None


async def _probe_message_from_this_bot(
    context: ContextTypes.DEFAULT_TYPE,
    source_chat_id: int,
    message_id: int,
    destination_chat_id: int,
    destination_topic_id: int,
) -> bool | None:
    temp = None
    try:
        temp = await context.bot.forward_message(
            chat_id=destination_chat_id,
            from_chat_id=source_chat_id,
            message_id=message_id,
            disable_notification=True,
            message_thread_id=destination_topic_id,
        )
    except (BadRequest, Forbidden):
        return None

    is_bot_origin = False
    try:
        origin = getattr(temp, "forward_origin", None)
        sender_user = getattr(origin, "sender_user", None)
        if sender_user and sender_user.id == context.bot.id:
            is_bot_origin = True
    finally:
        try:
            await context.bot.delete_message(
                chat_id=destination_chat_id,
                message_id=temp.message_id,
            )
        except (BadRequest, Forbidden):
            pass

    return is_bot_origin


async def _collect_bot_message_ids_with_probe(
    context: ContextTypes.DEFAULT_TYPE,
    source_chat_id: int,
    source_anchor_message_id: int,
    destination_chat_id: int,
    destination_topic_id: int,
    status_message=None,
) -> list[int]:
    window_back = 200
    window_forward = 2000
    stop_after_miss = 180

    start_id = max(1, source_anchor_message_id - window_back)
    end_id = source_anchor_message_id + window_forward
    total_to_check = end_id - start_id + 1

    collected: list[int] = []
    misses_after_found = 0
    checked = 0
    update_every = max(1, total_to_check // 25)

    for message_id in range(start_id, end_id + 1):
        checked += 1
        is_bot_origin = await _probe_message_from_this_bot(
            context=context,
            source_chat_id=source_chat_id,
            message_id=message_id,
            destination_chat_id=destination_chat_id,
            destination_topic_id=destination_topic_id,
        )

        if is_bot_origin:
            collected.append(message_id)
            misses_after_found = 0
            continue

        if collected:
            misses_after_found += 1
            if misses_after_found >= stop_after_miss:
                break

        if checked % update_every == 0 or checked == total_to_check:
            await _try_edit_status_message(
                status_message,
                "🔍 Scanning source section...\n"
                + _progress_bar(checked, total_to_check)
                + f"\n📨 Bot messages found: {len(collected)}",
            )

    return collected


async def _finalize_add_store(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    source_message = update.effective_message
    flow = pending.get(user_id, {})
    data = flow.get("data", {})
    store_url = data.get("store_url", "")
    caption = _build_store_caption(data)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Visit Store", url=store_url)]])

    image_type = data.get("image_type")
    image_value = data.get("image")
    target_chat_id = data.get("target_chat_id", update.effective_chat.id)
    target_reply_to = data.get("target_reply_to")
    target_thread_id = data.get("target_thread_id")

    try:
        sent = await context.bot.send_photo(
            chat_id=target_chat_id,
            photo=image_value,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
            reply_to_message_id=target_reply_to,
            message_thread_id=target_thread_id,
        )
    except (BadRequest, Forbidden) as exc:
        if source_message:
            await _reply_text_tracked(
                source_message,
                user_id,
                f"I couldn't send it there: {exc}\nSend another destination link.",
            )
        if image_type == "url":
            if source_message:
                await _reply_text_tracked(source_message, user_id, image_value)
        return False

    if target_chat_id == update.effective_chat.id:
        _track_dm_message(user_id, sent.message_id)

    pending.pop(user_id, None)
    await _clear_tracked_dm_messages(context, user_id)
    return True


async def _send_add_store_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    flow = pending.get(user_id, {})
    if flow.get("mode") != "add_store":
        return False

    data = flow.get("data", {})
    image_value = data.get("image")
    store_url = data.get("store_url", "")
    if not image_value or not store_url:
        return False

    caption = _build_store_caption(data)

    sent = await context.bot.send_photo(
        chat_id=user_id,
        photo=image_value,
        caption=caption,
        parse_mode="HTML",
        reply_markup=_store_preview_keyboard(store_url),
    )
    _track_dm_message(user_id, sent.message_id)
    flow["step"] = "confirm"
    return True


async def _send_custom_message_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    flow = pending.get(user_id, {})
    if flow.get("mode") != "custom_message":
        return False

    data = flow.get("data", {})
    rendered_text, _ = _build_custom_rendered_text(
        data.get("base_text", ""),
        data.get("dynamic"),
        0,
    )
    button_specs = data.get("button_specs", [])

    sent = await context.bot.send_message(
        chat_id=user_id,
        text=rendered_text,
        parse_mode="HTML",
        reply_markup=_custom_preview_keyboard(button_specs),
        disable_web_page_preview=True,
    )
    _track_dm_message(user_id, sent.message_id)
    flow["step"] = "confirm"
    return True


async def _finalize_custom_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    source_message = update.effective_message
    flow = pending.get(user_id, {})
    data = flow.get("data", {})

    base_text = data.get("base_text", "")
    button_specs = data.get("button_specs", [])
    dynamic = data.get("dynamic")
    target_chat_id = data.get("target_chat_id", update.effective_chat.id)
    target_reply_to = data.get("target_reply_to")
    target_thread_id = data.get("target_thread_id")

    rendered_text, _ = _build_custom_rendered_text(base_text, dynamic, 0)

    try:
        sent = await context.bot.send_message(
            chat_id=target_chat_id,
            text=rendered_text,
            parse_mode="HTML",
            reply_markup=_custom_keyboard_from_specs(button_specs),
            reply_to_message_id=target_reply_to,
            message_thread_id=target_thread_id,
            disable_web_page_preview=True,
        )
    except (BadRequest, Forbidden) as exc:
        if source_message:
            await _reply_text_tracked(
                source_message,
                user_id,
                f"I couldn't send it there: {exc}\nSend another destination link.",
            )
        return False

    if dynamic:
        context.application.job_queue.run_repeating(
            callback=_custom_dynamic_message_job,
            interval=1,
            first=1,
            data={
                "chat_id": target_chat_id,
                "message_id": sent.message_id,
                "base_text": base_text,
                "dynamic": dynamic,
                "button_specs": button_specs,
                "started_at": int(time.time()),
            },
            name=f"custom_dynamic_{target_chat_id}_{sent.message_id}",
        )

    pending.pop(user_id, None)
    await _clear_tracked_dm_messages(context, user_id)
    return True


async def _handle_custom_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "custom_message":
        return False

    text = (update.message.text or "").strip()
    step = flow.get("step")
    data = flow.setdefault("data", {})
    _track_dm_message(user_id, update.message.message_id)

    if step == "compose":
        base_text, button_specs, dynamic = _parse_custom_message_template(text)
        if not base_text and not button_specs and not dynamic:
            await _reply_text_tracked(
                update.message,
                user_id,
                "I couldn't parse any message content. Please send your custom message again.",
            )
            return True

        data["base_text"] = base_text
        data["button_specs"] = button_specs
        data["dynamic"] = dynamic
        flow["step"] = "destination"
        await _reply_text_tracked(
            update.message,
            user_id,
            "Thank you! 🙏 Where would you like me to post this message?",
        )
        return True

    if step == "destination":
        parsed = _parse_target_link(text)
        if not parsed:
            await _reply_text_tracked(
                update.message,
                user_id,
                "Invalid link. Send a Telegram post link like https://t.me/c/3857658928/208",
            )
            return True

        target_chat_id, reply_to_message_id, message_thread_id = parsed
        data["target_chat_id"] = target_chat_id
        data["target_reply_to"] = reply_to_message_id
        data["target_thread_id"] = message_thread_id
        await _send_custom_message_preview(update, context)
        return True

    if step == "confirm":
        await _reply_text_tracked(
            update.message,
            user_id,
            "Please use ✅ Confirm or ❌ Cancel below the preview.",
        )
        return True

    return False


async def _handle_add_store_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "add_store":
        return False

    text = (update.message.text or "").strip()
    step = flow.get("step")
    data = flow.setdefault("data", {})
    _track_dm_message(user_id, update.message.message_id)

    if step == "store_name":
        data["store_name"] = text
        flow["step"] = "image"
        await _reply_text_tracked(update.message, user_id, "📸 Please upload the <b>store logo.</b>", parse_mode="HTML")
        return True

    if step == "image":
        normalized = _normalize_store_url(text)
        if not normalized.startswith(("http://", "https://")):
            await _reply_text_tracked(update.message, user_id, "📸 Please upload the <b>store logo.</b>", parse_mode="HTML")
            return True
        data["image_type"] = "url"
        data["image"] = normalized
        flow["step"] = "store_url"
        await _reply_text_tracked(update.message, user_id, "🔗 Please provide me with the <b>store URL.</b>", parse_mode="HTML")
        return True

    if step == "store_url":
        data["store_url"] = _normalize_store_url(text)
        flow["step"] = "country"
        await _reply_text_tracked(
            update.message,
            user_id,
            "🌎 Choose one of the following countries:",
            reply_markup=_store_country_keyboard(),
        )
        return True

    if step == "country":
        await _reply_text_tracked(
            update.message,
            user_id,
            "🌎 Choose one of the following countries:",
            reply_markup=_store_country_keyboard(),
        )
        return True

    if step == "limit":
        data["limit"] = text
        flow["step"] = "timeframe"
        await _reply_text_tracked(
            update.message,
            user_id,
            "⏰ Choose the turnaround timeframe for this specific store:",
            reply_markup=_store_timeframe_keyboard(),
        )
        return True

    if step == "timeframe":
        await _reply_text_tracked(
            update.message,
            user_id,
            "⏰ Choose the turnaround timeframe for this specific store:",
            reply_markup=_store_timeframe_keyboard(),
        )
        return True

    if step == "method":
        await _reply_text_tracked(
            update.message,
            user_id,
            "⚙️ <b>Select the Method.</b>",
            parse_mode="HTML",
            reply_markup=_store_method_keyboard(),
        )
        return True

    if step == "notes":
        data["notes"] = text
        flow["step"] = "destination"
        await _reply_text_tracked(
            update.message,
            user_id,
            "🚀 Ready to Post? Please provide me the URL of the group/section. | Example: <code>https://t.me/c/3857658928/148</code>",
            parse_mode="HTML",
        )
        return True

    if step == "destination":
        parsed = _parse_target_link(text)
        if not parsed:
            await _reply_text_tracked(
                update.message,
                user_id,
                "Invalid link. Send a Telegram post link like https://t.me/c/3857658928/148",
            )
            return True

        target_chat_id, reply_to_message_id, message_thread_id = parsed
        data["target_chat_id"] = target_chat_id
        data["target_reply_to"] = reply_to_message_id
        data["target_thread_id"] = message_thread_id

        await _send_add_store_preview(update, context)
        return True

    if step == "confirm":
        await _reply_text_tracked(
            update.message,
            user_id,
            "Please use ✅ Confirm or ❌ Cancel below the preview.",
        )
        return True

    return False


async def _handle_copy_messages_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "copy_messages":
        return False

    text = (update.message.text or "").strip()
    step = flow.get("step")
    data = flow.setdefault("data", {})
    _track_dm_message(user_id, update.message.message_id)

    if step == "source_section":
        parsed = _parse_section_link(text)
        if not parsed:
            await _reply_text_tracked(
                update.message,
                user_id,
                "Invalid section link. Send something like https://t.me/c/3857658928/148",
            )
            return True

        source_chat_id, source_topic_id, source_anchor_message_id = parsed
        if not await _is_user_admin_in_chat(context, source_chat_id, user_id):
            await _reply_text_tracked(
                update.message,
                user_id,
                "You must be an admin in that source chat/section before I can scrape it.",
            )
            return True

        data["source_chat_id"] = source_chat_id
        data["source_topic_id"] = source_topic_id
        data["source_anchor_message_id"] = source_anchor_message_id
        flow["step"] = "destination_section"
        await _reply_text_tracked(
            update.message,
            user_id,
            "Where would you like me to send all these messages to?",
        )
        return True

    if step == "destination_section":
        parsed = _parse_section_link(text)
        if not parsed:
            await _reply_text_tracked(
                update.message,
                user_id,
                "Invalid section link. Send something like https://t.me/c/3857658928/147",
            )
            return True

        destination_chat_id, destination_topic_id, _destination_anchor_message_id = parsed
        if not await _is_user_admin_in_chat(context, destination_chat_id, user_id):
            await _reply_text_tracked(
                update.message,
                user_id,
                "You must be an admin in that destination chat/section before I can post there.",
            )
            return True

        status_message = await _reply_text_tracked(
            update.message,
            user_id,
            "🔍 Scanning source section...\n" + _progress_bar(0, 1),
        )

        copied, err = await _copy_section_messages(
            context=context,
            source_chat_id=data["source_chat_id"],
            source_topic_id=data["source_topic_id"],
            source_anchor_message_id=data["source_anchor_message_id"],
            destination_chat_id=destination_chat_id,
            destination_topic_id=destination_topic_id,
            status_message=status_message,
        )

        pending.pop(user_id, None)

        if err:
            edited = await _try_edit_status_message(status_message, f"❌ {err}")
            if not edited:
                await _reply_text_tracked(update.message, user_id, err)
            return True

        edited = await _try_edit_status_message(
            status_message,
            f"✅ Done. I copied {copied} message(s) to that section.",
        )
        if not edited:
            await _reply_text_tracked(
                update.message,
                user_id,
                f"Done. I copied {copied} message(s) to that section.",
            )
        return True

    return False


async def _handle_add_store_media(update: Update) -> bool:
    user_id = update.effective_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "add_store":
        return False
    if flow.get("step") != "image":
        return False

    data = flow.setdefault("data", {})
    message = update.message
    _track_dm_message(user_id, message.message_id)

    if message.photo:
        data["image_type"] = "photo"
        data["image"] = message.photo[-1].file_id
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        data["image_type"] = "document"
        data["image"] = message.document.file_id
    else:
        await _reply_text_tracked(update.message, user_id, "📸 Please upload the <b>store logo.</b>", parse_mode="HTML")
        return True

    flow["step"] = "store_url"
    await _reply_text_tracked(update.message, user_id, "🔗 Please provide me with the <b>store URL.</b>", parse_mode="HTML")
    return True


async def store_country_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.message.chat.type != "private":
        return

    user_id = query.from_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "add_store" or flow.get("step") != "country":
        return

    country_code = query.data.replace("store_country_", "", 1)
    if country_code not in STORE_COUNTRIES:
        return

    data = flow.setdefault("data", {})
    data["country"] = country_code
    flow["step"] = "limit"

    await _reply_text_tracked(
        query.message,
        user_id,
        "⛔️ <b>Set the Limits</b> | Example: <code>$1,000 | 10 Items.</code>",
        parse_mode="HTML",
    )


async def store_timeframe_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.message.chat.type != "private":
        return

    user_id = query.from_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "add_store" or flow.get("step") != "timeframe":
        return

    timeframe_key = query.data.replace("store_timeframe_", "", 1)
    timeframe_label = STORE_TIMEFRAMES.get(timeframe_key)
    if not timeframe_label:
        return

    data = flow.setdefault("data", {})
    data["timeframe"] = timeframe_label
    flow["step"] = "method"

    await _reply_text_tracked(
        query.message,
        user_id,
        "⚙️ <b>Select the Method.</b>",
        parse_mode="HTML",
        reply_markup=_store_method_keyboard(),
    )


async def store_method_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.message.chat.type != "private":
        return

    user_id = query.from_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "add_store" or flow.get("step") != "method":
        return

    method_key = query.data.replace("store_method_", "", 1)
    method_label = STORE_METHODS.get(method_key)
    if not method_label:
        return

    data = flow.setdefault("data", {})
    data["method"] = method_label
    flow["step"] = "notes"

    await _reply_text_tracked(
        query.message,
        user_id,
        "📝 Any specific notes?",
        reply_markup=_store_notes_keyboard(),
    )


async def store_notes_na_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.message.chat.type != "private":
        return

    user_id = query.from_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "add_store" or flow.get("step") != "notes":
        return

    data = flow.setdefault("data", {})
    data["notes"] = "N/A"
    flow["step"] = "destination"

    await _reply_text_tracked(
        query.message,
        user_id,
        "🚀 Ready to Post? Please provide me the URL of the group/section. | Example: <code>https://t.me/c/3857658928/148</code>",
        parse_mode="HTML",
    )


async def store_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.message.chat.type != "private":
        return

    user_id = query.from_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "add_store" or flow.get("step") != "confirm":
        return

    if query.data == "store_preview_cancel":
        pending.pop(user_id, None)
        await _clear_tracked_dm_messages(context, user_id)
        return

    if query.data == "store_preview_confirm":
        if query.message:
            _track_dm_message(user_id, query.message.message_id)
        await _finalize_add_store(update, context)


async def custom_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.message.chat.type != "private":
        return

    user_id = query.from_user.id
    flow = pending.get(user_id)
    if not flow or flow.get("mode") != "custom_message" or flow.get("step") != "confirm":
        return

    if query.data == "custom_preview_cancel":
        pending.pop(user_id, None)
        await _clear_tracked_dm_messages(context, user_id)
        return

    if query.data == "custom_preview_confirm":
        if query.message:
            _track_dm_message(user_id, query.message.message_id)
        await _finalize_custom_message(update, context)


# ─── Revocation job ─────────────────────────────────────────────────────────

async def revoke_links_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke invite links and clear the private chat with the user."""
    user_id = None
    job_data = context.job.data
    if isinstance(job_data, dict):
        invite_entries = job_data.get("invite_entries", [])
        user_id = job_data.get("user_id")
        countdown_job_name = job_data.get("countdown_job_name")
        if countdown_job_name:
            for job in context.application.job_queue.get_jobs_by_name(countdown_job_name):
                job.schedule_removal()
    else:
        invite_entries = job_data or []

    for entry in invite_entries:
        try:
            await context.bot.revoke_chat_invite_link(
                chat_id=entry["chat_id"],
                invite_link=entry["invite_link"].invite_link,
            )
            logger.info("Link revoked -> %s", entry["invite_link"].invite_link)
        except (BadRequest, Forbidden) as exc:
            logger.warning("Could not revoke: %s", exc)
        # Extract user_id from job name
        if user_id is None:
            try:
                user_id = int(context.job.name.split("_")[1])
            except (IndexError, ValueError):
                pass

    # Clear all bot messages in the private chat
    if user_id and user_id in _dm_messages:
        for msg_id in _dm_messages[user_id]:
            try:
                await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
            except (BadRequest, Forbidden):
                pass
        del _dm_messages[user_id]
        logger.info("Cleared DM messages for user %s", user_id)


# ─── Gateway handlers (DM only) ─────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private":
        return

    user_id = update.effective_user.id

    # Block fedbanned users
    if is_fedbanned(user_id):
        await update.message.reply_text(t("en", "fedbanned_start"))
        return

    # Block users banned from any configured group
    for gid in GROUP_IDS:
        try:
            member = await context.bot.get_chat_member(gid, user_id)
            if member.status == "kicked":
                await update.message.reply_text(
                    "I'm sorry, you are not allowed to use this bot at this moment."
                )
                return
        except (BadRequest, Forbidden):
            continue

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇺🇸 English", callback_data="lang_en"),
            InlineKeyboardButton("🇲🇽 Español", callback_data="lang_es"),
        ]
    ])
    msg = await update.message.reply_text(
        "🌐 Choose your language / Elige tu idioma:",
        reply_markup=keyboard,
    )
    # Track bot messages for cleanup
    _dm_messages.setdefault(user_id, []).append(update.message.message_id)  # user's /start
    _dm_messages[user_id].append(msg.message_id)


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id

    # Block fedbanned users
    if is_fedbanned(user_id):
        await query.edit_message_text(t("en", "fedbanned_start"))
        return

    lang = "en" if query.data == "lang_en" else "es"
    await _start_math_challenge(query.message, user_id, lang, edit=True)


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if update.effective_chat.type == "private" and _is_addstore_trigger_text(text):
        await _start_add_store_flow(update)
        return

    if update.effective_chat.type == "private" and _is_copymessages_trigger_text(text):
        await _start_copy_messages_flow(update)
        return

    if update.effective_chat.type == "private" and _is_custommessage_trigger_text(text):
        await _start_custom_message_flow(update)
        return

    if _is_add_store_flow(user_id):
        handled = await _handle_add_store_text(update, context)
        if handled:
            return

    if _is_copy_messages_flow(user_id):
        handled = await _handle_copy_messages_text(update, context)
        if handled:
            return

    if _is_custom_message_flow(user_id):
        handled = await _handle_custom_message_text(update, context)
        if handled:
            return

    if user_id not in pending or "answer" not in pending[user_id]:
        lang = pending.get(user_id, {}).get("lang", "en")
        msg = await update.message.reply_text(t(lang, "no_pending"))
        _dm_messages.setdefault(user_id, []).append(update.message.message_id)
        _dm_messages[user_id].append(msg.message_id)
        return

    lang = pending[user_id]["lang"]

    msg = await update.message.reply_text(t(lang, "not_a_number"))
    _dm_messages.setdefault(user_id, []).append(update.message.message_id)
    _dm_messages[user_id].append(msg.message_id)


# ─── Retry captcha callback ─────────────────────────────────────────────────

async def retry_captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a new math problem when user taps 'Try Again'."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    lang = pending.get(user_id, {}).get("lang", "en")
    await _start_math_challenge(query.message, user_id, lang, edit=True)


async def math_answer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.message.chat.type != "private":
        return

    user_id = query.from_user.id
    flow = pending.get(user_id)
    if not flow or "answer" not in flow:
        lang = pending.get(user_id, {}).get("lang", "en")
        await query.edit_message_text(t(lang, "no_pending"))
        return

    lang = flow.get("lang", "en")

    try:
        selected_answer = int(query.data.replace("math_answer_", "", 1))
    except ValueError:
        return

    if selected_answer != flow.get("answer"):
        pending[user_id] = {"lang": lang}
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="retry_captcha")]
        ])
        await query.edit_message_text(
            "❌ Incorrect answer.\nUse /start to try again with a new problem.",
            reply_markup=keyboard,
        )
        return

    pending.pop(user_id, None)
    await query.edit_message_text(
        "✅ Well done! That’s correct! 🎉 I’m now generating your invite links... 🚀"
    )
    await _complete_gateway_success(update, context, user_id, lang)


async def handle_private_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private" or not update.message:
        return

    handled = await _handle_add_store_media(update)
    if handled:
        return


async def admin_addstore_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private" or not update.message or not update.message.text:
        return
    if _is_addstore_trigger_text(update.message.text):
        await _start_add_store_flow(update)


async def admin_copymessages_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private" or not update.message or not update.message.text:
        return
    if _is_copymessages_trigger_text(update.message.text):
        await _start_copy_messages_flow(update)


async def admin_custommessage_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type != "private" or not update.message or not update.message.text:
        return
    if _is_custommessage_trigger_text(update.message.text):
        await _start_custom_message_flow(update)


# ─── Dot-command text trigger handler ────────────────────────────────────────

def _parse_duration(text: str) -> timedelta | None:
    """Parse a duration string like 1h, 30m, 2d, 1w into a timedelta."""
    import re
    m = re.match(r"^(\d+)\s*(s|m|h|d|w)$", text.strip(), re.IGNORECASE)
    if not m:
        return None
    amount = int(m.group(1))
    unit = m.group(2).lower()
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return timedelta(seconds=amount * multipliers[unit])


async def dot_command_trigger(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route dot-commands: .info, .mute, .unmute, .warning"""
    if not update.effective_message or not update.effective_message.text:
        return
    text = update.effective_message.text.strip().lower()
    if text.startswith(".info"):
        await info_command(update, context)
    elif text.startswith(".mute"):
        await mute_command(update, context)
    elif text.startswith(".unmute"):
        await unmute_command(update, context)
    elif text.startswith(".warning"):
        await warning_command(update, context)


async def warning_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """.warning <reason> — reply to a message to warn that user."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        return
    # Accept anonymous admin or real admins
    if user.id != 1087968824 and not await is_admin(chat.id, user.id, context.bot):
        return

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("\u26a0\ufe0f Reply to a message to warn that user.")
        return

    target = msg.reply_to_message.from_user
    if target.is_bot:
        await msg.reply_text("\u26a0\ufe0f Can't warn bots.")
        return

    # Parse reason
    raw_text = (msg.text or "").strip()
    parts = raw_text.split(None, 1)
    reason = parts[1] if len(parts) >= 2 else "No reason given"

    # Get or create user data
    from welcome import get_user_data, _record_user, _users
    data = get_user_data(chat.id, target.id)
    if not data:
        data = _record_user(chat.id, target)

    # Initialize warn_list if missing
    if "warn_list" not in data:
        data["warn_list"] = []

    # Add warning with reason and timestamp
    data["warn_list"].append({
        "reason": reason,
        "date": datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M"),
    })
    data["warns"] = len(data["warn_list"])
    warns = data["warns"]

    username_display = f"@{target.username}" if target.username else target.full_name

    if warns >= 3:
        await context.bot.ban_chat_member(chat.id, target.id)
        warn_text = (
            f"\u26a0\ufe0f {username_display} \u2014 `{target.id}` has reached *3/3* warnings "
            f"and has been \U0001f6ab *banned*.\n"
            f"\u2022 Reason: {reason}"
        )
        await msg.reply_text(warn_text, parse_mode="Markdown")
    else:
        warn_text = (
            f"\u26a0\ufe0f {username_display} \u2014 `{target.id}` has been warned "
            f"({warns}/3).\n"
            f"\u2022 Reason: {reason}"
        )
        await msg.reply_text(warn_text, parse_mode="Markdown")


async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """.mute <time> <reason> — reply to a message to mute that user."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        return
    # Accept anonymous admin (GroupAnonymousBot) or real admins
    if user.id != 1087968824 and not await is_admin(chat.id, user.id, context.bot):
        return

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("⚠️ Reply to a message to mute that user.")
        return

    target = msg.reply_to_message.from_user
    if target.is_bot:
        await msg.reply_text("⚠️ Cannot mute a bot.")
        return

    # Check if target is admin
    if await is_admin(chat.id, target.id, context.bot):
        await msg.reply_text("⚠️ Cannot mute an admin.")
        return

    # Parse: .mute 1d mucho spam
    text = (msg.text or "").strip()
    parts = text.split(None, 2)  # [".mute", "1d", "mucho spam"]

    duration = None
    reason = "No reason provided"

    if len(parts) >= 2:
        duration = _parse_duration(parts[1])
    if len(parts) >= 3:
        reason = parts[2]

    if not duration:
        await msg.reply_text("⚠️ Invalid format. Use: `.mute 1h reason`\nExamples: `30m`, `1h`, `1d`, `1w`", parse_mode="Markdown")
        return

    until_date = datetime.now(timezone.utc) + duration
    until_str = until_date.strftime("%d %b %Y, %H:%M")

    # Restrict the user
    from telegram import ChatPermissions as _CP
    try:
        await context.bot.restrict_chat_member(
            chat.id, target.id,
            permissions=_CP(can_send_messages=False),
            until_date=until_date,
        )
    except (BadRequest, Forbidden) as exc:
        await msg.reply_text(f"❌ Could not mute: {exc}")
        return

    username_display = f"@{target.username}" if target.username else target.full_name
    mute_text = (
        f"{username_display} — `{target.id}` has been 🔇 muted.\n"
        f"• Until: {until_str}\n"
        f"• Reason: {reason}"
    )

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔑 Permissions", callback_data=f"info_perms_{target.id}"),
            InlineKeyboardButton("✅ Unmute", callback_data=f"unmute_{target.id}"),
        ]
    ])

    await msg.reply_text(mute_text, reply_markup=buttons, parse_mode="Markdown")


async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """.unmute — reply to a message to unmute that user."""
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user

    if chat.type not in ("group", "supergroup"):
        return
    if user.id != 1087968824 and not await is_admin(chat.id, user.id, context.bot):
        return

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_text("⚠️ Reply to a message to unmute that user.")
        return

    target = msg.reply_to_message.from_user

    from telegram import ChatPermissions as _CP
    try:
        await context.bot.restrict_chat_member(
            chat.id, target.id,
            permissions=_CP(
                can_send_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_invite_users=True,
            ),
        )
    except (BadRequest, Forbidden) as exc:
        await msg.reply_text(f"❌ Could not unmute: {exc}")
        return

    username_display = f"@{target.username}" if target.username else target.full_name
    await msg.reply_text(f"✅ {username_display} [`{target.id}`] has been unmuted.", parse_mode="Markdown")


async def unmute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the Unmute button from .mute responses."""
    query = update.callback_query
    chat_id = query.message.chat.id

    if query.from_user.id != 1087968824 and not await is_admin(chat_id, query.from_user.id, context.bot):
        await query.answer("⛔ Admin only.", show_alert=True)
        return

    try:
        target_uid = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer()
        return

    from telegram import ChatPermissions as _CP
    try:
        await context.bot.restrict_chat_member(
            chat_id, target_uid,
            permissions=_CP(
                can_send_messages=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_invite_users=True,
            ),
        )
        await query.answer("✅ User unmuted.", show_alert=True)
    except (BadRequest, Forbidden) as exc:
        await query.answer(f"Error: {exc}", show_alert=True)


# ─── Join request handling ───────────────────────────────────────────────────

async def handle_join_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming join requests.
    - Fedbanned users → declined immediately.
    - Recently verified users (passed math captcha) → approved + welcome+captcha sent.
    - Other users → stored for 36h auto-approve.
    """
    join_request = update.chat_join_request
    if not join_request:
        return

    user = join_request.from_user
    chat = join_request.chat

    # Main group is always manual approval only
    if _is_manual_approval_chat(chat.id):
        _pending_requests[(chat.id, user.id)] = time.time()
        logger.info(
            "Join request in Main kept for manual admin approval: %s (%s) in %s",
            user.id, user.full_name, chat.id,
        )
        return

    # Block fedbanned users immediately
    if is_fedbanned(user.id):
        try:
            await join_request.decline()
        except (BadRequest, Forbidden):
            pass
        return

    # If user recently passed the DM math captcha, approve immediately
    verified_at = verified_users.get(user.id)
    if verified_at and (time.time() - verified_at) < 48 * 3600:
        try:
            await join_request.approve()
            logger.info("Auto-approved verified user: %s (%s) in %s", user.id, user.full_name, chat.id)
        except (BadRequest, Forbidden) as exc:
            logger.warning("Could not approve join request: %s", exc)
            return

        # Send welcome + captcha right away
        lang = get_chat_lang(chat.id)
        await restrict_and_welcome(chat, user, context, lang)
        # Remove from pending if present
        _pending_requests.pop((chat.id, user.id), None)
    else:
        # Store for 36h auto-approval
        _pending_requests[(chat.id, user.id)] = time.time()
        logger.info(
            "Join request stored: %s (%s) in %s — pending 36h auto-approve",
            user.id, user.full_name, chat.id,
        )


async def auto_approve_stale_requests(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Periodic job: auto-approve join requests that have been pending for 36+ hours."""
    now = time.time()
    to_remove: list[tuple[int, int]] = []

    for (chat_id, user_id), requested_at in list(_pending_requests.items()):
        if _is_manual_approval_chat(chat_id):
            continue
        if (now - requested_at) >= PENDING_APPROVAL_TIMEOUT:
            try:
                await context.bot.approve_chat_join_request(chat_id, user_id)
                logger.info("Auto-approved stale request: user %s in chat %s (waited 36h+)", user_id, chat_id)
                # Send welcome + captcha
                try:
                    chat = await context.bot.get_chat(chat_id)
                    member = await context.bot.get_chat_member(chat_id, user_id)
                    lang = get_chat_lang(chat_id)
                    await restrict_and_welcome(chat, member.user, context, lang)
                except (BadRequest, Forbidden) as exc:
                    logger.warning("Could not send welcome after stale approval: %s", exc)
            except (BadRequest, Forbidden) as exc:
                logger.warning("Could not auto-approve %s in %s: %s", user_id, chat_id, exc)
            to_remove.append((chat_id, user_id))

    for key in to_remove:
        _pending_requests.pop(key, None)


async def welcome_manually_approved_requests(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Fallback: for manual-approval chats, detect approved users and send welcome+captcha.
    This covers cases where Telegram does not deliver a join event update.
    """
    to_remove: list[tuple[int, int]] = []

    for (chat_id, user_id), _requested_at in list(_pending_requests.items()):
        if not _is_manual_approval_chat(chat_id):
            continue

        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
        except (BadRequest, Forbidden):
            continue

        if member.status in ("member", "restricted", "administrator", "creator"):
            try:
                chat = await context.bot.get_chat(chat_id)
                lang = get_chat_lang(chat_id)
                await restrict_and_welcome(chat, member.user, context, lang)
                logger.info(
                    "Detected manual approval; welcome sent: user %s in chat %s",
                    user_id, chat_id,
                )
            except (BadRequest, Forbidden) as exc:
                logger.warning(
                    "Could not send welcome after manual approval for %s in %s: %s",
                    user_id, chat_id, exc,
                )
            to_remove.append((chat_id, user_id))

    for key in to_remove:
        _pending_requests.pop(key, None)


async def on_member_joined(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ChatMemberUpdated — welcome + captcha when user becomes a member."""
    member_update = update.chat_member
    if not member_update:
        return

    chat = member_update.chat
    if chat.type not in ("group", "supergroup"):
        return

    old_status = member_update.old_chat_member.status
    new_status = member_update.new_chat_member.status
    user = member_update.new_chat_member.user

    # Only act when user goes from non-member to member
    if old_status in ("left", "kicked") and new_status in ("member", "restricted"):
        _pending_requests.pop((chat.id, user.id), None)
        if user.is_bot:
            return
        lang = get_chat_lang(chat.id)
        await restrict_and_welcome(chat, user, context, lang)


# ─── Diagnostic ──────────────────────────────────────────────────────────────

@admin_only
async def chatid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    await update.message.reply_text(
        f"ℹ️ ID: `{chat.id}`\nType: {chat.type}\nTitle: {chat.title or 'N/A'}",
        parse_mode="Markdown",
    )


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Simple liveness check."""
    await update.message.reply_text("\U0001f3d3 pong")


HELP_OWNER_USERNAME = "gordo"

HELP_TEXT = (
    "\U0001f916 <b>Gateway TG \u2014 Command Reference</b>\n"
    "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n"

    "\U0001f4e6 <b>Gateway (DM)</b>\n"
    "  \u2022 /start \u2014 Begin setup\n"
    "  \u2022 <code>add store</code> \u2014 Add a store listing\n"
    "  \u2022 <code>copy messages</code> \u2014 Copy messages\n"
    "  \u2022 <code>custom message</code> \u2014 Custom message\n\n"

    "\U0001f451 <b>Admin</b>\n"
    "  \u2022 /promote  /demote\n"
    "  \u2022 /adminlist  /admincache\n"
    "  \u2022 /anonadmin  /adminerror\n\n"

    "\U0001f30a <b>Flood Control</b>\n"
    "  \u2022 /flood  /setflood  /setfloodtimer\n"
    "  \u2022 /floodmode  /clearflood\n\n"

    "\U0001f6e1 <b>Anti-Raid</b>\n"
    "  \u2022 /antiraid  /raidtime\n"
    "  \u2022 /raidactiontime  /autoantiraid\n\n"

    "\u2705 <b>Approvals</b>\n"
    "  \u2022 /approval  /approve  /unapprove\n"
    "  \u2022 /approved  /unapproveall\n\n"

    "\U0001f528 <b>Bans &amp; Mutes</b>\n"
    "  \u2022 /ban  /dban  /sban  /tban  /unban\n"
    "  \u2022 /mute  /dmute  /smute  /tmute  /unmute\n"
    "  \u2022 /kick  /dkick  /skick  /kickme\n\n"

    "\U0001f6ab <b>Blocklists</b>\n"
    "  \u2022 /addblocklist  /rmblocklist\n"
    "  \u2022 /blocklist  /blocklistmode\n"
    "  \u2022 /blocklistdelete\n\n"

    "\U0001f310 <b>Federations</b>\n"
    "  \u2022 /newfed  /joinfed  /leavefed\n"
    "  \u2022 /fedban  /unfedban\n"
    "  \u2022 /fedadmins  /fedpromote  /feddemote\n"
    "  \u2022 /fedinfo  /fedchats\n\n"

    "\U0001f527 <b>Diagnostics</b>\n"
    "  \u2022 /chatid  /ping  /staff\n"
    "  \u2022 <code>.info</code> @user \u2014 User info card"
)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help \u2014 restricted to @gordo."""
    user = update.effective_user
    if not user or (user.username or "").lower() != HELP_OWNER_USERNAME.lower():
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="HTML")


# ─── Main ────────────────────────────────────────────────────────────────────

GROUP_FILTER = filters.ChatType.GROUP | filters.ChatType.SUPERGROUP

# Service message filters — everything we want to auto-delete
SERVICE_FILTER = (
    filters.StatusUpdate.NEW_CHAT_MEMBERS
    | filters.StatusUpdate.LEFT_CHAT_MEMBER
    | filters.StatusUpdate.NEW_CHAT_TITLE
    | filters.StatusUpdate.NEW_CHAT_PHOTO
    | filters.StatusUpdate.DELETE_CHAT_PHOTO
    | filters.StatusUpdate.PINNED_MESSAGE
    | filters.StatusUpdate.CHAT_SHARED
    | filters.StatusUpdate.WRITE_ACCESS_ALLOWED
    | filters.StatusUpdate.FORUM_TOPIC_CREATED
    | filters.StatusUpdate.FORUM_TOPIC_CLOSED
    | filters.StatusUpdate.FORUM_TOPIC_REOPENED
    | filters.StatusUpdate.FORUM_TOPIC_EDITED
    | filters.StatusUpdate.GENERAL_FORUM_TOPIC_HIDDEN
    | filters.StatusUpdate.GENERAL_FORUM_TOPIC_UNHIDDEN
)


def main() -> None:
    application = Application.builder().token(BOT_TOKEN).build()

    async def _on_application_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        if isinstance(context.error, Conflict):
            logger.warning(
                "Telegram Conflict detected (another instance may be running). "
                "Will retry automatically."
            )
            return

        logger.exception("Unhandled application error", exc_info=context.error)

    application.add_error_handler(_on_application_error)


    # ── Gateway (DM) ─────────────────────────────────────────────────────
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(
        MessageHandler(
            filters.Regex(r"(?i)add\s*[-_–—‑]?\s*store") & filters.ChatType.PRIVATE,
            admin_addstore_trigger,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(r"(?i)copy\s*[-_–—‑]?\s*messages") & filters.ChatType.PRIVATE,
            admin_copymessages_trigger,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Regex(r"(?i)custom\s*[-_–—‑]?\s*message") & filters.ChatType.PRIVATE,
            admin_custommessage_trigger,
        )
    )
    application.add_handler(
        CallbackQueryHandler(language_callback, pattern=r"^lang_(en|es)$")
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_answer,
        )
    )
    application.add_handler(
        MessageHandler(
            (filters.PHOTO | filters.Document.IMAGE) & filters.ChatType.PRIVATE,
            handle_private_media,
        )
    )

    # ── Admin ────────────────────────────────────────────────────────────
    application.add_handler(CommandHandler("promote", promote_command))
    application.add_handler(CommandHandler("demote", demote_command))
    application.add_handler(CommandHandler("adminlist", adminlist_command))
    application.add_handler(CommandHandler("admincache", admincache_command))
    application.add_handler(CommandHandler("anonadmin", anonadmin_command))
    application.add_handler(CommandHandler("adminerror", adminerror_command))

    # ── Antiflood ────────────────────────────────────────────────────────
    application.add_handler(CommandHandler("flood", flood_command))
    application.add_handler(CommandHandler("setflood", setflood_command))
    application.add_handler(CommandHandler("setfloodtimer", setfloodtimer_command))
    application.add_handler(CommandHandler("floodmode", floodmode_command))
    application.add_handler(CommandHandler("clearflood", clearflood_command))

    # ── Antiraid ─────────────────────────────────────────────────────────
    application.add_handler(CommandHandler("antiraid", antiraid_command))
    application.add_handler(CommandHandler("raidtime", raidtime_command))
    application.add_handler(CommandHandler("raidactiontime", raidactiontime_command))
    application.add_handler(CommandHandler("autoantiraid", autoantiraid_command))

    # ── Approval ─────────────────────────────────────────────────────────
    application.add_handler(CommandHandler("approval", approval_command))
    application.add_handler(CommandHandler("approve", approve_command))
    application.add_handler(CommandHandler("unapprove", unapprove_command))
    application.add_handler(CommandHandler("approved", approved_command))
    application.add_handler(CommandHandler("unapproveall", unapproveall_command))

    # ── Bans ─────────────────────────────────────────────────────────────
    application.add_handler(CommandHandler("ban", ban_command))
    application.add_handler(CommandHandler("dban", dban_command))
    application.add_handler(CommandHandler("sban", sban_command))
    application.add_handler(CommandHandler("tban", tban_command))
    application.add_handler(CommandHandler("unban", unban_command))
    application.add_handler(CommandHandler("mute", mute_command))
    application.add_handler(CommandHandler("dmute", dmute_command))
    application.add_handler(CommandHandler("smute", smute_command))
    application.add_handler(CommandHandler("tmute", tmute_command))
    application.add_handler(CommandHandler("unmute", unmute_command))
    application.add_handler(CommandHandler("kick", kick_command))
    application.add_handler(CommandHandler("dkick", dkick_command))
    application.add_handler(CommandHandler("skick", skick_command))
    application.add_handler(CommandHandler("kickme", kickme_command))

    # ── Blocklists ───────────────────────────────────────────────────────
    application.add_handler(CommandHandler("addblocklist", addblocklist_command))
    application.add_handler(CommandHandler("rmblocklist", rmblocklist_command))
    application.add_handler(CommandHandler("unblocklistall", unblocklistall_command))
    application.add_handler(CommandHandler("blocklist", blocklist_command))
    application.add_handler(CommandHandler("blocklistmode", blocklistmode_command))
    application.add_handler(CommandHandler("blocklistdelete", blocklistdelete_command))
    application.add_handler(CommandHandler("setblocklistreason", setblocklistreason_command))
    application.add_handler(CommandHandler("resetblocklistreason", resetblocklistreason_command))

    # ── Federation ───────────────────────────────────────────────────────
    application.add_handler(CommandHandler("newfed", newfed_command))
    application.add_handler(CommandHandler("joinfed", joinfed_command))
    application.add_handler(CommandHandler("leavefed", leavefed_command))
    application.add_handler(CommandHandler("fedban", fedban_command))
    application.add_handler(CommandHandler("unfedban", unfedban_command))
    application.add_handler(CommandHandler("fedadmins", fedadmins_command))
    application.add_handler(CommandHandler("fedpromote", fedpromote_command))
    application.add_handler(CommandHandler("feddemote", feddemote_command))
    application.add_handler(CommandHandler("fedinfo", fedinfo_command))
    application.add_handler(CommandHandler("fedchats", fedchats_command))

    # ── Welcome + Staff ──────────────────────────────────────────────────
    application.add_handler(CommandHandler("staff", staff_command))

    # ── Diagnostic ───────────────────────────────────────────────────────
    application.add_handler(CommandHandler("ping", ping_command))
    application.add_handler(CommandHandler("chatid", chatid_command))
    application.add_handler(CommandHandler("help", help_command))

    # ── Callback query handlers for captcha + info + retry ─────────────
    application.add_handler(
        CallbackQueryHandler(captcha_callback, pattern=r"^captcha_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(info_action_callback, pattern=r"^info_(warn|mute|ban|perms)_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(retry_captcha_callback, pattern=r"^retry_captcha$")
    )
    application.add_handler(
        CallbackQueryHandler(math_answer_callback, pattern=r"^math_answer_-?\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(store_country_callback, pattern=r"^store_country_(US|CA|UK|EU|AUS|MX)$")
    )
    application.add_handler(
        CallbackQueryHandler(
            store_timeframe_callback,
            pattern=r"^store_timeframe_(TF_INSTANT|TF_1_5_DAYS|TF_7_DAYS|TF_1_2_WEEKS|TF_2_3_WEEKS|TF_3_4_WEEKS|TF_4_WEEKS)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            store_method_callback,
            pattern=r"^store_method_(M_FTID_V3|M_WEIGHTED_FTID|M_LIT|M_DNA|M_EB|M_FTID_ROS|M_FTID_ROD|M_FTIDNA|M_DMG_RTS|M_RTS|M_UTD|M_PTDNA|M_PEB)$",
        )
    )
    application.add_handler(
        CallbackQueryHandler(store_notes_na_callback, pattern=r"^store_notes_na$")
    )
    application.add_handler(
        CallbackQueryHandler(store_preview_callback, pattern=r"^store_preview_(confirm|cancel)$")
    )
    application.add_handler(
        CallbackQueryHandler(custom_preview_callback, pattern=r"^custom_preview_(confirm|cancel)$")
    )
    application.add_handler(
        CallbackQueryHandler(unmute_callback, pattern=r"^unmute_\d+$")
    )
    application.add_handler(
        CallbackQueryHandler(unban_callback, pattern=r"^unban_\d+$")
    )

    # ── Passive group handlers (run for every group message, ordered) ────
    # group 1: Track messages for user data / inactivity
    application.add_handler(
        MessageHandler(filters.ALL & GROUP_FILTER, track_message), group=1,
    )
    # group 2: Antiflood
    application.add_handler(
        MessageHandler(filters.ALL & GROUP_FILTER, check_flood), group=2,
    )
    # group 3: Blocklist checking
    application.add_handler(
        MessageHandler(filters.ALL & GROUP_FILTER, check_blocklist), group=3,
    )
    # group 4: Dot-command text triggers (.info, .mute, .unmute)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & GROUP_FILTER, dot_command_trigger,
        ),
        group=4,
    )
    # group 5: New member → CAPTCHA + welcome + fedban check + antiraid
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS & GROUP_FILTER, on_new_member,
        ),
        group=5,
    )
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS & GROUP_FILTER, check_fedban_on_join,
        ),
        group=7,
    )
    application.add_handler(
        MessageHandler(
            filters.StatusUpdate.NEW_CHAT_MEMBERS & GROUP_FILTER, check_raid,
        ),
        group=8,
    )

    # ── Join request auto-approve (for creates_join_request links) ────
    application.add_handler(ChatJoinRequestHandler(handle_join_request))

    # ── ChatMemberUpdated → welcome + captcha on join ────────────────
    application.add_handler(
        ChatMemberHandler(on_member_joined, ChatMemberHandler.CHAT_MEMBER)
    )

    # group 9: Auto-delete service messages (joins, leaves, title changes, etc.)
    application.add_handler(
        MessageHandler(
            SERVICE_FILTER & GROUP_FILTER, delete_service_message,
        ),
        group=9,
    )

    # ── Periodic jobs ────────────────────────────────────────────────────
    # Inactivity checker (every 6 hours)
    application.job_queue.run_repeating(
        callback=kick_inactive_job,
        interval=CHECK_INTERVAL_SECONDS,
        first=CHECK_INTERVAL_SECONDS,
        name="inactivity_checker",
    )
    # Auto-approve stale join requests (check every hour)
    application.job_queue.run_repeating(
        callback=auto_approve_stale_requests,
        interval=3600,
        first=3600,
        name="stale_request_approver",
    )
    # Fallback checker for manually-approved requests in Main (every minute)
    application.job_queue.run_repeating(
        callback=welcome_manually_approved_requests,
        interval=60,
        first=20,
        name="manual_approval_welcome_checker",
    )

    logger.info("Bot started — forcing POLLING mode (ignoring RAILWAY_PUBLIC_DOMAIN)")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=[
            "message", "edited_message", "channel_post", "edited_channel_post",
            "inline_query", "chosen_inline_result", "callback_query",
            "shipping_query", "pre_checkout_query", "poll", "poll_answer",
            "my_chat_member", "chat_member", "chat_join_request",
        ]
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.critical("FATAL: main() crashed: %s", exc, exc_info=True)
        raise
