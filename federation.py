"""
federation.py — Federated bans across groups.
"""

import logging
import uuid
from collections import defaultdict

from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import ContextTypes

from admin import admin_only, get_chat_lang, _resolve_target
from strings import t

logger = logging.getLogger(__name__)

# ─── Federation data ────────────────────────────────────────────────────────
# {fed_id: {name, owner_id, admins: set[int], bans: set[int], chats: set[int]}}
_federations: dict[str, dict] = {}

# Reverse lookup: {chat_id: fed_id}
_chat_to_fed: dict[int, str] = {}


def is_fedbanned(user_id: int) -> bool:
    """Check if a user is banned in ANY federation."""
    for fed in _federations.values():
        if user_id in fed["bans"]:
            return True
    return False


def _get_fed_for_chat(chat_id: int) -> dict | None:
    """Get the federation the chat belongs to, or None."""
    fed_id = _chat_to_fed.get(chat_id)
    if fed_id and fed_id in _federations:
        return _federations[fed_id]
    return None


def _is_fed_admin(fed: dict, user_id: int) -> bool:
    """Check if user is fed owner or admin."""
    return user_id == fed["owner_id"] or user_id in fed["admins"]


# ─── Auto-ban on join if fedbanned ──────────────────────────────────────────

async def check_fedban_on_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ban users who join a federated chat if they are fedbanned."""
    if not update.message or not update.message.new_chat_members:
        return
    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        return

    fed = _get_fed_for_chat(chat.id)
    if not fed:
        return

    for member in update.message.new_chat_members:
        if member.id in fed["bans"]:
            try:
                await context.bot.ban_chat_member(chat.id, member.id)
                logger.info(
                    "Fedban: auto-banned %s (%s) in %s",
                    member.id, member.full_name, chat.id,
                )
            except (BadRequest, Forbidden) as exc:
                logger.warning("Fedban auto-ban failed: %s", exc)


# ─── Commands ────────────────────────────────────────────────────────────────

@admin_only
async def newfed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/newfed <name> — create a new federation."""
    chat = update.effective_chat
    user = update.effective_user
    lang = get_chat_lang(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "newfed_usage"))
        return

    name = " ".join(context.args)
    fed_id = str(uuid.uuid4())[:8]

    _federations[fed_id] = {
        "name": name,
        "owner_id": user.id,
        "admins": set(),
        "bans": set(),
        "chats": set(),
    }

    await update.message.reply_text(
        t(lang, "newfed_done", name=name, fed_id=fed_id), parse_mode="Markdown"
    )
    logger.info("Federation created: %s (%s) by user %s", name, fed_id, user.id)


@admin_only
async def joinfed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/joinfed <fed_id> — join current chat to a federation."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    if not context.args:
        await update.message.reply_text(t(lang, "joinfed_usage"))
        return

    fed_id = context.args[0]
    if fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_found"))
        return

    fed = _federations[fed_id]
    fed["chats"].add(chat.id)
    _chat_to_fed[chat.id] = fed_id

    await update.message.reply_text(
        t(lang, "joinfed_done", name=fed["name"]), parse_mode="Markdown"
    )


@admin_only
async def leavefed_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/leavefed — remove current chat from its federation."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    fed_id = _chat_to_fed.get(chat.id)
    if not fed_id or fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_joined"))
        return

    fed = _federations[fed_id]
    fed["chats"].discard(chat.id)
    del _chat_to_fed[chat.id]

    await update.message.reply_text(
        t(lang, "leavefed_done", name=fed["name"]), parse_mode="Markdown"
    )


@admin_only
async def fedban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fedban <user> — ban user across all federated chats."""
    chat = update.effective_chat
    user = update.effective_user
    lang = get_chat_lang(chat.id)

    fed_id = _chat_to_fed.get(chat.id)
    if not fed_id or fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_joined"))
        return

    fed = _federations[fed_id]
    if not _is_fed_admin(fed, user.id):
        await update.message.reply_text(t(lang, "fed_not_admin"))
        return

    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "fedban_usage"))
        return

    target_id, target_name = target
    fed["bans"].add(target_id)

    # Ban in all federated chats
    banned_count = 0
    for cid in fed["chats"]:
        try:
            await context.bot.ban_chat_member(cid, target_id)
            banned_count += 1
        except (BadRequest, Forbidden):
            pass

    await update.message.reply_text(
        t(lang, "fedban_done", user=target_name, count=banned_count, fed=fed["name"]),
        parse_mode="Markdown",
    )
    logger.info("Fedban: %s (%s) banned in %d chats", target_id, target_name, banned_count)


@admin_only
async def unfedban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unfedban <user> — unban from federation."""
    chat = update.effective_chat
    user = update.effective_user
    lang = get_chat_lang(chat.id)

    fed_id = _chat_to_fed.get(chat.id)
    if not fed_id or fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_joined"))
        return

    fed = _federations[fed_id]
    if not _is_fed_admin(fed, user.id):
        await update.message.reply_text(t(lang, "fed_not_admin"))
        return

    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "unfedban_usage"))
        return

    target_id, target_name = target
    fed["bans"].discard(target_id)

    # Unban in all federated chats
    for cid in fed["chats"]:
        try:
            await context.bot.unban_chat_member(cid, target_id, only_if_banned=True)
        except (BadRequest, Forbidden):
            pass

    await update.message.reply_text(
        t(lang, "unfedban_done", user=target_name, fed=fed["name"]),
        parse_mode="Markdown",
    )


@admin_only
async def fedadmins_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fedadmins — list federation admins."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    fed_id = _chat_to_fed.get(chat.id)
    if not fed_id or fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_joined"))
        return

    fed = _federations[fed_id]
    text = f"👑 *Federation: {fed['name']}*\n"
    text += f"  • Owner: `{fed['owner_id']}`\n"
    for admin_id in fed["admins"]:
        text += f"  • Admin: `{admin_id}`\n"
    if not fed["admins"]:
        text += "  No additional admins."

    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def fedpromote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fedpromote <user> — add federation admin."""
    chat = update.effective_chat
    user = update.effective_user
    lang = get_chat_lang(chat.id)

    fed_id = _chat_to_fed.get(chat.id)
    if not fed_id or fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_joined"))
        return

    fed = _federations[fed_id]
    if user.id != fed["owner_id"]:
        await update.message.reply_text(t(lang, "fed_owner_only"))
        return

    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "fedpromote_usage"))
        return

    target_id, target_name = target
    fed["admins"].add(target_id)
    await update.message.reply_text(
        t(lang, "fedpromote_done", user=target_name), parse_mode="Markdown"
    )


@admin_only
async def feddemote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/feddemote <user> — remove federation admin."""
    chat = update.effective_chat
    user = update.effective_user
    lang = get_chat_lang(chat.id)

    fed_id = _chat_to_fed.get(chat.id)
    if not fed_id or fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_joined"))
        return

    fed = _federations[fed_id]
    if user.id != fed["owner_id"]:
        await update.message.reply_text(t(lang, "fed_owner_only"))
        return

    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "feddemote_usage"))
        return

    target_id, target_name = target
    fed["admins"].discard(target_id)
    await update.message.reply_text(
        t(lang, "feddemote_done", user=target_name), parse_mode="Markdown"
    )


@admin_only
async def fedinfo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fedinfo — show federation info."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    fed_id = _chat_to_fed.get(chat.id)
    if not fed_id or fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_joined"))
        return

    fed = _federations[fed_id]
    text = (
        f"📋 *Federation Info*\n"
        f"• Name: {fed['name']}\n"
        f"• ID: `{fed_id}`\n"
        f"• Owner: `{fed['owner_id']}`\n"
        f"• Admins: {len(fed['admins'])}\n"
        f"• Chats: {len(fed['chats'])}\n"
        f"• Bans: {len(fed['bans'])}"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


@admin_only
async def fedchats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/fedchats — list chats in the federation."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    fed_id = _chat_to_fed.get(chat.id)
    if not fed_id or fed_id not in _federations:
        await update.message.reply_text(t(lang, "fed_not_joined"))
        return

    fed = _federations[fed_id]
    if not fed["chats"]:
        await update.message.reply_text("No chats in this federation.")
        return

    text = f"💬 *Chats in {fed['name']}:*\n"
    for cid in fed["chats"]:
        try:
            c = await context.bot.get_chat(cid)
            text += f"  • {c.title} (`{cid}`)\n"
        except (BadRequest, Forbidden):
            text += f"  • `{cid}` (unavailable)\n"

    await update.message.reply_text(text, parse_mode="Markdown")
