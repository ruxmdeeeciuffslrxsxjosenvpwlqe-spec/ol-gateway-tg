"""
strings.py — All bot strings in English and Spanish.
"""

STRINGS = {
    "en": {
        # ── Gateway (DM flow) ────────────────────────────────────────────
        "choose_lang": "🌐 Choose your language / Elige tu idioma:",
        "math_prompt": (
            "🔢 To get your invite links, "
            "solve this math problem:\n\n"
            "What is *{q}*?\n\n"
            "Tap the correct answer below:"
        ),
        "correct": "✅ Well done! That’s correct! 🎉 I’m now generating your invite links... 🚀",
        "incorrect": "❌ Incorrect answer.\nUse /start to try again with a new problem.",
        "not_a_number": "❌ Please tap one of the answer buttons below the math question.",
        "no_pending": "⚠️ You don't have a pending problem.\nUse /start to begin.",
        "links_message": (
            "🔗 Here are your invite links (valid for the next 60 seconds):\n"
            "Tap the buttons below to join the rooms. 👇\n"
            "If they expire, no worries! Just type /start again to get new buttons. ⏰"
        ),
        "no_links": "⚠️ Could not generate links at this time.\nContact an administrator.",

        # ── Admin ────────────────────────────────────────────────────────
        "not_admin": "⛔ You don't have permission to use this command.",
        "cannot_target_self": "❌ I can't do that to myself.",
        "promote_usage": "Usage: reply to a user, or /promote <username/user_id>",
        "promote_success": "✅ {user} has been promoted.",
        "promote_fail": "❌ Could not promote {user}: {err}",
        "demote_usage": "Usage: reply to a user, or /demote <username/user_id>",
        "demote_success": "✅ {user} has been demoted.",
        "demote_fail": "❌ Could not demote {user}: {err}",
        "adminlist_title": "👑 *Admins in {chat}:*\n",
        "adminlist_creator": "  • {name} (creator)\n",
        "adminlist_admin": "  • {name}\n",
        "adminlist_empty": "No admins found.",
        "admincache_done": "✅ Admin cache updated.",
        "anonadmin_usage": "Usage: /anonadmin <yes/no/on/off>",
        "anonadmin_set": "✅ Anonymous admin mode: *{val}*",
        "adminerror_usage": "Usage: /adminerror <yes/no/on/off>",
        "adminerror_set": "✅ Admin error messages: *{val}*",

        # ── Antiflood ────────────────────────────────────────────────────
        "flood_status_on": (
            "🌊 *Antiflood settings:*\n"
            "• Consecutive limit: *{limit}* messages\n"
            "• Action: *{action}*\n"
            "• Clear messages: *{clear}*"
        ),
        "flood_status_timed": "\n• Timed flood: *{count}* messages in *{duration}s*",
        "flood_status_off": "🌊 Antiflood is currently *disabled*.",
        "setflood_usage": "Usage: /setflood <number/off/no>",
        "setflood_set": "✅ Antiflood set to *{n}* consecutive messages.",
        "setflood_off": "✅ Antiflood has been *disabled*.",
        "setflood_invalid": "❌ Please provide a valid number greater than 0.",
        "setfloodtimer_usage": "Usage: /setfloodtimer <count> <duration>\nExample: /setfloodtimer 10 30s",
        "setfloodtimer_set": "✅ Timed antiflood set to *{count}* messages in *{dur}*.",
        "setfloodtimer_off": "✅ Timed antiflood has been *disabled*.",
        "floodmode_usage": "Usage: /floodmode <ban/mute/kick/tban/tmute>\nFor tban/tmute: /floodmode tban 3d",
        "floodmode_set": "✅ Antiflood action set to *{mode}*.",
        "floodmode_invalid": "❌ Invalid action. Choose: ban, mute, kick, tban, tmute.",
        "clearflood_usage": "Usage: /clearflood <yes/no/on/off>",
        "clearflood_set": "✅ Clear flood messages: *{val}*",
        "flood_action_ban": "🚫 {user} has been *banned* for flooding.",
        "flood_action_mute": "🔇 {user} has been *muted* for flooding.",
        "flood_action_kick": "👢 {user} has been *kicked* for flooding.",
        "flood_action_tban": "🚫 {user} has been *temporarily banned* ({dur}) for flooding.",
        "flood_action_tmute": "🔇 {user} has been *temporarily muted* ({dur}) for flooding.",
        "flood_action_fail": "⚠️ Could not take action on {user}: {err}",

        # ── Antiraid ────────────────────────────────────────────────────
        "antiraid_on": "🛡️ Antiraid *enabled* for *{dur}*. All new joins will be temporarily banned.",
        "antiraid_off": "🛡️ Antiraid *disabled*.",
        "antiraid_usage": "Usage: /antiraid <time/off>\nExamples: /antiraid 3h, /antiraid off",
        "antiraid_auto_enabled": "🚨 *Auto-antiraid activated!* {threshold}+ joins/min detected. Active for *{dur}*.",
        "antiraid_expired": "🛡️ Antiraid has *expired* and is now disabled.",
        "raidtime_current": "🛡️ Antiraid duration: *{dur}*",
        "raidtime_set": "✅ Antiraid duration set to *{dur}*.",
        "raidtime_usage": "Usage: /raidtime <duration>\nExample: /raidtime 6h",
        "raidactiontime_current": "🛡️ Raid tempban duration: *{dur}*",
        "raidactiontime_set": "✅ Raid tempban duration set to *{dur}*.",
        "raidactiontime_usage": "Usage: /raidactiontime <duration>\nExample: /raidactiontime 1h",
        "autoantiraid_current": "🛡️ Auto-antiraid: triggers at *{n}* joins/min.",
        "autoantiraid_off": "🛡️ Auto-antiraid is *disabled*.",
        "autoantiraid_set": "✅ Auto-antiraid set to *{n}* joins/min.",
        "autoantiraid_disabled": "✅ Auto-antiraid *disabled*.",
        "autoantiraid_usage": "Usage: /autoantiraid <number/off>",

        # ── Approval ────────────────────────────────────────────────────
        "approval_yes": "✅ {user} is *approved* in this chat.",
        "approval_no": "❌ {user} is *not approved* in this chat.",
        "approve_usage": "Usage: reply to a user, or /approve <username/user_id>",
        "approve_done": "✅ {user} has been *approved*. Locks, blocklists, and antiflood won't apply to them.",
        "unapprove_usage": "Usage: reply to a user, or /unapprove <username/user_id>",
        "unapprove_done": "✅ {user} has been *unapproved*.",
        "approved_title": "✅ *Approved users in {chat}:*",
        "approved_empty": "No approved users in this chat.",
        "unapproveall_done": "✅ All approvals have been *cleared*.",

        # ── Bans ─────────────────────────────────────────────────────────
        "ban_usage": "Usage: reply to a user, or /ban <username/user_id>",
        "ban_done": "🚫 {user} has been *banned*.",
        "ban_fail": "❌ Could not ban {user}: {err}",
        "dban_usage": "Usage: reply to a message with /dban",
        "tban_usage": "Usage: /tban <user> <duration>\nExample: /tban @user 3h",
        "tban_done": "🚫 {user} has been *temporarily banned* for *{dur}*.",
        "unban_usage": "Usage: reply to a user, or /unban <username/user_id>",
        "unban_done": "✅ {user} has been *unbanned*.",
        "unban_fail": "❌ Could not unban {user}: {err}",
        "mute_usage": "Usage: reply to a user, or /mute <username/user_id>",
        "mute_done": "🔇 {user} has been *muted*.",
        "mute_fail": "❌ Could not mute {user}: {err}",
        "dmute_usage": "Usage: reply to a message with /dmute",
        "tmute_usage": "Usage: /tmute <user> <duration>\nExample: /tmute @user 2h",
        "tmute_done": "🔇 {user} has been *temporarily muted* for *{dur}*.",
        "unmute_usage": "Usage: reply to a user, or /unmute <username/user_id>",
        "unmute_done": "🔊 {user} has been *unmuted*.",
        "unmute_fail": "❌ Could not unmute {user}: {err}",
        "kick_usage": "Usage: reply to a user, or /kick <username/user_id>",
        "kick_done": "👢 {user} has been *kicked*.",
        "kick_fail": "❌ Could not kick {user}: {err}",
        "dkick_usage": "Usage: reply to a message with /dkick",
        "kickme_done": "👋 {user} has left the chat.",
        "kickme_fail": "❌ Could not kick you: {err}",

        # ── Blocklists ───────────────────────────────────────────────────
        "addblocklist_usage": 'Usage: /addblocklist <trigger> <reason>\nQuoted: /addblocklist "bad phrase" reason',
        "addblocklist_done": "✅ Added blocklist trigger: `{trigger}`",
        "rmblocklist_usage": "Usage: /rmblocklist <trigger>",
        "rmblocklist_done": "✅ Removed blocklist trigger: `{trigger}`",
        "rmblocklist_notfound": "❌ Trigger `{trigger}` not found.",
        "unblocklistall_done": "✅ All blocklist triggers have been *cleared*.",
        "blocklist_title": "🚫 *Blocklist for {chat}:*",
        "blocklist_empty": "No blocklist triggers set.",
        "blocklistmode_usage": "Usage: /blocklistmode <nothing/ban/mute/kick/warn/tban/tmute>",
        "blocklistmode_set": "✅ Blocklist action set to *{mode}*.",
        "blocklistmode_invalid": "❌ Invalid action. Choose: nothing, ban, mute, kick, warn, tban, tmute.",
        "blocklistdelete_usage": "Usage: /blocklistdelete <yes/no/on/off>",
        "blocklistdelete_set": "✅ Delete blocklisted messages: *{val}*",
        "setblocklistreason_usage": "Usage: /setblocklistreason <reason>",
        "setblocklistreason_done": "✅ Default blocklist reason set to: *{reason}*",
        "resetblocklistreason_done": "✅ Blocklist reason reset to default.",
        "bl_action_ban": "🚫 {user} has been *banned*. Reason: {reason}",
        "bl_action_mute": "🔇 {user} has been *muted*. Reason: {reason}",
        "bl_action_kick": "👢 {user} has been *kicked*. Reason: {reason}",
        "bl_action_tban": "🚫 {user} has been *temporarily banned* ({dur}). Reason: {reason}",
        "bl_action_tmute": "🔇 {user} has been *temporarily muted* ({dur}). Reason: {reason}",
        "bl_action_warn": "⚠️ {user} has been *warned*. Reason: {reason}",

        # ── CAPTCHA ──────────────────────────────────────────────────────
        "captcha_prompt": "🔒 {user}, please tap the button below to verify you are human.",
        "captcha_button": "✅ Verify",
        "captcha_verified": "✅ Verified!",
        "captcha_not_you": "This button is not for you.",

        # ── Federation ───────────────────────────────────────────────────
        "fedbanned_start": "🚫 You are unable to use this bot at this moment.",
        "newfed_usage": "Usage: /newfed <name>",
        "newfed_done": "✅ Federation *{name}* created!\nID: `{fed_id}`",
        "joinfed_usage": "Usage: /joinfed <fed_id>",
        "joinfed_done": "✅ This chat has joined federation *{name}*.",
        "leavefed_done": "✅ This chat has left federation *{name}*.",
        "fedban_usage": "Usage: reply to a user, or /fedban <username/user_id>",
        "fedban_done": "🚫 {user} has been *fedbanned* across *{count}* chats in *{fed}*.",
        "unfedban_usage": "Usage: reply to a user, or /unfedban <username/user_id>",
        "unfedban_done": "✅ {user} has been *unfedbanned* from *{fed}*.",
        "fedpromote_usage": "Usage: /fedpromote <user>",
        "fedpromote_done": "✅ {user} is now a federation admin.",
        "feddemote_usage": "Usage: /feddemote <user>",
        "feddemote_done": "✅ {user} is no longer a federation admin.",
        "fed_not_found": "❌ Federation not found.",
        "fed_not_joined": "❌ This chat is not in any federation.",
        "fed_not_admin": "⛔ You are not a federation admin.",
        "fed_owner_only": "⛔ Only the federation owner can do this.",
    },
    "es": {
        # ── Gateway (DM flow) ────────────────────────────────────────────
        "choose_lang": "🌐 Choose your language / Elige tu idioma:",
        "math_prompt": (
            "🔢 Para obtener tus enlaces de invitación, "
            "resuelve este problema matemático:\n\n"
            "¿Cuánto es *{q}*?\n\n"
            "Toca la respuesta correcta abajo:"
        ),
        "correct": "✅ ¡Bien hecho! ¡Eso es correcto! 🎉 Ahora estoy generando tus enlaces de invitación... 🚀",
        "incorrect": "❌ Respuesta incorrecta.\nUsa /start para intentar con un nuevo problema.",
        "not_a_number": "❌ Toca uno de los botones de respuesta debajo del problema matemático.",
        "no_pending": "⚠️ No tienes un problema pendiente.\nUsa /start para comenzar.",
        "links_message": (
            "🔗 Aquí están tus enlaces de invitación (válidos durante los próximos 60 segundos):\n"
            "Toca los botones de abajo para unirte a las salas. 👇\n"
            "Si expiran, ¡no pasa nada! Solo escribe /start para obtener nuevos botones. ⏰"
        ),
        "no_links": "⚠️ No se pudieron generar enlaces en este momento.\nContacta a un administrador.",

        # ── Admin ────────────────────────────────────────────────────────
        "not_admin": "⛔ No tienes permiso para usar este comando.",
        "cannot_target_self": "❌ No puedo hacer eso conmigo mismo.",
        "promote_usage": "Uso: responde a un usuario, o /promote <username/user_id>",
        "promote_success": "✅ {user} ha sido promovido.",
        "promote_fail": "❌ No se pudo promover a {user}: {err}",
        "demote_usage": "Uso: responde a un usuario, o /demote <username/user_id>",
        "demote_success": "✅ {user} ha sido degradado.",
        "demote_fail": "❌ No se pudo degradar a {user}: {err}",
        "adminlist_title": "👑 *Admins en {chat}:*\n",
        "adminlist_creator": "  • {name} (creador)\n",
        "adminlist_admin": "  • {name}\n",
        "adminlist_empty": "No se encontraron admins.",
        "admincache_done": "✅ Caché de admins actualizada.",
        "anonadmin_usage": "Uso: /anonadmin <yes/no/on/off>",
        "anonadmin_set": "✅ Modo admin anónimo: *{val}*",
        "adminerror_usage": "Uso: /adminerror <yes/no/on/off>",
        "adminerror_set": "✅ Mensajes de error para admins: *{val}*",

        # ── Antiflood ────────────────────────────────────────────────────
        "flood_status_on": (
            "🌊 *Configuración antiflood:*\n"
            "• Límite consecutivo: *{limit}* mensajes\n"
            "• Acción: *{action}*\n"
            "• Borrar mensajes: *{clear}*"
        ),
        "flood_status_timed": "\n• Flood por tiempo: *{count}* mensajes en *{duration}s*",
        "flood_status_off": "🌊 Antiflood está *desactivado*.",
        "setflood_usage": "Uso: /setflood <número/off/no>",
        "setflood_set": "✅ Antiflood configurado a *{n}* mensajes consecutivos.",
        "setflood_off": "✅ Antiflood ha sido *desactivado*.",
        "setflood_invalid": "❌ Proporciona un número válido mayor a 0.",
        "setfloodtimer_usage": "Uso: /setfloodtimer <cantidad> <duración>\nEjemplo: /setfloodtimer 10 30s",
        "setfloodtimer_set": "✅ Antiflood por tiempo: *{count}* mensajes en *{dur}*.",
        "setfloodtimer_off": "✅ Antiflood por tiempo ha sido *desactivado*.",
        "floodmode_usage": "Uso: /floodmode <ban/mute/kick/tban/tmute>\nPara tban/tmute: /floodmode tban 3d",
        "floodmode_set": "✅ Acción antiflood: *{mode}*.",
        "floodmode_invalid": "❌ Acción inválida. Opciones: ban, mute, kick, tban, tmute.",
        "clearflood_usage": "Uso: /clearflood <yes/no/on/off>",
        "clearflood_set": "✅ Borrar mensajes de flood: *{val}*",
        "flood_action_ban": "🚫 {user} ha sido *baneado* por flood.",
        "flood_action_mute": "🔇 {user} ha sido *silenciado* por flood.",
        "flood_action_kick": "👢 {user} ha sido *expulsado* por flood.",
        "flood_action_tban": "🚫 {user} ha sido *baneado temporalmente* ({dur}) por flood.",
        "flood_action_tmute": "🔇 {user} ha sido *silenciado temporalmente* ({dur}) por flood.",
        "flood_action_fail": "⚠️ No se pudo tomar acción contra {user}: {err}",

        # ── Antiraid ────────────────────────────────────────────────────
        "antiraid_on": "🛡️ Antiraid *activado* por *{dur}*. Todas las nuevas uniones serán baneadas temporalmente.",
        "antiraid_off": "🛡️ Antiraid *desactivado*.",
        "antiraid_usage": "Uso: /antiraid <tiempo/off>\nEjemplos: /antiraid 3h, /antiraid off",
        "antiraid_auto_enabled": "🚨 *¡Auto-antiraid activado!* {threshold}+ uniones/min detectadas. Activo por *{dur}*.",
        "antiraid_expired": "🛡️ Antiraid ha *expirado* y se ha desactivado.",
        "raidtime_current": "🛡️ Duración del antiraid: *{dur}*",
        "raidtime_set": "✅ Duración del antiraid: *{dur}*.",
        "raidtime_usage": "Uso: /raidtime <duración>\nEjemplo: /raidtime 6h",
        "raidactiontime_current": "🛡️ Duración del ban temporal por raid: *{dur}*",
        "raidactiontime_set": "✅ Duración del ban temporal por raid: *{dur}*.",
        "raidactiontime_usage": "Uso: /raidactiontime <duración>\nEjemplo: /raidactiontime 1h",
        "autoantiraid_current": "🛡️ Auto-antiraid: se activa a *{n}* uniones/min.",
        "autoantiraid_off": "🛡️ Auto-antiraid está *desactivado*.",
        "autoantiraid_set": "✅ Auto-antiraid configurado a *{n}* uniones/min.",
        "autoantiraid_disabled": "✅ Auto-antiraid *desactivado*.",
        "autoantiraid_usage": "Uso: /autoantiraid <número/off>",

        # ── Approval ────────────────────────────────────────────────────
        "approval_yes": "✅ {user} está *aprobado* en este chat.",
        "approval_no": "❌ {user} *no está aprobado* en este chat.",
        "approve_usage": "Uso: responde a un usuario, o /approve <username/user_id>",
        "approve_done": "✅ {user} ha sido *aprobado*. Bloqueos, listas negras y antiflood no aplicarán.",
        "unapprove_usage": "Uso: responde a un usuario, o /unapprove <username/user_id>",
        "unapprove_done": "✅ {user} ha sido *desaprobado*.",
        "approved_title": "✅ *Usuarios aprobados en {chat}:*",
        "approved_empty": "No hay usuarios aprobados en este chat.",
        "unapproveall_done": "✅ Todas las aprobaciones han sido *eliminadas*.",

        # ── Bans ─────────────────────────────────────────────────────────
        "ban_usage": "Uso: responde a un usuario, o /ban <username/user_id>",
        "ban_done": "🚫 {user} ha sido *baneado*.",
        "ban_fail": "❌ No se pudo banear a {user}: {err}",
        "dban_usage": "Uso: responde a un mensaje con /dban",
        "tban_usage": "Uso: /tban <usuario> <duración>\nEjemplo: /tban @user 3h",
        "tban_done": "🚫 {user} ha sido *baneado temporalmente* por *{dur}*.",
        "unban_usage": "Uso: responde a un usuario, o /unban <username/user_id>",
        "unban_done": "✅ {user} ha sido *desbaneado*.",
        "unban_fail": "❌ No se pudo desbanear a {user}: {err}",
        "mute_usage": "Uso: responde a un usuario, o /mute <username/user_id>",
        "mute_done": "🔇 {user} ha sido *silenciado*.",
        "mute_fail": "❌ No se pudo silenciar a {user}: {err}",
        "dmute_usage": "Uso: responde a un mensaje con /dmute",
        "tmute_usage": "Uso: /tmute <usuario> <duración>\nEjemplo: /tmute @user 2h",
        "tmute_done": "🔇 {user} ha sido *silenciado temporalmente* por *{dur}*.",
        "unmute_usage": "Uso: responde a un usuario, o /unmute <username/user_id>",
        "unmute_done": "🔊 {user} ha sido *desilenciado*.",
        "unmute_fail": "❌ No se pudo desilenciar a {user}: {err}",
        "kick_usage": "Uso: responde a un usuario, o /kick <username/user_id>",
        "kick_done": "👢 {user} ha sido *expulsado*.",
        "kick_fail": "❌ No se pudo expulsar a {user}: {err}",
        "dkick_usage": "Uso: responde a un mensaje con /dkick",
        "kickme_done": "👋 {user} ha abandonado el chat.",
        "kickme_fail": "❌ No se pudo expulsarte: {err}",

        # ── Blocklists ───────────────────────────────────────────────────
        "addblocklist_usage": 'Uso: /addblocklist <trigger> <razón>\nCon comillas: /addblocklist "frase mala" razón',
        "addblocklist_done": "✅ Trigger de lista negra añadido: `{trigger}`",
        "rmblocklist_usage": "Uso: /rmblocklist <trigger>",
        "rmblocklist_done": "✅ Trigger de lista negra eliminado: `{trigger}`",
        "rmblocklist_notfound": "❌ Trigger `{trigger}` no encontrado.",
        "unblocklistall_done": "✅ Todos los triggers de lista negra han sido *eliminados*.",
        "blocklist_title": "🚫 *Lista negra de {chat}:*",
        "blocklist_empty": "No hay triggers en la lista negra.",
        "blocklistmode_usage": "Uso: /blocklistmode <nothing/ban/mute/kick/warn/tban/tmute>",
        "blocklistmode_set": "✅ Acción de lista negra: *{mode}*.",
        "blocklistmode_invalid": "❌ Acción inválida. Opciones: nothing, ban, mute, kick, warn, tban, tmute.",
        "blocklistdelete_usage": "Uso: /blocklistdelete <yes/no/on/off>",
        "blocklistdelete_set": "✅ Borrar mensajes de lista negra: *{val}*",
        "setblocklistreason_usage": "Uso: /setblocklistreason <razón>",
        "setblocklistreason_done": "✅ Razón predeterminada de lista negra: *{reason}*",
        "resetblocklistreason_done": "✅ Razón de lista negra restablecida.",
        "bl_action_ban": "🚫 {user} ha sido *baneado*. Razón: {reason}",
        "bl_action_mute": "🔇 {user} ha sido *silenciado*. Razón: {reason}",
        "bl_action_kick": "👢 {user} ha sido *expulsado*. Razón: {reason}",
        "bl_action_tban": "🚫 {user} ha sido *baneado temporalmente* ({dur}). Razón: {reason}",
        "bl_action_tmute": "🔇 {user} ha sido *silenciado temporalmente* ({dur}). Razón: {reason}",
        "bl_action_warn": "⚠️ {user} ha sido *advertido*. Razón: {reason}",

        # ── CAPTCHA ──────────────────────────────────────────────────────
        "captcha_prompt": "🔒 {user}, toca el botón de abajo para verificar que eres humano.",
        "captcha_button": "✅ Verificar",
        "captcha_verified": "✅ ¡Verificado!",
        "captcha_not_you": "Este botón no es para ti.",

        # ── Federation ───────────────────────────────────────────────────
        "fedbanned_start": "🚫 No puedes usar este bot en este momento.",
        "newfed_usage": "Uso: /newfed <nombre>",
        "newfed_done": "✅ Federación *{name}* creada!\nID: `{fed_id}`",
        "joinfed_usage": "Uso: /joinfed <fed_id>",
        "joinfed_done": "✅ Este chat se ha unido a la federación *{name}*.",
        "leavefed_done": "✅ Este chat ha salido de la federación *{name}*.",
        "fedban_usage": "Uso: responde a un usuario, o /fedban <username/user_id>",
        "fedban_done": "🚫 {user} ha sido *fedbaneado* en *{count}* chats de *{fed}*.",
        "unfedban_usage": "Uso: responde a un usuario, o /unfedban <username/user_id>",
        "unfedban_done": "✅ {user} ha sido *desfedbaneado* de *{fed}*.",
        "fedpromote_usage": "Uso: /fedpromote <usuario>",
        "fedpromote_done": "✅ {user} ahora es admin de la federación.",
        "feddemote_usage": "Uso: /feddemote <usuario>",
        "feddemote_done": "✅ {user} ya no es admin de la federación.",
        "fed_not_found": "❌ Federación no encontrada.",
        "fed_not_joined": "❌ Este chat no pertenece a ninguna federación.",
        "fed_not_admin": "⛔ No eres admin de la federación.",
        "fed_owner_only": "⛔ Solo el dueño de la federación puede hacer esto.",
    },
}

DEFAULT_LANG = "en"


def t(lang: str, key: str, **kwargs) -> str:
    """Return a translated string for the given language and key."""
    strings = STRINGS.get(lang, STRINGS[DEFAULT_LANG])
    text = strings.get(key, STRINGS[DEFAULT_LANG].get(key, key))
    return text.format(**kwargs) if kwargs else text
