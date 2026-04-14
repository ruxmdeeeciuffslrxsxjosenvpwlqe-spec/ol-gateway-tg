"""
captcha.py — CAPTCHA verification: new members must tap a button to verify.
Also sends the combined welcome + verify message.
"""

import logging
import time
from datetime import datetime, timezone

from telegram import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from admin import get_chat_lang
from strings import t
from welcome import _record_user

logger = logging.getLogger(__name__)

# Track pending verifications: {(chat_id, user_id): message_id}
_pending_verify: dict[tuple[int, int], int] = {}

# Prevent duplicate welcome messages: {(chat_id, user_id): timestamp}
_recently_welcomed: dict[tuple[int, int], float] = {}

_RESTRICTED = ChatPermissions(
    can_send_messages=False,
    can_send_polls=False,
    can_send_other_messages=False,
    can_add_web_page_previews=False,
    can_invite_users=False,
)

_UNRESTRICTED = ChatPermissions(
    can_send_messages=True,
    can_send_polls=True,
    can_send_other_messages=True,
    can_add_web_page_previews=True,
    can_invite_users=True,
)


def _build_welcome_text(chat, user, count, lang):
    """Build the combined welcome + captcha prompt text."""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%d/%m/%Y %H:%M:%S")
    full_name = user.first_name or ""
    if user.last_name:
        full_name += f" {user.last_name}"
    username_str = f"@{user.username}" if user.username else "N/A"

    return (
        f"🔥 Hello! Welcome to\n"
        f"⚜️ {chat.title} ⚜️\n\n"
        f"💀 Your information:\n\n"
        f"👹 Name: `{full_name}`\n"
        f"🔱 ID: `{user.id}`\n"
        f"👺 Username: {username_str}\n"
        f"📢 `{full_name}`\n"
        f"📜 Date and time joined:\n"
        f"🦇 {date_str}\n\n"
        f"😈 Today we are: *{count}* members.\n\n"
        f"⛓️💥 I hope you enjoy your time in the group.\n\n"
        f"👁️ _Always use the /staff command to verify that the admins are the real ones._"
    )


async def restrict_and_welcome(chat, user, context, lang):
    """Restrict a new user and send the combined welcome + verify message.
    Called from both on_new_member (NEW_CHAT_MEMBERS) and on_member_joined (ChatMemberUpdated).
    """
    # Prevent duplicate welcome messages (5-second window)
    key = (chat.id, user.id)
    now = time.time()
    if key in _recently_welcomed and now - _recently_welcomed[key] < 5:
        return
    _recently_welcomed[key] = now

    # Restrict immediately
    try:
        await context.bot.restrict_chat_member(
            chat.id, user.id, permissions=_RESTRICTED
        )
    except (BadRequest, Forbidden) as exc:
        logger.warning("Could not restrict %s in %s: %s", user.id, chat.id, exc)

    # Record user data
    rec = _record_user(chat.id, user)
    rec["join_date"] = datetime.now(timezone.utc)

    # Get member count
    try:
        count = await context.bot.get_chat_member_count(chat.id)
    except (BadRequest, Forbidden):
        count = "?"

    # Build combined message
    welcome_text = _build_welcome_text(chat, user, count, lang)

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t(lang, "captcha_button"),
            callback_data=f"captcha_{user.id}",
        )]
    ])

    try:
        msg = await context.bot.send_message(
            chat.id,
            welcome_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        _pending_verify[(chat.id, user.id)] = msg.message_id
    except (BadRequest, Forbidden) as exc:
        logger.warning("Could not send welcome+captcha in %s: %s", chat.id, exc)


async def on_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """NEW_CHAT_MEMBERS handler — restrict new members and show welcome + verify button."""
    if not update.message or not update.message.new_chat_members:
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return

    lang = get_chat_lang(chat.id)

    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        await restrict_and_welcome(chat, member, context, lang)


async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the verification button press."""
    query = update.callback_query

    # Extract the target user_id from callback_data
    try:
        target_user_id = int(query.data.split("_")[1])
    except (IndexError, ValueError):
        await query.answer()
        return

    # Only the actual user can verify themselves
    if query.from_user.id != target_user_id:
        await query.answer(t(get_chat_lang(query.message.chat.id), "captcha_not_you"), show_alert=True)
        return

    chat_id = query.message.chat.id
    lang = get_chat_lang(chat_id)

    # Answer the callback query FIRST — before any message edits/deletes —
    # to avoid Telegram rejecting the answer after the message is gone.
    await query.answer(t(lang, "captcha_verified"))

    # Unrestrict the user
    try:
        await context.bot.restrict_chat_member(
            chat_id, target_user_id, permissions=_UNRESTRICTED
        )
    except (BadRequest, Forbidden) as exc:
        logger.warning("Could not unrestrict %s in %s: %s", target_user_id, chat_id, exc)

    # Delete the verification message
    try:
        await query.message.delete()
    except (BadRequest, Forbidden):
        pass

    _pending_verify.pop((chat_id, target_user_id), None)
    logger.info("User %s verified in chat %s", target_user_id, chat_id)
