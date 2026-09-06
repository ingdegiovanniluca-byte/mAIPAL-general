"""Telegram bot: long-polling worker that receives user messages and processes them via mAIPAL logic."""
import os
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from emergentintegrations.llm.chat import LlmChat, UserMessage

logger = logging.getLogger(__name__)

_application = None
_polling_task = None


def bot_token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "")


async def _process_action(db, user_doc: dict, action: str, content: str) -> str:
    """Reuse the same logic as web chat, non-streaming for Telegram."""
    from server import build_system_prompt, _parse_task_json, _create_task_or_todo  # local import to avoid cycles

    system = build_system_prompt(_to_user_pydantic(user_doc), action)
    conv_id = f"conv_tg_{uuid.uuid4().hex[:12]}"
    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=conv_id,
        system_message=system,
    ).with_model("anthropic", "claude-sonnet-5")

    # simple KB retrieval for info_request
    user_text = content
    if action == "info_request":
        terms = [t for t in content.lower().split() if len(t) > 2][:6]
        if terms:
            regex = "|".join(terms)
            chunks = await db.kb_chunks.find(
                {"user_id": user_doc["user_id"], "text": {"$regex": regex, "$options": "i"}},
                {"_id": 0}
            ).limit(4).to_list(4)
            if chunks:
                ctx = "\n\n".join([f"- {c.get('text','')[:400]}" for c in chunks])
                user_text = f"CONTESTO KB PERSONALE:\n{ctx}\n\nDOMANDA:\n{content}"

    answer = await chat.send_message(UserMessage(text=user_text))

    await db.conversations.insert_one({
        "conv_id": conv_id,
        "user_id": user_doc["user_id"],
        "action": action,
        "channel": "telegram",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_message": content,
        "agent_response": answer,
        "pipeline": {"claude": "ok", "n8n": "skip", "mongodb": "ok"},
    })

    if action == "info_upload":
        await db.kb_chunks.insert_one({
            "chunk_id": f"kb_{uuid.uuid4().hex[:12]}",
            "user_id": user_doc["user_id"],
            "text": content,
            "summary": answer,
            "conv_id": conv_id,
            "channel": "telegram",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    elif action == "task_todo":
        parsed = _parse_task_json(answer)
        if parsed:
            await _create_task_or_todo(user_doc["user_id"], parsed, conv_id)

    return answer


def _to_user_pydantic(doc):
    from server import User
    return User(**{k: doc.get(k) for k in [
        "user_id","email","name","picture","onboarded","profession","sector","verticals","interests","tone","created_at"
    ] if k in doc})


async def _get_user_by_chat(db, chat_id: int):
    return await db.users.find_one({"telegram_chat_id": chat_id}, {"_id": 0})


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
        await update.message.reply_text(f"✅ Ciao {user.get('name','')}! Sei connesso a mAIPAL.\n\nComandi:\n/ask <domanda>\n/save <informazione>\n/task <task>\n(oppure scrivi liberamente: capirò io l'azione)")
        return

    user = await _get_user_by_chat(db, chat_id)
    if user:
        await update.message.reply_text(f"Bentornato, {user.get('name','')}! Scrivi liberamente o usa /ask /save /task.")
    else:
        await update.message.reply_text(
            "👋 Ciao! Sono mAIPAL. Per collegare il tuo account:\n"
            "1) Apri mAIPAL → Impostazioni → Telegram\n"
            "2) Copia il codice di collegamento\n"
            "3) Torna qui e scrivi: /start <codice>"
        )


async def _cmd_help(update: Update, ctx):
    await update.message.reply_text(
        "Comandi mAIPAL:\n"
        "/ask <domanda> — interroga la tua knowledge base\n"
        "/save <info>   — salva un'informazione\n"
        "/task <task>   — crea task o to-do\n"
        "Se non usi un comando, provo a capire l'azione dal testo."
    )


def _infer_action(text: str) -> str:
    t = text.lower().strip()
    if any(t.startswith(k) for k in ("ricordami ", "aggiungi task", "task:", "todo ", "to-do", "domani ", "lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica")):
        return "task_todo"
    if any(k in t for k in ("salva", "annota", "prendi nota", "memorizza")):
        return "info_upload"
    return "info_request"


async def _cmd_generic(update: Update, ctx, forced_action=None):
    from server import db
    chat_id = update.effective_chat.id
    user = await _get_user_by_chat(db, chat_id)
    if not user:
        await update.message.reply_text("Devi prima collegare l'account: apri mAIPAL → Impostazioni → Telegram e usa /start <codice>.")
        return

    text = update.message.text or ""
    # strip command prefix if any
    if forced_action:
        parts = text.split(" ", 1)
        content = parts[1] if len(parts) > 1 else ""
        if not content.strip():
            await update.message.reply_text("Scrivi qualcosa dopo il comando.")
            return
        action = forced_action
    else:
        content = text
        action = _infer_action(text)

    await ctx.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        answer = await _process_action(db, user, action, content)
    except Exception as e:
        logger.exception("tg process error")
        await update.message.reply_text(f"⚠️ Errore: {str(e)[:200]}")
        return

    # Cap message length for Telegram
    if len(answer) > 3500:
        answer = answer[:3500] + "\n…"
    action_label = {"info_upload": "💾 Salvato", "info_request": "🔍 Risposta", "task_todo": "✅ Task/To-Do"}.get(action, "")
    await update.message.reply_text(f"{action_label}\n\n{answer}")


async def _cmd_ask(update, ctx): await _cmd_generic(update, ctx, "info_request")
async def _cmd_save(update, ctx): await _cmd_generic(update, ctx, "info_upload")
async def _cmd_task(update, ctx): await _cmd_generic(update, ctx, "task_todo")
async def _msg_free(update, ctx): await _cmd_generic(update, ctx, None)


def build_application() -> Application:
    app = Application.builder().token(bot_token()).build()
    app.add_handler(CommandHandler("start", _cmd_start))
    app.add_handler(CommandHandler("help", _cmd_help))
    app.add_handler(CommandHandler("ask", _cmd_ask))
    app.add_handler(CommandHandler("save", _cmd_save))
    app.add_handler(CommandHandler("task", _cmd_task))
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
    logger.info("Telegram bot polling started")


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
