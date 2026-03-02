"""
approval.py — Approve/unapprove users to bypass locks, blocklists, and antiflood.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from admin import admin_only, get_chat_lang, _resolve_target
from strings import t

logger = logging.getLogger(__name__)

# ─── Per-chat approved users ────────────────────────────────────────────────
# {chat_id: {user_id: display_name}}
_approved: dict[int, dict[int, str]] = {}


def is_approved(chat_id: int, user_id: int) -> bool:
    """Check if a user is approved in a chat."""
    return user_id in _approved.get(chat_id, {})


def _get_approved(chat_id: int) -> dict[int, str]:
    """Return or initialise the approved set for a chat."""
    if chat_id not in _approved:
        _approved[chat_id] = {}
    return _approved[chat_id]


# ─── Handlers ────────────────────────────────────────────────────────────────

async def approval_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/approval — check a user's approval status (any user can use this)."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    target = await _resolve_target(update, context)
    if not target:
        # Check the sender themselves
        user = update.effective_user
        if is_approved(chat.id, user.id):
            await update.message.reply_text(
                t(lang, "approval_yes", user=user.full_name), parse_mode="Markdown"
            )
        else:
            await update.message.reply_text(
                t(lang, "approval_no", user=user.full_name), parse_mode="Markdown"
            )
        return

    user_id, name = target
    if is_approved(chat.id, user_id):
        await update.message.reply_text(
            t(lang, "approval_yes", user=name), parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            t(lang, "approval_no", user=name), parse_mode="Markdown"
        )


@admin_only
async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/approve — approve a user."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "approve_usage"))
        return

    user_id, name = target
    _get_approved(chat.id)[user_id] = name
    await update.message.reply_text(
        t(lang, "approve_done", user=name), parse_mode="Markdown"
    )
    logger.info("Approved user %s (%s) in chat %s", user_id, name, chat.id)


@admin_only
async def unapprove_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unapprove — unapprove a user."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    target = await _resolve_target(update, context)
    if not target:
        await update.message.reply_text(t(lang, "unapprove_usage"))
        return

    user_id, name = target
    approved = _get_approved(chat.id)
    if user_id in approved:
        del approved[user_id]

    await update.message.reply_text(
        t(lang, "unapprove_done", user=name), parse_mode="Markdown"
    )


@admin_only
async def approved_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/approved — list all approved users."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)
    approved = _get_approved(chat.id)

    if not approved:
        await update.message.reply_text(t(lang, "approved_empty"))
        return

    lines = [t(lang, "approved_title", chat=chat.title or str(chat.id))]
    for uid, name in approved.items():
        lines.append(f"  • {name} (`{uid}`)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@admin_only
async def unapproveall_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/unapproveall — unapprove ALL users (creator only)."""
    chat = update.effective_chat
    lang = get_chat_lang(chat.id)

    _approved[chat.id] = {}
    await update.message.reply_text(
        t(lang, "unapproveall_done"), parse_mode="Markdown"
    )
    logger.info("All approvals cleared in chat %s", chat.id)
