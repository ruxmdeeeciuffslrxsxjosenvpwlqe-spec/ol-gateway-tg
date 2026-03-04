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
    "TF_1_4_DAYS": "1-4 Days",
    "TF_7_DAYS": "7 Days",
    "TF_1_2_WEEKS": "1-2 Weeks",
    "TF_2_3_WEEKS": "2-3 Weeks",
    "TF_3_4_WEEKS": "3-4 Weeks",
    "TF_4_WEEKS": "4 Weeks",
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
            InlineKeyboardButton("US", callback_data="store_country_US"),
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
        [InlineKeyboardButton("1-4 Days", callback_data="store_timeframe_TF_1_4_DAYS")],
        [InlineKeyboardButton("7 Days", callback_data="store_timeframe_TF_7_DAYS")],
        [InlineKeyboardButton("1-2 Weeks", callback_data="store_timeframe_TF_1_2_WEEKS")],
        [InlineKeyboardButton("2-3 Weeks", callback_data="store_timeframe_TF_2_3_WEEKS")],
        [InlineKeyboardButton("3-4 Weeks", callback_data="store_timeframe_TF_3_4_WEEKS")],
        [InlineKeyboardButton("4 Weeks", callback_data="store_timeframe_TF_4_WEEKS")],
    ])


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
    await _reply_text_tracked(update.message, user_id, "Give me the store name.")


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
        message_ids = await _collect_bot_message_ids_with_probe(
            context=context,
            source_chat_id=source_chat_id,
            source_anchor_message_id=source_anchor_message_id,
            destination_chat_id=destination_chat_id,
            destination_topic_id=destination_topic_id,
            status_message=status_message,
        )

    if not message_ids:
        return 0, (
            "I couldn't find bot-sent messages from that link point. "
            "Send an older link in the same section and try again."
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
    flow = pending.get(user_id, {})
    data = flow.get("data", {})

    country_code = data.get("country", "US")
    country_flag = STORE_COUNTRIES.get(country_code, "🇺🇸")

    store_name = escape(data.get("store_name", "N/A"))
    limit_text = escape(data.get("limit", "N/A"))
    method_text = escape(data.get("method", "N/A"))
    notes_text = escape(data.get("notes", "N/A"))
    timeframe_text = escape(data.get("timeframe", "N/A"))
    store_url = data.get("store_url", "")

    caption = (
        f"{country_flag} {store_name} {country_flag}\n"
        f"<code>{STORE_WATERMARK}</code>\n\n"
        f"<b>Limit:</b> {limit_text}\n"
        f"<b>Timeframe:</b> {timeframe_text}\n"
        f"<b>Method:</b> {method_text}\n"
        f"<b>Notes:</b> {notes_text}\n\n"
        f"<code>{STORE_WATERMARK}</code>"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Visit Store", url=store_url)]
    ])

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
        await _reply_text_tracked(
            update.message,
            user_id,
            f"I couldn't send it there: {exc}\nSend another destination link.",
        )
        if image_type == "url":
            await _reply_text_tracked(update.message, user_id, image_value)
        return False

    if target_chat_id == update.effective_chat.id:
        _track_dm_message(user_id, sent.message_id)

    pending.pop(user_id, None)
    await _clear_tracked_dm_messages(context, user_id)
    return True


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
        await _reply_text_tracked(update.message, user_id, "Give me the image.")
        return True

    if step == "image":
        normalized = _normalize_store_url(text)
        if not normalized.startswith(("http://", "https://")):
            await _reply_text_tracked(update.message, user_id, "Give me the image.")
            return True
        data["image_type"] = "url"
        data["image"] = normalized
        flow["step"] = "store_url"
        await _reply_text_tracked(update.message, user_id, "Give me the store URL")
        return True

    if step == "store_url":
        data["store_url"] = _normalize_store_url(text)
        flow["step"] = "country"
        await _reply_text_tracked(
            update.message,
            user_id,
            "Select the country",
            reply_markup=_store_country_keyboard(),
        )
        return True

    if step == "country":
        await _reply_text_tracked(
            update.message,
            user_id,
            "Select the country",
            reply_markup=_store_country_keyboard(),
        )
        return True

    if step == "limit":
        data["limit"] = text
        flow["step"] = "timeframe"
        await _reply_text_tracked(
            update.message,
            user_id,
            "Select timeframe",
            reply_markup=_store_timeframe_keyboard(),
        )
        return True

    if step == "timeframe":
        await _reply_text_tracked(
            update.message,
            user_id,
            "Select timeframe",
            reply_markup=_store_timeframe_keyboard(),
        )
        return True

    if step == "method":
        data["method"] = text
        flow["step"] = "notes"
        await _reply_text_tracked(update.message, user_id, "Add your notes")
        return True

    if step == "notes":
        data["notes"] = text
        flow["step"] = "destination"
        await _reply_text_tracked(update.message, user_id, "Where should I send this message?")
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

        await _finalize_add_store(update, context)
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
        await _reply_text_tracked(update.message, user_id, "Give me the image.")
        return True

    flow["step"] = "store_url"
    await _reply_text_tracked(update.message, user_id, "Give me the store URL")
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

    await _reply_text_tracked(query.message, user_id, "Give me the $ or item limit.")


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

    await _reply_text_tracked(query.message, user_id, "Give me the method.")


# ─── Revocation job ─────────────────────────────────────────────────────────

async def revoke_links_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Revoke invite links and clear the private chat with the user."""
    user_id = None
    for entry in context.job.data:
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
    question, answer = generate_math_problem()
    pending[user_id] = {"lang": lang, "question": question, "answer": answer}
    await query.edit_message_text(
        t(lang, "math_prompt", q=question), parse_mode="Markdown",
    )


async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if update.effective_chat.type == "private" and _is_addstore_trigger_text(text):
        await _start_add_store_flow(update)
        return

    if update.effective_chat.type == "private" and _is_copymessages_trigger_text(text):
        await _start_copy_messages_flow(update)
        return

    if _is_add_store_flow(user_id):
        handled = await _handle_add_store_text(update, context)
        if handled:
            return

    if _is_copy_messages_flow(user_id):
        handled = await _handle_copy_messages_text(update, context)
        if handled:
            return

    if user_id not in pending or "answer" not in pending[user_id]:
        lang = pending.get(user_id, {}).get("lang", "en")
        msg = await update.message.reply_text(t(lang, "no_pending"))
        _dm_messages.setdefault(user_id, []).append(update.message.message_id)
        _dm_messages[user_id].append(msg.message_id)
        return

    lang = pending[user_id]["lang"]

    try:
        user_answer = int(text)
    except ValueError:
        msg = await update.message.reply_text(t(lang, "not_a_number"))
        _dm_messages.setdefault(user_id, []).append(update.message.message_id)
        _dm_messages[user_id].append(msg.message_id)
        return

    if user_answer != pending[user_id]["answer"]:
        del pending[user_id]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Try Again", callback_data="retry_captcha")]
        ])
        msg = await update.message.reply_text(
            t(lang, "incorrect"),
            reply_markup=keyboard,
        )
        _dm_messages.setdefault(user_id, []).append(update.message.message_id)
        _dm_messages[user_id].append(msg.message_id)
        return

    # Correct
    del pending[user_id]
    verified_users[user_id] = time.time()  # Track verification time
    correct_msg = await update.message.reply_text(t(lang, "correct"))
    _dm_messages.setdefault(user_id, []).append(update.message.message_id)
    _dm_messages[user_id].append(correct_msg.message_id)

    invite_entries: list[dict] = []
    buttons: list[list[InlineKeyboardButton]] = []

    for gid, gname in zip(GROUP_IDS, GROUP_NAMES):
        try:
            invite = await context.bot.create_chat_invite_link(
                chat_id=gid,
                expire_date=datetime.now(timezone.utc) + timedelta(seconds=60),
                creates_join_request=True,
                name=f"Gateway – {user_id}",
            )
            invite_entries.append({"chat_id": gid, "invite_link": invite})
            buttons.append([
                InlineKeyboardButton(f"🔗 {gname}", url=invite.invite_link)
            ])
            logger.info("Link created → %s (%s) | %s", gid, gname, invite.invite_link)
        except (Forbidden, BadRequest) as exc:
            logger.warning("Error creating link in %s (%s): %s", gid, gname, exc)

    if not buttons:
        msg = await update.message.reply_text(t(lang, "no_links"))
        _dm_messages.setdefault(user_id, []).append(msg.message_id)
        return

    links_msg = await update.message.reply_text(
        t(lang, "links_message"),
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    _dm_messages.setdefault(user_id, []).append(links_msg.message_id)

    context.application.job_queue.run_once(
        callback=revoke_links_job, when=60, data=invite_entries,
        name=f"revoke_{user_id}_{datetime.now(timezone.utc).timestamp():.0f}",
    )


# ─── Retry captcha callback ─────────────────────────────────────────────────

async def retry_captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generate a new math problem when user taps 'Try Again'."""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    lang = pending.get(user_id, {}).get("lang", "en")

    question, answer = generate_math_problem()
    pending[user_id] = {"lang": lang, "question": question, "answer": answer}
    await query.edit_message_text(
        t(lang, "math_prompt", q=question), parse_mode="Markdown",
    )


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
            logger.critical(
                "Telegram Conflict detected: another bot instance is using this BOT_TOKEN (duplicate polling/getUpdates). "
                "Stopping this process. Ensure only one active instance runs in polling mode."
            )
            await context.application.stop()
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
    application.add_handler(CommandHandler("chatid", chatid_command))

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
        CallbackQueryHandler(store_country_callback, pattern=r"^store_country_(US|CA|UK|EU|AUS|MX)$")
    )
    application.add_handler(
        CallbackQueryHandler(
            store_timeframe_callback,
            pattern=r"^store_timeframe_(TF_1_4_DAYS|TF_7_DAYS|TF_1_2_WEEKS|TF_2_3_WEEKS|TF_3_4_WEEKS|TF_4_WEEKS)$",
        )
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

    logger.info("Bot started — waiting for messages...")

    # Detect Render environment for webhook mode
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    PORT = int(os.environ.get("PORT", "10000"))

    if RENDER_URL:
        # Webhook mode for Render free tier
        webhook_url = f"{RENDER_URL}/webhook"
        logger.info(f"Running in WEBHOOK mode on port {PORT} → {webhook_url}")
        try:
            application.run_webhook(
                listen="0.0.0.0",
                port=PORT,
                url_path="webhook",
                webhook_url=webhook_url,
                allowed_updates=[
                    "message", "edited_message", "channel_post", "edited_channel_post",
                    "inline_query", "chosen_inline_result", "callback_query",
                    "shipping_query", "pre_checkout_query", "poll", "poll_answer",
                    "my_chat_member", "chat_member", "chat_join_request",
                ],
            )
        except Conflict:
            logger.critical(
                "Telegram Conflict detected at startup. Another instance is already using this BOT_TOKEN. "
                "Stop duplicate instances (Render/local/other hosts) and restart only one bot process."
            )
            raise SystemExit(1)
    else:
        # Polling mode for local development
        logger.info("Running in POLLING mode (local)")
        try:
            application.run_polling(
                allowed_updates=[
                    "message", "edited_message", "channel_post", "edited_channel_post",
                    "inline_query", "chosen_inline_result", "callback_query",
                    "shipping_query", "pre_checkout_query", "poll", "poll_answer",
                    "my_chat_member", "chat_member", "chat_join_request",
                ]
            )
        except Conflict:
            logger.critical(
                "Telegram Conflict detected at startup. Another instance is already using this BOT_TOKEN. "
                "Stop duplicate instances (local/hosting/CI) and restart only one bot process."
            )
            raise SystemExit(1)


if __name__ == "__main__":
    main()
