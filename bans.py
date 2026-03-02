"""
bans.py — Ban, mute, kick commands with silent/delete/temp variants.
"""

import logging

from datetime import timedelta

from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from admin import admin_only, get_chat_lang, _resolve_target, is_admin
from antiflood import parse_duration, format_duration
from strings import t

logger = logging.getLogger(__name__)

# Ban reason storage: {(chat_id, user_id): reason}
_ban_reasons: dict[tuple[int, int], str] = {}


def record_ban_reason(chat_id: int, user_id: int, reason: str) -> None:
    _ban_reasons[(chat_id, user_id)] = reason


def get_ban_reason(chat_id: int, user_id: int) -> str | None:
    return _ban_reasons.get((chat_id, user_id))


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def _get_target_and_duration(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> tuple | None:
    """Resolve target user and optional duration from command args.

    Returns (user_id, display_name, duration_seconds_or_0) or None.
    """
    lang = get_chat_lang(update.effective_chat.id)
    target = await _resolve_target(update, context)
    if not target:
        return None

    user_id, name = target

    # Check if bot is targeting itself
    bot_id = (await context.bot.get_me()).id
    if user_id == bot_id:
        await update.message.reply_text(t(lang, "cannot_target_self"))
        return None

    # Parse optional duration from remaining args
    dur = 0
    # If target was resolved from reply, args[0] could be duration
    # If target was resolved from args[0], args[1] could be duration
    remaining_args = context.args or []
    if update.message.reply_to_message and remaining_args:
        parsed = parse_duration(remaining_args[0])
        if parsed:
            dur = parsed
    elif len(remaining_args) >= 2:
        parsed = parse_duration(remaining_args[1])
        if parsed:
            dur = parsed

    return user_id, name, dur


# ─── Ban commands ────────────────────────────────────────────────────────────

@admin_only
async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/ban - ban a user. Usage: /ban [reason] (reply) or /ban @user [reason]"""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    result = await _get_target_and_duration(update, context)
    if not result:
        await update.message.reply_text(t(lang, "ban_usage"))
        return

    user_id, name, _ = result

    # Extract reason from remaining args
    args = context.args or []
    reason = "No reason provided"
    if update.message.reply_to_message:
        # /ban reason text (reply to message)
        if args:
            reason = " ".join(args)
    else:
        # /ban @user reason text
        if len(args) >= 2:
            reason = " ".join(args[1:])

    try:
        await context.bot.ban_chat_member(chat.id, user_id)
        record_ban_reason(chat.id, user_id, reason)
        ban_text = (
            f"🚫 {name} — `{user_id}` has been banned.\n"
            f"• Reason: {reason}"
        )
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Unban", callback_data=f"unban_{user_id}")]
        ])
        await update.message.reply_text(ban_text, reply_markup=buttons, parse_mode="Markdown")
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "ban_fail", user=name, err=str(exc)))


@admin_only
async def dban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/dban — ban a user by reply and delete their message."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    if not update.message.reply_to_message:
        await update.message.reply_text(t(lang, "dban_usage"))
        return

    result = await _get_target_and_duration(update, context)
    if not result:
        return

    user_id, name, _ = result
    try:
        await context.bot.ban_chat_member(chat.id, user_id)
        await update.message.reply_to_message.delete()
        await update.message.reply_text(
            t(lang, "ban_done", user=name), parse_mode="Markdown"
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "ban_fail", user=name, err=str(exc)))


@admin_only
async def sban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/sban — silently ban a user and delete command message."""
    chat = update.effective_chat
    result = await _get_target_and_duration(update, context)
    if not result:
        return

    user_id, name, _ = result
    try:
        await context.bot.ban_chat_member(chat.id, user_id)
        await update.message.delete()
    except (BadRequest, Forbidden) as exc:
        logger.warning("Silent ban failed for %s in %s: %s", user_id, chat.id, exc)


@admin_only
async def tban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tban <user> <duration> — temporarily ban a user."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    result = await _get_target_and_duration(update, context)
    if not result:
        await update.message.reply_text(t(lang, "tban_usage"))
        return

    user_id, name, dur = result
    if dur <= 0:
        await update.message.reply_text(t(lang, "tban_usage"))
        return

    try:
        await context.bot.ban_chat_member(
            chat.id, user_id, until_date=timedelta(seconds=dur)
        )
        await update.message.reply_text(
            t(lang, "tban_done", user=name, dur=format_duration(dur)),
            parse_mode="Markdown",
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "ban_fail", user=name, err=str(exc)))


@admin_only
async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unban — unban a user."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "unban_usage"))
        return

    user_id, name = target
    try:
        await context.bot.unban_chat_member(chat.id, user_id, only_if_banned=True)
        await update.message.reply_text(
            t(lang, "unban_done", user=name), parse_mode="Markdown"
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "unban_fail", user=name, err=str(exc)))


# ─── Mute commands ───────────────────────────────────────────────────────────

_MUTE_PERMS = ChatPermissions(can_send_messages=False)
_UNMUTE_PERMS = ChatPermissions(
    can_send_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)


@admin_only
async def mute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/mute — mute a user."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    result = await _get_target_and_duration(update, context)
    if not result:
        await update.message.reply_text(t(lang, "mute_usage"))
        return

    user_id, name, _ = result
    try:
        await context.bot.restrict_chat_member(chat.id, user_id, permissions=_MUTE_PERMS)
        await update.message.reply_text(
            t(lang, "mute_done", user=name), parse_mode="Markdown"
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "mute_fail", user=name, err=str(exc)))


@admin_only
async def dmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/dmute — mute by reply and delete their message."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    if not update.message.reply_to_message:
        await update.message.reply_text(t(lang, "dmute_usage"))
        return

    result = await _get_target_and_duration(update, context)
    if not result:
        return

    user_id, name, _ = result
    try:
        await context.bot.restrict_chat_member(chat.id, user_id, permissions=_MUTE_PERMS)
        await update.message.reply_to_message.delete()
        await update.message.reply_text(
            t(lang, "mute_done", user=name), parse_mode="Markdown"
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "mute_fail", user=name, err=str(exc)))


@admin_only
async def smute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/smute — silently mute a user and delete command message."""
    chat = update.effective_chat
    result = await _get_target_and_duration(update, context)
    if not result:
        return

    user_id, name, _ = result
    try:
        await context.bot.restrict_chat_member(chat.id, user_id, permissions=_MUTE_PERMS)
        await update.message.delete()
    except (BadRequest, Forbidden) as exc:
        logger.warning("Silent mute failed for %s in %s: %s", user_id, chat.id, exc)


@admin_only
async def tmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tmute <user> <duration> — temporarily mute a user."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    result = await _get_target_and_duration(update, context)
    if not result:
        await update.message.reply_text(t(lang, "tmute_usage"))
        return

    user_id, name, dur = result
    if dur <= 0:
        await update.message.reply_text(t(lang, "tmute_usage"))
        return

    try:
        await context.bot.restrict_chat_member(
            chat.id, user_id,
            permissions=_MUTE_PERMS,
            until_date=timedelta(seconds=dur),
        )
        await update.message.reply_text(
            t(lang, "tmute_done", user=name, dur=format_duration(dur)),
            parse_mode="Markdown",
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "mute_fail", user=name, err=str(exc)))


@admin_only
async def unmute_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unmute — unmute a user."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "unmute_usage"))
        return

    user_id, name = target
    try:
        await context.bot.restrict_chat_member(
            chat.id, user_id, permissions=_UNMUTE_PERMS
        )
        await update.message.reply_text(
            t(lang, "unmute_done", user=name), parse_mode="Markdown"
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "unmute_fail", user=name, err=str(exc)))


# ─── Kick commands ───────────────────────────────────────────────────────────

@admin_only
async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/kick — kick a user (ban + immediate unban)."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    result = await _get_target_and_duration(update, context)
    if not result:
        await update.message.reply_text(t(lang, "kick_usage"))
        return

    user_id, name, _ = result
    try:
        await context.bot.ban_chat_member(chat.id, user_id)
        await context.bot.unban_chat_member(chat.id, user_id)
        await update.message.reply_text(
            t(lang, "kick_done", user=name), parse_mode="Markdown"
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "kick_fail", user=name, err=str(exc)))


@admin_only
async def dkick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/dkick — kick by reply and delete their message."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    if not update.message.reply_to_message:
        await update.message.reply_text(t(lang, "dkick_usage"))
        return

    result = await _get_target_and_duration(update, context)
    if not result:
        return

    user_id, name, _ = result
    try:
        await context.bot.ban_chat_member(chat.id, user_id)
        await context.bot.unban_chat_member(chat.id, user_id)
        await update.message.reply_to_message.delete()
        await update.message.reply_text(
            t(lang, "kick_done", user=name), parse_mode="Markdown"
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "kick_fail", user=name, err=str(exc)))


@admin_only
async def skick_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/skick — silently kick a user and delete command message."""
    chat = update.effective_chat
    result = await _get_target_and_duration(update, context)
    if not result:
        return

    user_id, name, _ = result
    try:
        await context.bot.ban_chat_member(chat.id, user_id)
        await context.bot.unban_chat_member(chat.id, user_id)
        await update.message.delete()
    except (BadRequest, Forbidden) as exc:
        logger.warning("Silent kick failed for %s in %s: %s", user_id, chat.id, exc)


# ─── User command ────────────────────────────────────────────────────────────

async def kickme_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/kickme — user kicks themselves from the chat."""
    chat = update.effective_chat
    user = update.effective_user
    lang = get_chat_lang(chat.id)

    if chat.type not in ("group", "supergroup"):
        return

    try:
        await context.bot.ban_chat_member(chat.id, user.id)
        await context.bot.unban_chat_member(chat.id, user.id)
        await update.message.reply_text(
            t(lang, "kickme_done", user=user.full_name), parse_mode="Markdown"
        )
    except (BadRequest, Forbidden) as exc:
        await update.message.reply_text(t(lang, "kickme_fail", err=str(exc)))


async def unban_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the Unban button from /ban responses."""
    query = update.callback_query
    chat_id = query.message.chat.id

    if not await is_admin(chat_id, query.from_user.id, context.bot):
        await query.answer("\u26d4 Admin only.", show_alert=True)
        return

    try:
        target_uid = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer()
        return

    try:
        await context.bot.unban_chat_member(chat_id, target_uid, only_if_banned=True)
        _ban_reasons.pop((chat_id, target_uid), None)
        await query.answer("\u2705 User unbanned.", show_alert=True)
    except (BadRequest, Forbidden) as exc:
        await query.answer(f"Error: {exc}", show_alert=True)
