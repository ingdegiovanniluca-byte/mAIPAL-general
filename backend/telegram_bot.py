"""Telegram bot v2: LLM-driven intent classifier + per-chat conversation state.

Behavior:
- Every free text (and every transcribed voice note) is classified by an LLM into
  {action: info_upload|info_request|task_todo|journal, continuation: continue|new, confidence}.
- If continuation=='continue' AND the last chat activity is recent (<15 min) we reuse the
  active conv_id + action, appending to the same conversation on the backend.
- Otherwise a new conv_id is started with the freshly classified action.
- Every reply carries an inline keyboard with:
    row1: [🔄 Nuova conversazione]  [✅ Termina]
    row2: [💾 Salva] [🔍 Cerca] [📝 Task] [📔 Diario]  — quick override
- /end command closes the active thread. /commands still work for explicit action.
"""
import os
import asyncio
import json as _json
import logging
import re as _re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from llm_integrations import LlmChat, UserMessage, OpenAISpeechToText
import usage_tracking as ut

logger = logging.getLogger(__name__)

_application = None
_polling_task = None

CONTEXT_TIMEOUT_MIN = 15  # after this many minutes, "continue" intent is ignored and a new conv is started
ACTIONS_LABEL = {"info_upload": "💾 Salvato", "info_request": "🔍 Risposta", "task_todo": "✅ Task/To-Do", "journal": "📔 Diario"}
ACTION_ITA = {"info_upload": "salva", "info_request": "chiedi", "task_todo": "task", "journal": "diario"}

# Usage tracking (see usage_tracking.py): maps a resolved Telegram action to its catalog
# feature (§4 of the usage-tracking spec) - same idea as server.py's _ACTION_TO_FEATURE,
# plus list_update, which only the Telegram classifier resolves directly (the web app's
# "Modifica liste" engine is reached through a different endpoint, not the chat action).
_TG_ACTION_TO_FEATURE = {
    "info_request": "ricerca_informazioni",
    "info_upload": "caricamento_informazioni",
    "task_todo": "creazione_task",
    "journal": "diario",
    "list_update": "gestione_liste",
}


def bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _to_user_pydantic(doc):
    from server import User
    return User(**{k: doc.get(k) for k in [
        "user_id","email","name","picture","onboarded","profession","sector","verticals","interests","tone","created_at","role",
        "org_id","org_role","telegram_chat_id","business_vertical",
    ] if k in doc})


async def _get_user_by_chat(db, chat_id: int):
    return await db.users.find_one({"telegram_chat_id": chat_id}, {"_id": 0})


async def _user_list_names(db, user_doc: dict) -> list[str]:
    from server import _visible_query
    current = _to_user_pydantic(user_doc)
    colls = await db.collections.find(_visible_query(current), {"_id": 0, "name": 1}).to_list(200)
    return [c["name"] for c in colls]


# ============ INTENT CLASSIFIER ============
async def _classify_intent(text: str, last_context: dict | None, list_names: list[str] | None = None,
                            user_id: Optional[str] = None) -> dict:
    """Return {action, continuation, confidence}. Fallback: heuristic.

    This call's own OUTPUT is what determines which catalog feature it belongs to, so it
    can't be tracked with eager kwargs at construction time (that feature isn't known yet) -
    it uses LlmChat.record_deferred() once the action is resolved (success or heuristic
    fallback alike), per the usage-tracking spec's rule that support calls like this must be
    attributed to the feature they end up enabling, never dumped into "altro" by default."""
    ctx_hint = ""
    if last_context and last_context.get("current_action"):
        ctx_hint = (
            f"\nUltima azione in corso: {last_context['current_action']}. "
            f"Ultimo messaggio utente: \"{(last_context.get('last_user_message') or '')[:200]}\"."
        )
    lists_hint = f"\nListe esistenti dell'utente: {', '.join(list_names)}." if list_names else ""
    system = (
        "Sei un classificatore di intenti per un assistente personale. "
        "Ricevi un messaggio utente e restituisci SOLO un JSON:\n"
        "{\"action\": \"info_upload|info_request|task_todo|journal|list_update\", "
        "\"continuation\": \"continue|new\", \"confidence\": 0.0-1.0}\n\n"
        "Regole per action:\n"
        "- info_upload: l'utente sta comunicando/salvando un'informazione generica da ricordare (es. 'la mia patente scade il 12/2028', 'il codice del wifi è XYZ', 'mia sorella si chiama Anna').\n"
        "- info_request: l'utente sta ponendo una domanda a cui rispondere con la sua knowledge base o conoscenza generale (es. 'quando scade Netflix?', 'che ristorante mi consigli?', 'chi è il sindaco di Milano?').\n"
        "- task_todo: c'è un'intenzione di azione futura, un promemoria, una data (es. 'ricordami di chiamare Marco martedì', 'devo comprare il latte', 'presentazione lunedì alle 10').\n"
        "- journal: l'utente racconta la sua giornata, come si sente, riflessioni personali (es. 'oggi è stata una giornata dura', 'sono felice perché...').\n"
        "- list_update: l'utente vuole aggiungere, modificare o rimuovere un elemento specifico in una delle sue liste esistenti "
        "(es. 'aggiungi Mario alla lista clienti', 'elimina Utente 2 dalla lezione di pilates del lunedì mattina', 'cambia il telefono di Luca').\n\n"
        "Regole per continuation:\n"
        "- continue: se il messaggio è chiaramente un follow-up sul contesto precedente (segue lo stesso argomento, risponde a una richiesta di chiarimento, aggiunge dettagli).\n"
        "- new: se apre un argomento diverso, cambia azione, o non c'è contesto precedente.\n\n"
        f"{lists_hint}\n"
        f"Contesto:{ctx_hint if ctx_hint else ' nessun contesto precedente.'}\n"
        "IMPORTANTE: rispondi SOLO con il JSON, senza testo aggiuntivo."
    )
    chat = None
    try:
        chat = LlmChat(
            api_key=os.environ.get("ANTHROPIC_API_KEY"),
            session_id=f"tg_cls_{uuid.uuid4().hex[:8]}",
            system_message=system,
        ).with_model("openai", "gpt-4o-mini")  # cheap classification, runs on every message
        raw = await chat.send_message(UserMessage(text=text))
        m = _re.search(r"\{[\s\S]*\}", raw or "")
        data = _json.loads(m.group(0)) if m else {}
        action = data.get("action") or "info_request"
        cont = data.get("continuation") or "new"
        conf = float(data.get("confidence") or 0.5)
        if action not in {"info_upload","info_request","task_todo","journal","list_update"}:
            action = "info_request"
        if cont not in {"continue", "new"}:
            cont = "new"
        chat.record_deferred(user_id=user_id, feature=_TG_ACTION_TO_FEATURE.get(action, "altro"), channel="telegram", trigger="utente")
        return {"action": action, "continuation": cont, "confidence": conf}
    except Exception:
        logger.exception("intent classification failed, using heuristic")
        heuristic_action = _infer_action_heuristic(text, list_names)
        if chat is not None:
            chat.record_deferred(user_id=user_id, feature=_TG_ACTION_TO_FEATURE.get(heuristic_action, "altro"), channel="telegram", trigger="utente")
        return {"action": heuristic_action, "continuation": "new", "confidence": 0.3}


def _infer_action_heuristic(text: str, list_names: list[str] | None = None) -> str:
    t = (text or "").lower().strip()
    if list_names and any(k in t for k in ("aggiungi", "elimina", "rimuovi", "cancella", "modifica", "cambia")) and any(n.lower() in t for n in list_names):
        return "list_update"
    if any(t.startswith(k) for k in ("ricordami ", "aggiungi task", "task:", "todo ", "to-do", "domani ", "lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica")):
        return "task_todo"
    if any(k in t for k in ("oggi è stata", "oggi ho", "mi sento", "sono stanco", "sono felice", "sono grato", "diario:")):
        return "journal"
    if any(k in t for k in ("salva", "annota", "prendi nota", "memorizza")):
        return "info_upload"
    return "info_request"


# ============ CONVERSATION STATE ============
async def _get_state(db, user_id: str, chat_id: int) -> dict:
    doc = await db.telegram_sessions.find_one({"chat_id": chat_id, "user_id": user_id}, {"_id": 0})
    return doc or {"chat_id": chat_id, "user_id": user_id, "current_conv_id": None, "current_action": None, "last_message_at": None, "last_user_message": None}


async def _set_state(db, chat_id: int, user_id: str, **fields):
    fields["last_message_at"] = datetime.now(timezone.utc).isoformat()
    await db.telegram_sessions.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": fields},
        upsert=True,
    )


async def _clear_state(db, chat_id: int, user_id: str):
    await db.telegram_sessions.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"current_conv_id": None, "current_action": None, "last_user_message": None, "last_message_at": datetime.now(timezone.utc).isoformat()}},
    )


def _state_is_fresh(state: dict) -> bool:
    ts = state.get("last_message_at")
    if not ts: return False
    try:
        last = datetime.fromisoformat(ts)
        return datetime.now(timezone.utc) - last < timedelta(minutes=CONTEXT_TIMEOUT_MIN)
    except Exception:
        return False


# ============ ACTION EXECUTION ============
async def _process_action(db, user_doc: dict, action: str, content: str, conv_id: str | None) -> tuple[str, str]:
    """Execute one action against a specific conv_id (new if None). Returns (answer, conv_id)."""
    from server import (
        build_system_prompt, _parse_task_json, _create_task_or_todo, _extract_meta, retrieve_kb,
        _find_created_in_conv, _update_task_or_todo_from_meta, _resolve_journal_date, _save_journal_entry,
    )

    new_conv = conv_id is None
    if new_conv:
        conv_id = f"conv_tg_{uuid.uuid4().hex[:12]}"

    # Load prior messages for continuity
    prior_messages = []
    if not new_conv:
        conv_doc = await db.conversations.find_one({"conv_id": conv_id}, {"_id": 0, "messages": 1})
        if conv_doc:
            prior_messages = conv_doc.get("messages", [])

    system = build_system_prompt(_to_user_pydantic(user_doc), action)
    user_text = content
    # Retrieve on every turn (not just the first) so follow-up questions in the same
    # thread ("e domani?") also get fresh, relevant context - a message reusing an
    # older conv_id via the "continue" classifier must not silently skip retrieval.
    if action == "info_request":
        kb = await retrieve_kb(user_doc["user_id"], content, scope="all", org_id=user_doc.get("org_id"))
        if kb:
            def _fmt(c): return c.get("display") or c.get("text","")[:400]
            user_text = f"CONTESTO KB PERSONALE:\n" + "\n\n".join(f"- {_fmt(c)}" for c in kb) + f"\n\nDOMANDA:\n{content}"
    elif action == "task_todo":
        # Same idea as info_request's RAG above, scoped to the personal KB only (not other
        # tasks/journal entries) - lets "crea un task per ogni lezione di pilates" see a
        # schedule the user uploaded earlier, without pasting it into the message.
        kb = await retrieve_kb(user_doc["user_id"], content, scope="kb", org_id=user_doc.get("org_id"))
        if kb:
            def _fmt(c): return c.get("display") or c.get("text", "")[:400]
            user_text = f"CONTESTO KB PERSONALE:\n" + "\n\n".join(f"- {_fmt(c)}" for c in kb) + f"\n\nRICHIESTA:\n{content}"

    chat = LlmChat(
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        session_id=conv_id,
        system_message=system,
        user_id=user_doc["user_id"], feature=_TG_ACTION_TO_FEATURE.get(action, "altro"),
        channel="telegram", trigger="utente", org_id=user_doc.get("org_id"),
    ).with_model("openai", "gpt-4o")

    # Rebuild history so Claude "remembers" what was said in this thread
    for m in prior_messages[-8:]:  # last 4 turns
        try:
            if m.get("role") == "user":
                await chat.send_message(UserMessage(text=m.get("content","")))
        except Exception:
            pass

    answer = await chat.send_message(UserMessage(text=user_text))
    visible, meta = _extract_meta(answer)

    # persist conversation
    turn_user = {"role": "user", "content": content}
    turn_bot = {"role": "assistant", "content": visible}
    now_iso = datetime.now(timezone.utc).isoformat()
    if new_conv:
        await db.conversations.insert_one({
            "conv_id": conv_id,
            "user_id": user_doc["user_id"],
            "action": action,
            "channel": "telegram",
            "created_at": now_iso,
            "updated_at": now_iso,
            "messages": [turn_user, turn_bot],
            "title": (meta or {}).get("title") or content[:60],
            "summary": (meta or {}).get("summary") or visible[:140],
            "pipeline": {"claude": "ok", "mongodb": "ok"},
        })
    else:
        await db.conversations.update_one(
            {"conv_id": conv_id},
            {"$push": {"messages": {"$each": [turn_user, turn_bot]}},
             "$set": {"updated_at": now_iso}}
        )

    # Side effects. info_upload always saves a new KB chunk on EVERY turn (not just the
    # first message of a new conversation) - a follow-up message in an ongoing "salva
    # informazioni" thread is virtually always a NEW distinct fact (e.g. "oggi Martina ha
    # fatto lezione di Pilates" followed later, in the same thread, by "venerdì scorso
    # Martina ha fatto lezione di Pilates"), not a duplicate of the first. Gating this to
    # new_conv silently dropped every fact stated in a follow-up turn, with no error and no
    # sign anything was wrong - it just never became retrievable.
    if action == "info_upload":
        await db.kb_chunks.insert_one({
            "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
            "user_id": user_doc["user_id"],
            "text": content,
            "summary": visible,
            "conv_id": conv_id,
            "channel": "telegram",
            "created_at": now_iso,
        })
        # Same "auto task from an embedded reminder" behavior as the web chat - only
        # when the model attached a task with a certain due_date.
        if meta and meta.get("task") and isinstance(meta["task"], dict) and meta["task"].get("due_date"):
            try:
                await _create_task_or_todo(user_doc["user_id"], meta["task"], conv_id, default_reminder_enabled=True)
            except Exception:
                logger.exception("auto task creation from info_upload failed")
    elif action == "task_todo":
        parsed = _parse_task_json(answer) or meta
        bulk_tasks = parsed.get("tasks") if parsed else None
        if isinstance(bulk_tasks, list) and bulk_tasks:
            # Multiple events read from the KB (e.g. "un task per ogni lezione di pilates"):
            # one task/todo per item, all sharing this conv_id.
            for item in bulk_tasks:
                if isinstance(item, dict) and item.get("title"):
                    try:
                        await _create_task_or_todo(user_doc["user_id"], item, conv_id, default_reminder_enabled=True)
                    except Exception:
                        logger.exception(f"bulk task creation failed for item={item!r}")
        elif parsed:
            # A follow-up turn in the SAME thread updates what was already created there
            # instead of creating a duplicate every time the user adds more detail.
            existing = await _find_created_in_conv(conv_id)
            if existing is None:
                # A Telegram-created task has no reminder-toggle button like the web app
                # does, so the reminder defaults ON here - otherwise it silently never fires.
                await _create_task_or_todo(user_doc["user_id"], parsed, conv_id, default_reminder_enabled=True)
            else:
                kind, existing_doc = existing
                await _update_task_or_todo_from_meta(kind, existing_doc["id"], parsed)
    elif action == "journal":
        # Same date resolution + append-or-create as the web chat: the entry lands on the
        # day the user is actually talking about (e.g. "ieri"), not always on today's page.
        target_date = _resolve_journal_date(meta)
        await _save_journal_entry(user_doc["user_id"], target_date, content, visible, meta, conv_id)

    ut.fire_and_forget_feature_event(
        user_id=user_doc["user_id"], feature=_TG_ACTION_TO_FEATURE.get(action, "altro"),
        channel="telegram", trigger="utente", org_id=user_doc.get("org_id"),
    )
    return visible, conv_id


# ============ KEYBOARDS ============
def _reply_keyboard(active_action: str | None) -> InlineKeyboardMarkup:
    def kb(label, cb, active=False):
        return InlineKeyboardButton(("✓ " + label) if active else label, callback_data=cb)
    row1 = [
        InlineKeyboardButton("🔄 Nuova conversazione", callback_data="ctrl:new"),
        InlineKeyboardButton("✅ Termina", callback_data="ctrl:end"),
    ]
    row2 = [
        kb("💾 Salva", "act:info_upload", active_action == "info_upload"),
        kb("🔍 Cerca", "act:info_request", active_action == "info_request"),
        kb("📝 Task", "act:task_todo", active_action == "task_todo"),
        kb("📔 Diario", "act:journal", active_action == "journal"),
    ]
    return InlineKeyboardMarkup([row1, row2])


# ============ HANDLERS ============
async def _cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from server import db
    args = ctx.args
    chat_id = update.effective_chat.id
    if args:
        code = args[0]
        link = await db.telegram_links.find_one({"code": code}, {"_id": 0})
        if not link:
            await update.message.reply_text("❌ Codice non valido o scaduto. Genera un nuovo codice in mAIPAL → Impostazioni.")
            return
        await db.users.update_one({"user_id": link["user_id"]}, {"$set": {"telegram_chat_id": chat_id}})
        await db.telegram_links.delete_one({"code": code})
        user = await db.users.find_one({"user_id": link["user_id"]}, {"_id": 0})
        await update.message.reply_text(
            f"✅ Ciao {user.get('name','')}! Sei connesso a mAIPAL.\n\n"
            "Scrivi liberamente: capirò io cosa vuoi fare (salvare info, cercare, creare task, diario).\n"
            "Comandi rapidi: /ask /save /task /journal /end /help"
        )
        return

    user = await _get_user_by_chat(db, chat_id)
    if user:
        await update.message.reply_text(f"Bentornato, {user.get('name','')}! Scrivi liberamente, capirò io.")
    else:
        await update.message.reply_text(
            "👋 Ciao! Sono mAIPAL. Per collegare il tuo account:\n"
            "1) Apri mAIPAL → Impostazioni → Telegram\n"
            "2) Copia il codice di collegamento\n"
            "3) Torna qui e scrivi: /start <codice>"
        )


async def _cmd_help(update: Update, ctx):
    await update.message.reply_text(
        "🤖 mAIPAL su Telegram\n\n"
        "Puoi scrivere liberamente: il bot capisce da solo se stai:\n"
        "  💾 salvando informazioni · 🔍 cercando · 📝 creando task · 📔 scrivendo il diario\n\n"
        "Mandami anche una foto (con o senza didascalia): te la salvo su Drive - se non capisco da solo "
        "in quale cartella, te lo chiedo.\n\n"
        "Continuità: se il messaggio successivo prosegue lo stesso argomento, rimango nel contesto. "
        "Se cambi argomento, apro una nuova conversazione.\n\n"
        "Comandi:\n"
        "  /ask <domanda>\n"
        "  /save <info>\n"
        "  /task <task>\n"
        "  /journal <racconto>\n"
        "  /report — genera un referto veterinario (scegli il tipo, poi detta la visita)\n"
        "  /lista <richiesta> — aggiungi/modifica/rimuovi un elemento da una lista, es. "
        "\"/lista aggiungi Mario Rossi alla lista clienti\"\n"
        "  /end   — chiudi la conversazione in corso\n"
        "  /help"
    )


async def _cmd_end(update: Update, ctx):
    from server import db
    chat_id = update.effective_chat.id
    user = await _get_user_by_chat(db, chat_id)
    if not user:
        await update.message.reply_text("Devi prima collegare l'account.")
        return
    await _clear_state(db, chat_id, user["user_id"])
    await update.message.reply_text("✅ Conversazione chiusa. Scrivi pure quando vuoi.", reply_markup=_reply_keyboard(None))


async def _run_and_reply(update_or_query, ctx, db, user, action, content, force_new=False):
    chat_id = update_or_query.message.chat.id if hasattr(update_or_query, "message") and update_or_query.message else update_or_query.effective_chat.id
    state = await _get_state(db, user["user_id"], chat_id)
    reuse = (not force_new) and _state_is_fresh(state) and state.get("current_conv_id") and state.get("current_action") == action
    conv_id = state.get("current_conv_id") if reuse else None

    reply_target = update_or_query.message if hasattr(update_or_query, "message") and update_or_query.message else update_or_query.effective_chat
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        answer, new_conv_id = await _process_action(db, user, action, content, conv_id)
    except Exception as e:
        logger.exception("tg process error")
        await ctx.bot.send_message(chat_id=chat_id, text=f"⚠️ Errore: {str(e)[:200]}")
        return

    await _set_state(db, chat_id, user["user_id"], current_conv_id=new_conv_id, current_action=action, last_user_message=content)

    if len(answer) > 3500:
        answer = answer[:3500] + "\n…"
    header = ACTIONS_LABEL.get(action, "")
    hint = " · nuova conv." if not reuse else " · continua conv."
    await ctx.bot.send_message(
        chat_id=chat_id,
        text=f"{header}{hint}\n\n{answer}",
        reply_markup=_reply_keyboard(action),
    )


async def _cmd_generic(update: Update, ctx, forced_action=None):
    from server import db
    chat_id = update.effective_chat.id
    user = await _get_user_by_chat(db, chat_id)
    if not user:
        await update.message.reply_text("Devi prima collegare l'account: apri mAIPAL → Impostazioni → Telegram e usa /start <codice>.")
        return

    text = (update.message.text or "").strip()
    force_new = False
    if forced_action:
        parts = text.split(" ", 1)
        content = parts[1] if len(parts) > 1 else ""
        if not content.strip():
            await update.message.reply_text("Scrivi qualcosa dopo il comando.")
            return
        action = forced_action
        force_new = True   # explicit command = fresh context by default
    else:
        content = text
        state = await _get_state(db, user["user_id"], chat_id)
        if state.get("pending_report_type"):
            await _run_vet_report_flow(update, ctx, db, user, content, state["pending_report_type"])
            return
        if state.get("pending_list_update"):
            await _run_list_update_flow(update, ctx, db, user, content)
            return
        if state.get("pending_drive_upload_id"):
            await _run_drive_pending_flow(update, ctx, db, user, state["pending_drive_upload_id"], content)
            return
        prev_ctx = state if _state_is_fresh(state) else None
        list_names = await _user_list_names(db, user)
        intent = await _classify_intent(content, prev_ctx, list_names, user_id=user["user_id"])
        action = intent["action"]
        if action == "list_update":
            await _run_list_update_flow(update, ctx, db, user, content)
            return
        if action == "task_todo" and await _try_task_command(update, ctx, db, user, content):
            return
        force_new = (intent["continuation"] == "new") or (prev_ctx is None) or (state.get("current_action") != action)

    await _run_and_reply(update, ctx, db, user, action, content, force_new=force_new)


async def _cmd_ask(update, ctx):     await _cmd_generic(update, ctx, "info_request")
async def _cmd_save(update, ctx):    await _cmd_generic(update, ctx, "info_upload")
async def _cmd_task(update, ctx):    await _cmd_generic(update, ctx, "task_todo")
async def _cmd_journal(update, ctx): await _cmd_generic(update, ctx, "journal")
async def _msg_free(update, ctx):    await _cmd_generic(update, ctx, None)


async def _cmd_report(update: Update, ctx):
    """Verticale veterinario: avvia il flusso 'referto visita' - il prossimo messaggio
    (testo o vocale) verrà interpretato come il resoconto della visita, non classificato
    dal solito intent classifier."""
    from server import db, _visible_query
    import vet_reports as vr
    chat_id = update.effective_chat.id
    user = await _get_user_by_chat(db, chat_id)
    if not user:
        await update.message.reply_text("Devi prima collegare l'account: apri mAIPAL → Impostazioni → Telegram e usa /start <codice>.")
        return
    buttons = [[InlineKeyboardButton(t["name"], callback_data=f"vetrep:{key}")] for key, t in vr.BUILTIN_TEMPLATES.items()]
    current = _to_user_pydantic(user)
    custom = await db.vet_templates.find(_visible_query(current), {"_id": 0, "id": 1, "name": 1}).to_list(20)
    for t in custom:
        buttons.append([InlineKeyboardButton(t["name"], callback_data=f"vetrep:{t['id']}")])
    await update.message.reply_text(
        "📋 Che tipo di visita? Scegli il template, poi mandami il resoconto (testo o vocale).",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _run_vet_report_flow(update_or_query, ctx, db, user, content, visit_type, patient_item_id=None):
    from server import _generate_vet_report
    chat_id = update_or_query.message.chat.id if hasattr(update_or_query, "message") and update_or_query.message else update_or_query.effective_chat.id
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    current = _to_user_pydantic(user)
    try:
        rep = await _generate_vet_report(current, content, visit_type, patient_item_id, channel="telegram")
    except Exception as e:
        logger.exception("tg vet report failed")
        await ctx.bot.send_message(chat_id=chat_id, text=f"⚠️ Errore nella generazione del referto: {str(e)[:200]}")
        await _set_state(db, chat_id, user["user_id"], pending_report_type=None, pending_report_context=None)
        return

    if rep.get("status") == "ambiguous_patient":
        buttons = [
            [InlineKeyboardButton(f"{c['name']} · {c.get('owner') or '?'} ({c.get('species') or '?'})", callback_data=f"vetpat:{c['item_id']}")]
            for c in rep["candidates"]
        ]
        await _set_state(db, chat_id, user["user_id"], pending_report_context={"visit_type": visit_type, "text": content})
        await ctx.bot.send_message(
            chat_id=chat_id,
            text="🐾 Ho trovato più pazienti con questo nome. Quale intendi?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    lines = [f"✅ Referto generato: {rep['template_name']}"]
    if rep.get("patient_name"):
        lines.append(f"👤 Paziente: {rep['patient_name']} (data ultima visita aggiornata)")
    else:
        lines.append('👤 Paziente non riconosciuto — salvato tra i "Report generici"')
    if rep.get("drive_link"):
        lines.append(f"📁 Salvato su Drive in \"{rep['drive_folder']}\"")
    lines.append("📄 Il file .docx è qui sopra." if rep.get("telegram_sent") else "⚠️ Non inviato come file: nessun problema, resta salvato in app/Drive.")
    await ctx.bot.send_message(chat_id=chat_id, text="\n".join(lines))
    await _set_state(db, chat_id, user["user_id"], pending_report_type=None, pending_report_context=None)


async def _cmd_list_update(update: Update, ctx):
    """Modifica di una Lista (Collections) a parole: '/lista aggiungi Mario Rossi alla
    lista clienti'. Senza testo dopo il comando, il prossimo messaggio (testo o vocale)
    viene trattato come la richiesta - stesso schema del flusso /report."""
    from server import db
    chat_id = update.effective_chat.id
    user = await _get_user_by_chat(db, chat_id)
    if not user:
        await update.message.reply_text("Devi prima collegare l'account: apri mAIPAL → Impostazioni → Telegram e usa /start <codice>.")
        return
    parts = (update.message.text or "").split(" ", 1)
    content = parts[1].strip() if len(parts) > 1 else ""
    if content:
        await _run_list_update_flow(update, ctx, db, user, content)
    else:
        await _set_state(db, chat_id, user["user_id"], pending_list_update=True)
        await update.message.reply_text('📋 Scrivimi cosa vuoi modificare, es. "Aggiungi Mario Rossi alla lista clienti".')


async def _run_list_update_flow(update_or_query, ctx, db, user, content, op=None, collection_id=None,
                                 item_id=None, sub_item_id=None, fields=None, item_query=None, sub_item_query=None,
                                 confirm=False, sub_items=None, items=None):
    from server import _execute_list_update
    chat_id = update_or_query.message.chat.id if hasattr(update_or_query, "message") and update_or_query.message else update_or_query.effective_chat.id
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    current = _to_user_pydantic(user)
    try:
        res = await _execute_list_update(
            current, content, op=op, collection_id=collection_id, item_id=item_id, sub_item_id=sub_item_id,
            fields=fields, item_query=item_query, sub_item_query=sub_item_query, confirm=confirm,
            new_sub_items=sub_items, new_items=items, channel="telegram",
        )
    except Exception as e:
        logger.exception("tg list update failed")
        detail = getattr(e, "detail", None) or str(e)
        await ctx.bot.send_message(chat_id=chat_id, text=f"⚠️ {str(detail)[:300]}")
        await _set_state(db, chat_id, user["user_id"], pending_list_update=None, pending_list_context=None)
        return

    status = res.get("status")
    if status in ("ambiguous_list", "ambiguous_item", "ambiguous_sub_item"):
        if status == "ambiguous_list":
            buttons = [[InlineKeyboardButton(c["name"][:60], callback_data=f"lstc:{c['collection_id']}")] for c in res["candidates"]]
            prompt = "📋 A quale lista ti riferisci?"
        elif status == "ambiguous_item":
            buttons = [[InlineKeyboardButton(c["label"][:60], callback_data=f"lsti:{c['item_id']}")] for c in res["candidates"]]
            prompt = "📋 Ho trovato più corrispondenze. Quale intendi?"
        else:
            buttons = [[InlineKeyboardButton(c["label"][:60], callback_data=f"lsts:{c['sub_item_id']}")] for c in res["candidates"]]
            prompt = "📋 Ho trovato più corrispondenze. Quale intendi?"
        await _set_state(db, chat_id, user["user_id"], pending_list_update=None, pending_list_context=res)
        await ctx.bot.send_message(chat_id=chat_id, text=prompt, reply_markup=InlineKeyboardMarkup(buttons))
        return

    if status == "confirm_clear":
        buttons = [[InlineKeyboardButton(f"⚠️ Conferma eliminazione di {res['count']}", callback_data="lstx:1")]]
        await _set_state(db, chat_id, user["user_id"], pending_list_update=None, pending_list_context=res)
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Stai per eliminare {res['count']} element{'o' if res['count'] == 1 else 'i'} in un colpo solo. Confermi?",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if status == "confirm_bulk_add":
        buttons = [[InlineKeyboardButton(f"✅ Conferma: crea {res['count']} elementi", callback_data="lstx:1")]]
        await _set_state(db, chat_id, user["user_id"], pending_list_update=None, pending_list_context=res)
        await ctx.bot.send_message(chat_id=chat_id, text=res["message"], reply_markup=InlineKeyboardMarkup(buttons))
        return

    await ctx.bot.send_message(chat_id=chat_id, text=f"✅ {res['message']}")
    await _set_state(db, chat_id, user["user_id"], pending_list_update=None, pending_list_context=None)


async def _try_task_command(update_or_query, ctx, db, user, text: str) -> bool:
    """Fast path for 'elimina/segna come fatto il task X' - checked before a "task_todo"-
    classified message is treated as a request to CREATE a new task. Without this, the LLM
    would just chat back "fatto!" without ever actually deleting/completing anything (it has
    no such tool in the normal task_todo flow), the same false-confirmation trap fixed
    earlier for Drive uploads. Returns True if it handled the message (caller should stop
    processing it any further)."""
    from server import _execute_task_command
    res = await _execute_task_command(user["user_id"], text, channel="telegram")
    if res is None:
        return False
    chat_id = update_or_query.message.chat.id if hasattr(update_or_query, "message") and update_or_query.message else update_or_query.effective_chat.id
    if res["status"] == "ok":
        await ctx.bot.send_message(chat_id=chat_id, text=f"✅ {res['message']}")
    elif res["status"] == "ambiguous":
        buttons = [[InlineKeyboardButton(c["title"][:60], callback_data=f"taskcmd:{res['op']}:{c['id']}")] for c in res["candidates"]]
        await ctx.bot.send_message(chat_id=chat_id, text="Ho trovato più corrispondenze. Quale intendi?", reply_markup=InlineKeyboardMarkup(buttons))
    else:
        await ctx.bot.send_message(chat_id=chat_id, text=f"Non ho trovato nessun task/to-do che corrisponda a \"{res.get('query', text)}\".")
    return True


async def _on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from server import db
    q = update.callback_query
    await q.answer()
    chat_id = q.message.chat.id
    user = await _get_user_by_chat(db, chat_id)
    if not user:
        await q.edit_message_reply_markup(reply_markup=None)
        return

    data = q.data or ""
    if data == "ctrl:end":
        await _clear_state(db, chat_id, user["user_id"])
        await ctx.bot.send_message(chat_id=chat_id, text="✅ Conversazione chiusa.")
    elif data == "ctrl:new":
        await _clear_state(db, chat_id, user["user_id"])
        await ctx.bot.send_message(chat_id=chat_id, text="🔄 Nuova conversazione. Scrivimi cosa vuoi fare.")
    elif data.startswith("vetrep:"):
        visit_type = data.split(":", 1)[1]
        await _set_state(db, chat_id, user["user_id"], pending_report_type=visit_type)
        await ctx.bot.send_message(chat_id=chat_id, text="🩺 Ok. Ora scrivi o manda un vocale con il resoconto della visita.")
    elif data.startswith("vetpat:"):
        patient_id = data.split(":", 1)[1]
        state = await _get_state(db, user["user_id"], chat_id)
        pctx = state.get("pending_report_context") or {}
        if not pctx.get("text"):
            await ctx.bot.send_message(chat_id=chat_id, text="Ho perso il contesto della visita, rifai /report.")
            return
        await _run_vet_report_flow(q, ctx, db, user, pctx["text"], pctx["visit_type"], patient_item_id=patient_id)
    elif data.startswith("lstc:") or data.startswith("lsti:") or data.startswith("lsts:"):
        target_id = data.split(":", 1)[1]
        state = await _get_state(db, user["user_id"], chat_id)
        pctx = state.get("pending_list_context") or {}
        if not pctx.get("text"):
            await ctx.bot.send_message(chat_id=chat_id, text="Ho perso il contesto, rifai /lista.")
            return
        kwargs = dict(op=pctx.get("op"), collection_id=pctx.get("collection_id"), item_id=pctx.get("item_id"),
                      fields=pctx.get("fields"), item_query=pctx.get("item_query"), sub_item_query=pctx.get("sub_item_query"),
                      sub_items=pctx.get("sub_items"))
        if data.startswith("lstc:"): kwargs["collection_id"] = target_id
        elif data.startswith("lsti:"): kwargs["item_id"] = target_id
        else: kwargs["sub_item_id"] = target_id
        await _run_list_update_flow(q, ctx, db, user, pctx["text"], **kwargs)
    elif data.startswith("lstx:"):
        state = await _get_state(db, user["user_id"], chat_id)
        pctx = state.get("pending_list_context") or {}
        if not pctx.get("text"):
            await ctx.bot.send_message(chat_id=chat_id, text="Ho perso il contesto, rifai /lista.")
            return
        await _run_list_update_flow(
            q, ctx, db, user, pctx["text"], op=pctx.get("op"), collection_id=pctx.get("collection_id"),
            item_id=pctx.get("item_id"), fields=pctx.get("fields"), item_query=pctx.get("item_query"),
            sub_item_query=pctx.get("sub_item_query"), confirm=True, items=pctx.get("items"),
        )
    elif data.startswith("taskcmd:"):
        _, op, target_id = data.split(":", 2)
        from server import _apply_task_command
        res = await _apply_task_command(target_id, op, user["user_id"])
        if res.get("status") == "ok":
            is_task = target_id.startswith("task_")
            ut.fire_and_forget_feature_event(
                user_id=user["user_id"], feature="creazione_task" if is_task else "creazione_todo",
                channel="telegram", trigger="utente", org_id=user.get("org_id"),
            )
        text = f"✅ {res['message']}" if res.get("status") == "ok" else "⚠️ Non trovato (forse già eliminato/completato)."
        await ctx.bot.send_message(chat_id=chat_id, text=text)
    elif data.startswith("act:"):
        forced = data.split(":", 1)[1]
        state = await _get_state(db, user["user_id"], chat_id)
        last = state.get("last_user_message")
        if not last:
            await ctx.bot.send_message(chat_id=chat_id, text=f"Ho impostato l'azione {ACTION_ITA.get(forced, forced)}. Scrivi cosa vuoi fare.")
            await _set_state(db, chat_id, user["user_id"], current_action=forced, current_conv_id=None)
            return
        # Re-run the last message with the forced action, in a NEW conv
        await _run_and_reply(q, ctx, db, user, forced, last, force_new=True)
    elif data.startswith("snooze:"):
        from server import LOCAL_TZ
        _, task_id, minutes_str = data.split(":", 2)
        minutes = int(minutes_str)
        task = await db.tasks.find_one({"id": task_id, "user_id": user["user_id"]}, {"_id": 0})
        if not task:
            await ctx.bot.send_message(chat_id=chat_id, text="Non trovo più questo task.")
            return
        due_time = task.get("due_time") or "09:00"
        try:
            due_dt_local = datetime.strptime(f"{task.get('due_date')} {due_time}", "%Y-%m-%d %H:%M").replace(tzinfo=LOCAL_TZ)
        except ValueError:
            await ctx.bot.send_message(chat_id=chat_id, text="Impossibile posticipare: data del task non valida.")
            return
        new_dt_local = due_dt_local + timedelta(minutes=minutes)
        await db.tasks.update_one(
            {"id": task_id},
            {"$set": {
                "due_date": new_dt_local.date().isoformat(),
                "due_time": new_dt_local.strftime("%H:%M"),
                "reminder_sent": False,
                "reminder_msg_sent": False,
            }},
        )
        label = {15: "15 minuti", 60: "1 ora", 1440: "domani"}.get(minutes, f"{minutes} minuti")
        await ctx.bot.send_message(
            chat_id=chat_id,
            text=f"🔁 *{task.get('title', '(senza titolo)')}* posticipato di {label}.\nNuovo orario: {new_dt_local.strftime('%d/%m alle %H:%M')}.",
            parse_mode="Markdown",
        )


async def _msg_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from server import db
    import tempfile

    chat_id = update.effective_chat.id
    user = await _get_user_by_chat(db, chat_id)
    if not user:
        await update.message.reply_text("Devi prima collegare l'account.")
        return
    voice = update.message.voice
    if not voice: return
    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    tmp_path = None
    mp3_path = None
    stt = OpenAISpeechToText(api_key=os.environ.get("OPENAI_API_KEY"))

    def _track_stt(feature: str):
        # A voice transcription has no feature of its own at call time - it's only known
        # once the transcript is classified (or a pending-flow's own feature is known
        # outright). Called exactly once per voice message, right before handing off.
        stt.record_deferred(user_id=user["user_id"], feature=feature, channel="telegram", trigger="utente", org_id=user.get("org_id"))

    try:
        tg_file = await ctx.bot.get_file(voice.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(custom_path=tmp_path)
        # Telegram voice notes are OGG/Opus. Whisper wrapper only accepts mp3/mp4/mpeg/mpga/m4a/wav/webm.
        # Convert to mp3 with ffmpeg.
        mp3_path = tmp_path.replace(".ogg", ".mp3")
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y", "-loglevel", "error", "-i", tmp_path,
            "-ac", "1", "-ar", "16000", "-b:a", "64k", mp3_path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        _, ffmpeg_err = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {ffmpeg_err.decode()[:200]}")
        with open(mp3_path, "rb") as f:
            result = await stt.transcribe(file=f, model="whisper-1", response_format="verbose_json", language="it")
        transcript = getattr(result, "text", None) or (result.get("text") if isinstance(result, dict) else "")
        for p in (tmp_path, mp3_path):
            try:
                if p: os.unlink(p)
            except Exception: pass
        if not transcript.strip():
            _track_stt("altro")
            await update.message.reply_text("🎙️ Non ho capito l'audio. Riprova più chiaramente.")
            return
        await update.message.reply_text(f"🎙️ _{transcript}_", parse_mode="Markdown")

        state = await _get_state(db, user["user_id"], chat_id)
        if state.get("pending_report_type"):
            _track_stt("creazione_report")
            await _run_vet_report_flow(update, ctx, db, user, transcript, state["pending_report_type"])
            return
        if state.get("pending_list_update"):
            _track_stt("gestione_liste")
            await _run_list_update_flow(update, ctx, db, user, transcript)
            return
        if state.get("pending_drive_upload_id"):
            _track_stt("caricamento_informazioni")
            await _run_drive_pending_flow(update, ctx, db, user, state["pending_drive_upload_id"], transcript)
            return
        prev_ctx = state if _state_is_fresh(state) else None
        list_names = await _user_list_names(db, user)
        intent = await _classify_intent(transcript, prev_ctx, list_names, user_id=user["user_id"])
        action = intent["action"]
        _track_stt(_TG_ACTION_TO_FEATURE.get(action, "altro"))
        if action == "list_update":
            await _run_list_update_flow(update, ctx, db, user, transcript)
            return
        if action == "task_todo" and await _try_task_command(update, ctx, db, user, transcript):
            return
        force_new = (intent["continuation"] == "new") or (prev_ctx is None) or (state.get("current_action") != action)
        await _run_and_reply(update, ctx, db, user, action, transcript, force_new=force_new)
    except Exception as e:
        logger.exception("voice message failed")
        _track_stt("altro")
        await update.message.reply_text(f"⚠️ Errore trascrizione: {str(e)[:200]}")


async def _run_drive_pending_flow(update_or_query, ctx, db, user, pending_id, text):
    """Second turn of a photo/document save: this message may now name the Drive folder."""
    from server import _drive_resolve_pending_core
    chat_id = update_or_query.message.chat.id if hasattr(update_or_query, "message") and update_or_query.message else update_or_query.effective_chat.id
    current = _to_user_pydantic(user)
    try:
        result = await _drive_resolve_pending_core(current, pending_id, text, channel="telegram")
    except Exception as e:
        logger.exception("tg drive pending resolve failed")
        detail = getattr(e, "detail", None) or str(e)
        await ctx.bot.send_message(chat_id=chat_id, text=f"⚠️ {str(detail)[:300]}")
        await _set_state(db, chat_id, user["user_id"], pending_drive_upload_id=None)
        return

    if result.get("status") == "needs_folder":
        suggestions = result.get("suggestions") or []
        hint = f" Cartelle esistenti: {', '.join(suggestions[:8])}." if suggestions else ""
        await ctx.bot.send_message(chat_id=chat_id, text=f"📁 In quale cartella la salvo?{hint}")
        return

    await ctx.bot.send_message(chat_id=chat_id, text=f"✅ Salvata su Drive in \"{result['folder']}\".")
    await _set_state(db, chat_id, user["user_id"], pending_drive_upload_id=None)


async def _msg_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from server import db, _drive_smart_upload_core
    chat_id = update.effective_chat.id
    user = await _get_user_by_chat(db, chat_id)
    if not user:
        await update.message.reply_text("Devi prima collegare l'account: apri mAIPAL → Impostazioni → Telegram e usa /start <codice>.")
        return
    photos = update.message.photo
    if not photos:
        return
    await ctx.bot.send_chat_action(chat_id=chat_id, action="upload_photo")
    caption = (update.message.caption or "").strip()
    current = _to_user_pydantic(user)
    try:
        tg_file = await ctx.bot.get_file(photos[-1].file_id)  # last = highest resolution
        raw = await tg_file.download_as_bytearray()
        filename = f"foto_{uuid.uuid4().hex[:8]}.jpg"
        result = await _drive_smart_upload_core(current, bytes(raw), filename, "image/jpeg", caption, channel="telegram")
    except Exception as e:
        logger.exception("tg photo upload failed")
        detail = getattr(e, "detail", None) or str(e)
        await update.message.reply_text(f"⚠️ {str(detail)[:300]}")
        return

    if result.get("status") == "needs_folder":
        suggestions = result.get("suggestions") or []
        hint = f" Cartelle esistenti: {', '.join(suggestions[:8])}." if suggestions else ""
        await _set_state(db, chat_id, user["user_id"], pending_drive_upload_id=result["pending_id"])
        await update.message.reply_text(f"📸 In quale cartella la salvo?{hint}")
        return

    await update.message.reply_text(f"✅ Foto salvata su Drive in \"{result['folder']}\".")


def build_application() -> Application:
    app = Application.builder().token(bot_token()).build()
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("help", _cmd_help))
    app.add_handler(CommandHandler("end", _cmd_end))
    app.add_handler(CommandHandler("ask", _cmd_ask))
    app.add_handler(CommandHandler("save", _cmd_save))
    app.add_handler(CommandHandler("task", _cmd_task))
    app.add_handler(CommandHandler("journal", _cmd_journal))
    app.add_handler(CommandHandler("report", _cmd_report))
    app.add_handler(CommandHandler("lista", _cmd_list_update))
    app.add_handler(CallbackQueryHandler(_on_callback))
    app.add_handler(MessageHandler(filters.VOICE, _msg_voice))
    app.add_handler(MessageHandler(filters.PHOTO, _msg_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _msg_free))
    return app


async def start_polling():
    global _application
    if not bot_token():
        logger.info("TELEGRAM_BOT_TOKEN not set - skipping bot start")
        return
    _application = build_application()
    await _application.initialize()
    await _application.start()
    await _application.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram bot v2 polling started")


async def stop_polling():
    global _application
    if _application is None:
        return
    try:
        await _application.updater.stop()
        await _application.stop()
        await _application.shutdown()
    except Exception:
        logger.exception("error stopping telegram bot")
    _application = None


async def bot_username() -> str:
    if not bot_token():
        return ""
    try:
        from telegram import Bot
        b = Bot(token=bot_token())
        me = await b.get_me()
        return me.username or ""
    except Exception:
        return ""
