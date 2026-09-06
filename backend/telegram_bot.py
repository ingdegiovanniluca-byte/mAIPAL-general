"""Telegram bot v2: LLM-driven intent classifier + per-chat conversation state.

Behavior:
- Every free text (and every transcribed voice note) is classified by Claude Sonnet 5 into
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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)

_application = None
_polling_task = None

CONTEXT_TIMEOUT_MIN = 15  # after this many minutes, "continue" intent is ignored and a new conv is started
ACTIONS_LABEL = {"info_upload": "💾 Salvato", "info_request": "🔍 Risposta", "task_todo": "✅ Task/To-Do", "journal": "📔 Diario"}
ACTION_ITA = {"info_upload": "salva", "info_request": "chiedi", "task_todo": "task", "journal": "diario"}


def bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


def _to_user_pydantic(doc):
    from server import User
    return User(**{k: doc.get(k) for k in [
        "user_id","email","name","picture","onboarded","profession","sector","verticals","interests","tone","created_at","role"
    ] if k in doc})


async def _get_user_by_chat(db, chat_id: int):
    return await db.users.find_one({"telegram_chat_id": chat_id}, {"_id": 0})


# ============ INTENT CLASSIFIER ============
async def _classify_intent(text: str, last_context: dict | None) -> dict:
    """Return {action, continuation, confidence}. Fallback: heuristic."""
    ctx_hint = ""
    if last_context and last_context.get("current_action"):
        ctx_hint = (
            f"\nUltima azione in corso: {last_context['current_action']}. "
            f"Ultimo messaggio utente: \"{(last_context.get('last_user_message') or '')[:200]}\"."
        )
    system = (
        "Sei un classificatore di intenti per un assistente personale. "
        "Ricevi un messaggio utente e restituisci SOLO un JSON:\n"
        "{\"action\": \"info_upload|info_request|task_todo|journal\", "
        "\"continuation\": \"continue|new\", \"confidence\": 0.0-1.0}\n\n"
        "Regole per action:\n"
        "- info_upload: l'utente sta comunicando/salvando un'informazione da ricordare (es. 'la mia patente scade il 12/2028', 'il codice del wifi è XYZ', 'mia sorella si chiama Anna').\n"
        "- info_request: l'utente sta ponendo una domanda a cui rispondere con la sua knowledge base o conoscenza generale (es. 'quando scade Netflix?', 'che ristorante mi consigli?', 'chi è il sindaco di Milano?').\n"
        "- task_todo: c'è un'intenzione di azione futura, un promemoria, una data (es. 'ricordami di chiamare Marco martedì', 'devo comprare il latte', 'presentazione lunedì alle 10').\n"
        "- journal: l'utente racconta la sua giornata, come si sente, riflessioni personali (es. 'oggi è stata una giornata dura', 'sono felice perché...').\n\n"
        "Regole per continuation:\n"
        "- continue: se il messaggio è chiaramente un follow-up sul contesto precedente (segue lo stesso argomento, risponde a una richiesta di chiarimento, aggiunge dettagli).\n"
        "- new: se apre un argomento diverso, cambia azione, o non c'è contesto precedente.\n\n"
        f"Contesto:{ctx_hint if ctx_hint else ' nessun contesto precedente.'}\n"
        "IMPORTANTE: rispondi SOLO con il JSON, senza testo aggiuntivo."
    )
    try:
        chat = LlmChat(
            api_key=os.environ["EMERGENT_LLM_KEY"],
            session_id=f"tg_cls_{uuid.uuid4().hex[:8]}",
            system_message=system,
        ).with_model("anthropic", "claude-sonnet-5")
        raw = await chat.send_message(UserMessage(text=text))
        m = _re.search(r"\{[\s\S]*\}", raw or "")
        data = _json.loads(m.group(0)) if m else {}
        action = data.get("action") or "info_request"
        cont = data.get("continuation") or "new"
        conf = float(data.get("confidence") or 0.5)
        if action not in {"info_upload","info_request","task_todo","journal"}:
            action = "info_request"
        if cont not in {"continue", "new"}:
            cont = "new"
        return {"action": action, "continuation": cont, "confidence": conf}
    except Exception:
        logger.exception("intent classification failed, using heuristic")
        return {"action": _infer_action_heuristic(text), "continuation": "new", "confidence": 0.3}


def _infer_action_heuristic(text: str) -> str:
    t = (text or "").lower().strip()
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
    from server import build_system_prompt, _parse_task_json, _create_task_or_todo, _extract_meta, retrieve_kb

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
    if action == "info_request" and not prior_messages:
        kb = await retrieve_kb(user_doc["user_id"], content, scope="all")
        if kb:
            def _fmt(c): return c.get("display") or c.get("text","")[:400]
            user_text = f"CONTESTO KB PERSONALE:\n" + "\n\n".join(f"- {_fmt(c)}" for c in kb) + f"\n\nDOMANDA:\n{content}"

    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=conv_id,
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-5")

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

    # Side effects
    if action == "info_upload" and new_conv:
        await db.kb_chunks.insert_one({
            "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
            "user_id": user_doc["user_id"],
            "text": content,
            "summary": visible,
            "conv_id": conv_id,
            "channel": "telegram",
            "created_at": now_iso,
        })
    elif action == "task_todo":
        parsed = _parse_task_json(answer) or meta
        if parsed:
            await _create_task_or_todo(user_doc["user_id"], parsed, conv_id)
    elif action == "journal":
        from datetime import date as _date
        await db.journal_entries.insert_one({
            "id": f"jr_{uuid.uuid4().hex[:12]}",
            "user_id": user_doc["user_id"],
            "date": _date.today().isoformat(),
            "raw_text": content,
            "cleaned_text": visible,
            "title": (meta or {}).get("title", ""),
            "mood": (meta or {}).get("mood", ""),
            "highlights": (meta or {}).get("highlights", []),
            "created_at": now_iso,
            "source_conv": conv_id,
        })

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
        kb("💾", "act:info_upload", active_action == "info_upload"),
        kb("🔍", "act:info_request", active_action == "info_request"),
        kb("📝", "act:task_todo", active_action == "task_todo"),
        kb("📔", "act:journal", active_action == "journal"),
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
        "Continuità: se il messaggio successivo prosegue lo stesso argomento, rimango nel contesto. "
        "Se cambi argomento, apro una nuova conversazione.\n\n"
        "Comandi:\n"
        "  /ask <domanda>\n"
        "  /save <info>\n"
        "  /task <task>\n"
        "  /journal <racconto>\n"
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
        prev_ctx = state if _state_is_fresh(state) else None
        intent = await _classify_intent(content, prev_ctx)
        action = intent["action"]
        force_new = (intent["continuation"] == "new") or (prev_ctx is None) or (state.get("current_action") != action)

    await _run_and_reply(update, ctx, db, user, action, content, force_new=force_new)


async def _cmd_ask(update, ctx):     await _cmd_generic(update, ctx, "info_request")
async def _cmd_save(update, ctx):    await _cmd_generic(update, ctx, "info_upload")
async def _cmd_task(update, ctx):    await _cmd_generic(update, ctx, "task_todo")
async def _cmd_journal(update, ctx): await _cmd_generic(update, ctx, "journal")
async def _msg_free(update, ctx):    await _cmd_generic(update, ctx, None)


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


async def _msg_voice(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    from server import db
    from emergentintegrations.llm.openai.speech_to_text import OpenAISpeechToText
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
        stt = OpenAISpeechToText(api_key=os.environ["EMERGENT_LLM_KEY"])
        with open(mp3_path, "rb") as f:
            result = await stt.transcribe(file=f, model="whisper-1", response_format="json", language="it")
        transcript = getattr(result, "text", None) or (result.get("text") if isinstance(result, dict) else "")
        for p in (tmp_path, mp3_path):
            try:
                if p: os.unlink(p)
            except Exception: pass
        if not transcript.strip():
            await update.message.reply_text("🎙️ Non ho capito l'audio. Riprova più chiaramente.")
            return
        await update.message.reply_text(f"🎙️ _{transcript}_", parse_mode="Markdown")

        state = await _get_state(db, user["user_id"], chat_id)
        prev_ctx = state if _state_is_fresh(state) else None
        intent = await _classify_intent(transcript, prev_ctx)
        action = intent["action"]
        force_new = (intent["continuation"] == "new") or (prev_ctx is None) or (state.get("current_action") != action)
        await _run_and_reply(update, ctx, db, user, action, transcript, force_new=force_new)
    except Exception as e:
        logger.exception("voice message failed")
        await update.message.reply_text(f"⚠️ Errore trascrizione: {str(e)[:200]}")


def build_application() -> Application:
    app = Application.builder().token(bot_token()).build()
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("help", _cmd_help))
    app.add_handler(CommandHandler("end", _cmd_end))
    app.add_handler(CommandHandler("ask", _cmd_ask))
    app.add_handler(CommandHandler("save", _cmd_save))
    app.add_handler(CommandHandler("task", _cmd_task))
    app.add_handler(CommandHandler("journal", _cmd_journal))
    app.add_handler(CallbackQueryHandler(_on_callback))
    app.add_handler(MessageHandler(filters.VOICE, _msg_voice))
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
