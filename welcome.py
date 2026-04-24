"""
welcome.py — Welcome messages, user tracking, and .info command.
"""

import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from admin import admin_only, get_chat_lang, is_admin
from strings import t

logger = logging.getLogger(__name__)

EST = timezone(timedelta(hours=-5), name="EST")

# ─── User data store ────────────────────────────────────────────────────────
# {chat_id: {user_id: {first_name, last_name, username, join_date, msg_count,
#                       last_msg_time, lang_code}}}
_users: dict[int, dict[int, dict]] = defaultdict(dict)


def get_user_data(chat_id: int, user_id: int) -> dict | None:
    """Get tracked data for a user in a chat."""
    return _users.get(chat_id, {}).get(user_id)


def get_all_users(chat_id: int) -> dict[int, dict]:
    """Get all tracked users for a chat."""
    return _users.get(chat_id, {})


def _record_user(chat_id: int, user) -> dict:
    """Create or update the user record. Returns the record."""
    if user.id not in _users[chat_id]:
        _users[chat_id][user.id] = {
            "first_name": user.first_name or "",
            "last_name": user.last_name or "",
            "username": user.username or "",
            "join_date": datetime.now(timezone.utc),
            "msg_count": 0,
            "last_msg_time": 0.0,
            "lang_code": user.language_code or "",
            "warns": 0,
        }
    else:
        # Update mutable fields
        rec = _users[chat_id][user.id]
        rec["first_name"] = user.first_name or rec["first_name"]
        rec["last_name"] = user.last_name or rec["last_name"]
        rec["username"] = user.username or rec["username"]
        if user.language_code:
            rec["lang_code"] = user.language_code

    return _users[chat_id][user.id]


# ─── Language code to display name ──────────────────────────────────────────

_LANG_NAMES = {
    "en": "English", "es": "Spanish", "pt": "Portuguese", "fr": "French",
    "de": "German", "it": "Italian", "ru": "Russian", "ar": "Arabic",
    "zh": "Chinese", "ja": "Japanese", "ko": "Korean", "hi": "Hindi",
    "tr": "Turkish", "nl": "Dutch", "pl": "Polish", "uk": "Ukrainian",
}


def _lang_display(code: str) -> str:
    if not code:
        return "Unknown"
    base = code.split("-")[0].lower()
    return _LANG_NAMES.get(base, code)


# ─── Welcome message on join ────────────────────────────────────────────────

async def send_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message for new members and record their data."""
    if not update.message or not update.message.new_chat_members:
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return

    for member in update.message.new_chat_members:
        if member.is_bot:
            continue

        # Record user
        rec = _record_user(chat.id, member)
        rec["join_date"] = datetime.now(timezone.utc)

        # Get member count
        try:
            count = await context.bot.get_chat_member_count(chat.id)
        except (BadRequest, Forbidden):
            count = "?"

        # Format date
        now = datetime.now(timezone.utc)
        date_str = now.strftime("%d/%m/%Y %H:%M:%S")

        # Build display name
        full_name = member.first_name or ""
        if member.last_name:
            full_name += f" {member.last_name}"

        username_str = f"@{member.username}" if member.username else "N/A"

        welcome_text = (
            f"🔥 Hello! Welcome to\n"
            f"⚜️{chat.title}⚜️\n\n"
            f"💀 Your information:\n\n"
            f"👹 Name: {full_name}\n"
            f"🔱 ID: {member.id}\n"
            f"👺 Username: {username_str}\n"
            f"📢 {full_name}\n"
            f"📜 Date and time joined:\n"
            f"🦇 {date_str}\n\n"
            f"😈 Today we are: {count} members.\n\n"
            f"⛓️💥 I hope you enjoy your time in the group.\n\n"
            f"👁️ Always use the /staff command to verify that the admins are the real ones."
        )

        try:
            await context.bot.send_message(chat.id, welcome_text)
        except (BadRequest, Forbidden) as exc:
            logger.warning("Could not send welcome in %s: %s", chat.id, exc)


# ─── Message tracker ────────────────────────────────────────────────────────

async def track_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Track message count, last message time, and detect identity changes."""
    if not update.effective_message or not update.effective_user:
        return
    if not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"):
        return

    user = update.effective_user
    chat_id = update.effective_chat.id

    # Build current full name
    current_name = user.first_name or ""
    if user.last_name:
        current_name += f" {user.last_name}"
    current_username = user.username or ""

    # Check if we already have data — detect changes
    existing = _users.get(chat_id, {}).get(user.id)
    if existing:
        old_name = existing.get("first_name", "")
        if existing.get("last_name"):
            old_name += f" {existing['last_name']}"
        old_username = existing.get("username", "")

        name_changed = old_name != current_name and old_name
        username_changed = old_username != current_username and old_username

        if name_changed or username_changed:
            # Build identity change alert
            user_link = f"[{current_name}](tg://user?id={user.id})"
            lines = [
                "🕵️‍♂️ *IDENTITY CHANGE DETECTED*",
                "━━━━━━━━━━━━━━━━",
                f"User {user_link} has modified their profile.\n",
            ]

            if name_changed:
                lines.append("🔄 *Name:*")
                lines.append(f"🔴 Before: {old_name}")
                lines.append(f"🟢 Now: {current_name}\n")

            if username_changed:
                old_uname_display = f"@{old_username}" if old_username else "N/A"
                new_uname_display = f"@{current_username}" if current_username else "N/A"
                lines.append("🔄 *Username:*")
                lines.append(f"🔴 Before: {old_uname_display}")
                lines.append(f"🟢 Now: {new_uname_display}\n")

            lines.append(f"🆔 ID: `{user.id}`")

            try:
                await context.bot.send_message(
                    chat_id,
                    "\n".join(lines),
                    parse_mode="Markdown",
                )
            except (BadRequest, Forbidden) as exc:
                logger.warning("Could not send identity change alert: %s", exc)

    rec = _record_user(chat_id, user)
    rec["msg_count"] = rec.get("msg_count", 0) + 1
    rec["last_msg_time"] = time.time()


# ─── /staff command ─────────────────────────────────────────────────────────

async def staff_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/staff — list admins (alias for adminlist, available to everyone)."""
    from admin import get_admins
    from telegram import ChatMemberOwner

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return

    lang = get_chat_lang(chat.id)
    admins = await get_admins(chat.id, context.bot)

    if not admins:
        await update.message.reply_text("No admins found.")
        return

    text = f"👑 *Staff — {chat.title}:*\n"
    for member in admins.values():
        name = member.user.full_name
        if isinstance(member, ChatMemberOwner):
            text += f"  • {name} 👑 (owner)\n"
        else:
            text += f"  • {name}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ─── .info command (text trigger) ───────────────────────────────────────────

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle '.info @username' or '.info user_id' as a text trigger."""
    if not update.effective_message or not update.effective_user:
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return

    msg = update.effective_message
    text = (msg.text or "").strip()

    # Only respond to messages starting with ".info"
    if not text.lower().startswith(".info"):
        return

    # Check if sender is admin (or anonymous admin)
    user_id = update.effective_user.id
    if user_id != 1087968824 and not await is_admin(chat.id, user_id, context.bot):
        return

    lang = get_chat_lang(chat.id)

    # Parse target
    parts = text.split(None, 1)
    target_user = None
    target_data = None

    if msg.reply_to_message and msg.reply_to_message.from_user:
        # Reply to a message
        target_user = msg.reply_to_message.from_user
        target_data = get_user_data(chat.id, target_user.id)
    elif len(parts) >= 2:
        arg = parts[1].strip().lstrip("@")

        # Try as user_id
        try:
            uid = int(arg)
            target_data = get_user_data(chat.id, uid)
            # Always try Telegram API for full user info
            try:
                member = await context.bot.get_chat_member(chat.id, uid)
                target_user = member.user
            except BadRequest:
                pass
        except ValueError:
            # Try as username — search tracked users first
            found = False
            for uid, data in get_all_users(chat.id).items():
                if data.get("username", "").lower() == arg.lower():
                    target_data = data
                    try:
                        member = await context.bot.get_chat_member(chat.id, uid)
                        target_user = member.user
                    except BadRequest:
                        pass
                    found = True
                    break

            # If not found in tracked users, try all group members via Telegram API
            if not found:
                # We can't search by username directly, but we can inform the user
                await msg.reply_text(
                    f"\u274c User @{arg} was not found in tracked data.\n"
                    "Try using their numeric ID instead."
                )
                return

    if not target_user and not target_data:
        await msg.reply_text("❌ No user was found with that ID or name.")
        return

    # Build info card
    if target_user:
        uid = target_user.id
        first_name = target_user.first_name or ""
        last_name = target_user.last_name or ""
        username = target_user.username or ""
    else:
        uid = 0
        first_name = target_data.get("first_name", "")
        last_name = target_data.get("last_name", "")
        username = target_data.get("username", "")

    # Merge with tracked data
    if not target_data:
        target_data = _record_user(chat.id, target_user) if target_user else {}

    # Determine role/label
    label = "Member"
    if target_user:
        try:
            cm = await context.bot.get_chat_member(chat.id, uid)
            if cm.status == "creator":
                label = "Owner"
            elif cm.status == "administrator":
                label = "Admin"
            elif cm.status == "restricted":
                label = "Member"
            elif cm.status in ("kicked", "left"):
                label = "Banned/Left"
        except BadRequest:
            pass

    warns = target_data.get("warns", 0)
    join_date = target_data.get("join_date")
    if join_date:
        if join_date.tzinfo is None:
            join_date = join_date.replace(tzinfo=timezone.utc)
        join_str = join_date.astimezone(EST).strftime("%d %b %Y, %I:%M %p EST")
    else:
        join_str = "Unknown"
    lang_code = target_data.get("lang_code", "")
    lang_display = _lang_display(lang_code)
    msg_count = target_data.get("msg_count", 0)

    last_msg_ts = target_data.get("last_msg_time", 0)
    if last_msg_ts > 0:
        last_msg_str = datetime.fromtimestamp(last_msg_ts, EST).strftime(
            "%b %d, %Y, %I:%M %p EST"
        )
    else:
        last_msg_str = "Never"

    username_display = f"@{username}" if username else "N/A"
    tag = f"#id{uid}"

    # Get ban reason if banned
    ban_reason_line = ""
    if label in ("Banned/Left",):
        from bans import get_ban_reason
        ban_reason = get_ban_reason(chat.id, uid)
        if ban_reason:
            ban_reason_line = f"\n\U0001f6ab Ban Reason: {ban_reason}"

    # Language flag based on actual language
    if lang_display.lower() in ("english", "en"):
        lang_flag = "\U0001f1fa\U0001f1f8"
    elif lang_display.lower() in ("spanish", "es", "espa\u00f1ol"):
        lang_flag = "\U0001f1ea\U0001f1f8"
    else:
        lang_flag = "\U0001f310"

    info_text = (
        f"\U0001f194 ID: `{uid}` {tag}\n"
        f"\U0001f471 Name: `{first_name}`\n"
        f"\U0001f46a Last Name: `{last_name or 'N/A'}`\n"
        f"\U0001f310 Username: {username_display}\n"
        f"\U0001f440 Label: {label}{ban_reason_line}\n"
        f"\u2757 Warnings: {warns}/3\n"
        f"\u2935\ufe0f Joined: {join_str}\n"
        f"{lang_flag} Language: {lang_display}\n"
        f"\U0001f4ac Messages: {msg_count}\n"
        f"\U0001f4ad Last Message:\n{last_msg_str}"
    )

    # Action buttons
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚠️ Warnings", callback_data=f"info_warn_{uid}", api_kwargs={"style": "primary"}),
            InlineKeyboardButton("🔇 Silence", callback_data=f"info_mute_{uid}", api_kwargs={"style": "danger"}),
        ],
        [
            InlineKeyboardButton("🚫 Ban", callback_data=f"info_ban_{uid}", api_kwargs={"style": "danger"}),
            InlineKeyboardButton("🔑 Permissions", callback_data=f"info_perms_{uid}", api_kwargs={"style": "primary"}),
        ],
    ])

    await msg.reply_text(info_text, reply_markup=buttons, parse_mode="Markdown")


async def info_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle quick action buttons from .info cards."""
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat.id
    user_id = query.from_user.id

    # Only admins can use these buttons
    if user_id != 1087968824 and not await is_admin(chat_id, user_id, context.bot):
        await query.answer("\u26d4 Admin only.", show_alert=True)
        return

    parts = query.data.split("_")
    if len(parts) < 3:
        return

    action = parts[1]  # warn, mute, ban, perms
    try:
        target_uid = int(parts[2])
    except ValueError:
        return

    lang = get_chat_lang(chat_id)

    try:
        if action == "warn":
            # Show warning history
            data = get_user_data(chat_id, target_uid)
            warn_list = (data or {}).get("warn_list", [])
            warns = len(warn_list)
            if warns == 0:
                await query.answer("✅ No warnings.", show_alert=True)
            else:
                lines = [f"⚠️ Warnings ({warns}/3):"]
                for i, w in enumerate(warn_list, 1):
                    lines.append(f"{i}. {w['reason']} ({w['date']})")
                await query.answer("\n".join(lines)[:200], show_alert=True)

        elif action == "mute":
            from telegram import ChatPermissions
            await context.bot.restrict_chat_member(
                chat_id, target_uid,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await query.answer("🔇 User muted.", show_alert=True)

        elif action == "ban":
            await context.bot.ban_chat_member(chat_id, target_uid)
            await query.answer("🚫 User banned.", show_alert=True)

        elif action == "perms":
            try:
                cm = await context.bot.get_chat_member(chat_id, target_uid)
                perms_text = (
                    f"🔑 Permissions for user {target_uid}:\n"
                    f"Status: {cm.status}\n"
                )
                if hasattr(cm, "can_send_messages"):
                    perms_text += f"Send messages: {cm.can_send_messages}\n"
                if hasattr(cm, "can_invite_users"):
                    perms_text += f"Invite users: {cm.can_invite_users}\n"
                if hasattr(cm, "can_pin_messages"):
                    perms_text += f"Pin messages: {cm.can_pin_messages}\n"
                await query.answer(perms_text[:200], show_alert=True)
            except BadRequest as exc:
                await query.answer(f"Error: {exc}", show_alert=True)

    except (BadRequest, Forbidden) as exc:
        await query.answer(f"Error: {exc}", show_alert=True)
