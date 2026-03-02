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
import time
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
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

GROUP_IDS: list[int] = [
    int(gid.strip()) for gid in os.environ["GROUP_IDS"].split(",")
]

_raw_names = os.environ.get("GROUP_NAMES", "")
GROUP_NAMES: list[str] = (
    [n.strip() for n in _raw_names.split(",")]
    if _raw_names
    else [str(gid) for gid in GROUP_IDS]
)

# ─── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── State ───────────────────────────────────────────────────────────────────
pending: dict[int, dict] = {}

# Track users who completed the math captcha: {user_id: timestamp}
verified_users: dict[int, float] = {}

# Track bot messages in private chats for cleanup: {user_id: [message_ids]}
_dm_messages: dict[int, list[int]] = {}

# Pending join requests: {(chat_id, user_id): timestamp}
_pending_requests: dict[tuple[int, int], float] = {}
PENDING_APPROVAL_TIMEOUT = 36 * 3600  # 36 hours in seconds


# ─── Utilities ───────────────────────────────────────────────────────────────

def generate_math_problem() -> tuple[str, int]:
    a = random.randint(1, 50)
    b = random.randint(1, 50)
    if random.choice(["+", "-"]) == "+":
        return f"{a} + {b}", a + b
    a, b = max(a, b), min(a, b)
    return f"{a} - {b}", a - b


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

    # ── Gateway (DM) ─────────────────────────────────────────────────────
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(
        CallbackQueryHandler(language_callback, pattern=r"^lang_(en|es)$")
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handle_answer,
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

    logger.info("Bot started — waiting for messages...")

    # Detect Render environment for webhook mode
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")
    PORT = int(os.environ.get("PORT", "10000"))

    if RENDER_URL:
        # Webhook mode for Render free tier
        webhook_url = f"{RENDER_URL}/webhook"
        logger.info(f"Running in WEBHOOK mode on port {PORT} → {webhook_url}")
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
    else:
        # Polling mode for local development
        logger.info("Running in POLLING mode (local)")
        application.run_polling(
            allowed_updates=[
                "message", "edited_message", "channel_post", "edited_channel_post",
                "inline_query", "chosen_inline_result", "callback_query",
                "shipping_query", "pre_checkout_query", "poll", "poll_answer",
                "my_chat_member", "chat_member", "chat_join_request",
            ]
        )


if __name__ == "__main__":
    main()
