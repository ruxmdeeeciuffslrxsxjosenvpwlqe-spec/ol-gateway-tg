"""
admin.py — Admin management: promote, demote, admin list, cache, and settings.
"""

import logging
import time
from functools import wraps
from typing import Optional

from telegram import ChatMember, ChatMemberAdministrator, ChatMemberOwner, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from strings import t

logger = logging.getLogger(__name__)

# ─── Admin cache ─────────────────────────────────────────────────────────────
# {chat_id: {"admins": {user_id: ChatMember, ...}, "updated": timestamp,
#             "anonadmin": bool, "adminerror": bool, "lang": str}}
_cache: dict[int, dict] = {}

CACHE_TTL = 600  # 10 minutes


def _chat_settings(chat_id: int) -> dict:
    """Return or initialise the settings dict for a chat."""
    if chat_id not in _cache:
        _cache[chat_id] = {
            "admins": {},
            "updated": 0,
            "anonadmin": True,
            "adminerror": True,
            "lang": "en",
        }
    return _cache[chat_id]


def set_chat_lang(chat_id: int, lang: str) -> None:
    """Set the language for a group chat (used by gateway flow)."""
    _chat_settings(chat_id)["lang"] = lang


def get_chat_lang(chat_id: int) -> str:
    """Get the language for a group chat."""
    return _chat_settings(chat_id).get("lang", "en")


async def _refresh_cache(chat_id: int, bot) -> dict[int, ChatMember]:
    """Fetch admin list from Telegram and update cache."""
    settings = _chat_settings(chat_id)
    try:
        members = await bot.get_chat_administrators(chat_id)
        settings["admins"] = {m.user.id: m for m in members}
        settings["updated"] = time.time()
    except (BadRequest, Forbidden) as exc:
        logger.warning("Could not fetch admins for %s: %s", chat_id, exc)
    return settings["admins"]


async def get_admins(chat_id: int, bot) -> dict[int, ChatMember]:
    """Return cached admins, refreshing if stale."""
    settings = _chat_settings(chat_id)
    if time.time() - settings["updated"] > CACHE_TTL:
        return await _refresh_cache(chat_id, bot)
    return settings["admins"]


async def is_admin(chat_id: int, user_id: int, bot) -> bool:
    """Check if a user is an admin (or owner) in the given chat."""
    admins = await get_admins(chat_id, bot)
    return user_id in admins


# ─── Decorator: admin-only commands ─────────────────────────────────────────

def admin_only(func):
    """Decorator that restricts a handler to chat admins only."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat = update.effective_chat
        user = update.effective_user

        # Only applies to groups
        if chat.type not in ("group", "supergroup"):
            return await func(update, context)

        settings = _chat_settings(chat.id)
        lang = settings.get("lang", "en")

        # Anonymous admin (GroupAnonymousBot)
        if user.id == 1087968824:  # Telegram's GroupAnonymousBot
            if settings.get("anonadmin", False):
                return await func(update, context)
            if settings.get("adminerror", True):
                await update.message.reply_text(t(lang, "not_admin"))
            return

        if not await is_admin(chat.id, user.id, context.bot):
            if settings.get("adminerror", True):
                await update.message.reply_text(t(lang, "not_admin"))
            return

        return await func(update, context)

    return wrapper


# ─── Helper: resolve target user from reply / args ──────────────────────────

async def _resolve_target(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> Optional[tuple[int, str]]:
    """Extract (user_id, display_name) from a reply or command argument.

    Returns None if no target can be resolved.
    """
    msg = update.message

    # Priority 1: reply to a message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        user = msg.reply_to_message.from_user
        return user.id, user.full_name

    # Priority 2: command argument
    if not context.args:
        return None

    arg = context.args[0].lstrip("@")

    # Try as numeric user ID
    try:
        user_id = int(arg)
        try:
            member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
            return user_id, member.user.full_name
        except BadRequest:
            return user_id, str(user_id)
    except ValueError:
        pass

    # Try as username
    # Telegram Bot API doesn't allow fetching user by username directly,
    # so we search cached admins first
    admins = await get_admins(update.effective_chat.id, context.bot)
    for uid, member in admins.items():
        if member.user.username and member.user.username.lower() == arg.lower():
            return uid, member.user.full_name

    return None


# ─── Handlers ────────────────────────────────────────────────────────────────

@admin_only
async def promote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/promote — promote a user to admin."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "promote_usage"))
        return

    user_id, name = target

    # Don't promote the bot itself
    bot_id = (await context.bot.get_me()).id
    if user_id == bot_id:
        await update.message.reply_text(t(lang, "cannot_target_self"))
        return

    try:
        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=user_id,
            can_manage_chat=True,
            can_delete_messages=True,
            can_restrict_members=True,
            can_invite_users=True,
            can_pin_messages=True,
            can_manage_video_chats=True,
        )
        await update.message.reply_text(t(lang, "promote_success", user=name))
        # Refresh cache to include new admin
        await _refresh_cache(chat.id, context.bot)
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(
            t(lang, "promote_fail", user=name, err=str(exc))
        )


@admin_only
async def demote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/demote — demote a user from admin."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "demote_usage"))
        return

    user_id, name = target

    bot_id = (await context.bot.get_me()).id
    if user_id == bot_id:
        await update.message.reply_text(t(lang, "cannot_target_self"))
        return

    try:
        await context.bot.promote_chat_member(
            chat_id=chat.id,
            user_id=user_id,
            can_manage_chat=False,
            can_delete_messages=False,
            can_restrict_members=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_manage_video_chats=False,
        )
        await update.message.reply_text(t(lang, "demote_success", user=name))
        await _refresh_cache(chat.id, context.bot)
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(
            t(lang, "demote_fail", user=name, err=str(exc))
        )


@admin_only
async def adminlist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/adminlist — list all admins in the chat."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    admins = await get_admins(chat.id, context.bot)
    if not admins:
        await update.message.reply_text(t(lang, "adminlist_empty"))
        return

    text = t(lang, "adminlist_title", chat=chat.title or str(chat.id))
    for member in admins.values():
        name = member.user.full_name
        if isinstance(member, ChatMemberOwner):
            text += t(lang, "adminlist_creator", name=name)
        else:
            text += t(lang, "adminlist_admin", name=name)

    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def admincache_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admincache — force-refresh the admin cache."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    await _refresh_cache(chat.id, context.bot)
    await update.message.reply_text(t(lang, "admincache_done"))


@admin_only
async def anonadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/anonadmin <yes/no/on/off> — toggle anonymous admin mode."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "anonadmin_usage"))
        return

    val = context.args[0].lower()
    if val in ("yes", "on"):
        _chat_settings(chat.id)["anonadmin"] = True
        await update.message.reply_text(
            t(lang, "anonadmin_set", val="ON"), parse_mode="Markdown"
        )
    elif val in ("no", "off"):
        _chat_settings(chat.id)["anonadmin"] = False
        await update.message.reply_text(
            t(lang, "anonadmin_set", val="OFF"), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(t(lang, "anonadmin_usage"))


@admin_only
async def adminerror_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/adminerror <yes/no/on/off> — toggle error messages for non-admins."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "adminerror_usage"))
        return

    val = context.args[0].lower()
    if val in ("yes", "on"):
        _chat_settings(chat.id)["adminerror"] = True
        await update.message.reply_text(
            t(lang, "adminerror_set", val="ON"), parse_mode="Markdown"
        )
    elif val in ("no", "off"):
        _chat_settings(chat.id)["adminerror"] = False
        await update.message.reply_text(
            t(lang, "adminerror_set", val="OFF"), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(t(lang, "adminerror_usage"))
