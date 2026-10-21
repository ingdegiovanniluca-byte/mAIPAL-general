"""Collaboratori on Telegram: people outside the app (subcontractors, workers) who can only
write in the diario of the commesse they were enabled on, and ask about those commesse.

- Linking: "/start CODE" (the link in the invitation sends it by itself). The code is single
  use and lasts COLLAB_CODE_DAYS; when the admin gave a phone number, the collaborator must
  also share their Telegram contact and the number must match. The admin is told on Telegram.
- Every message from a collaborator's chat is handled here, before the bot's own handlers (a
  group -1 handler that stops the update): nothing else of the app - notes, tasks, lists,
  other commesse, Cerca - is ever reachable from a collaborator's chat.
- A message: on their only commessa, on the one it names, on the one the conversation is on,
  or they choose it with a button. Text, voice or photo. A question gets an answer from that
  commessa's data only (the client's phone and e-mail left out unless allowed); anything else
  goes in its diary with their name, with "Annulla" for COLLAB_UNDO_MINUTES. A problem they
  report is sent to the admin.
"""
import logging
import os
import tempfile
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
                      ReplyKeyboardRemove, Update)
from telegram.ext import ApplicationHandlerStop, ContextTypes

import site_presence as sp

logger = logging.getLogger(__name__)

TARGET_FRESH = timedelta(hours=2)   # the commessa of the conversation, for the next messages
HISTORY_KEEP = 8

HELP = ("Qui puoi fare due cose, sulle commesse che ti sono state abilitate:\n"
        "📒 scrivere cosa avete fatto (ore, materiali, problemi), anche a voce o con le foto;\n"
        "🔎 chiedere informazioni sulla commessa (es. «cosa manca da fare?», «quante ore abbiamo fatto?»).\n"
        "Se lavori su più commesse, nomina il cliente o i lavori, oppure scegli la commessa dai pulsanti.\n"
        "📌 Qui ti arrivano anche le attività e le milestone affidate a te, con i promemoria: quando sono fatte tocca ✅ Fatto.\n"
        "⏱️ Quando arrivi in cantiere tocca 📍 Sono arrivato, quando hai finito 📍 Ho finito: le ore vanno nel diario da sole "
        "(oppure scrivi «sono arrivato» / «ho finito alle 17:30»).")
PRIVACY_PLACE = ("📍 La tua posizione viene salvata solo quando tocchi il pulsante 📍 (all'arrivo e alla fine), "
                 "per segnare che eri in cantiere: non vieni seguito.")


def presence_keyboard(working: bool) -> ReplyKeyboardMarkup:
    """The button under the chat: it sends the phone's position, which starts or ends the work."""
    label = "📍 Ho finito" if working else "📍 Sono arrivato in cantiere"
    return ReplyKeyboardMarkup([[KeyboardButton(label, request_location=True)]], resize_keyboard=True, is_persistent=True)


async def _still_working(update: Update, recs: list):
    """After a reply that carries its own buttons (Annulla...): the 📍 Ho finito button can't ride
    on it, and phones often keep it folded away - with the time open it is sent again, under a
    line that says so."""
    from server import _open_presence, _local
    for r in recs:
        s_ = await _open_presence(r["id"])
        if s_:
            await _reply(update, f"⏱️ Tempo in cantiere aperto dalle {sp.hhmm(_local(s_['start_at']))} su «{s_['commessa_title']}»: "
                                 "quando hai finito tocca 📍 Ho finito.", reply_markup=presence_keyboard(True))
            return


async def _keyboard_for(recs: list) -> ReplyKeyboardMarkup:
    from server import _open_presence
    for r in recs:
        if await _open_presence(r["id"]):
            return presence_keyboard(True)
    return presence_keyboard(False)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _records(db, chat_id: int) -> list:
    return await db.collaborators.find({"telegram_chat_id": chat_id}, {"_id": 0}).to_list(10)


async def _reply(update: Update, text: str, **kw):
    if update.message:
        return await update.message.reply_text(text, **kw)
    if update.callback_query and update.callback_query.message:
        return await update.callback_query.message.reply_text(text, **kw)


# ---------------- linking ----------------

async def try_link(update: Update, ctx: ContextTypes.DEFAULT_TYPE, code: str) -> bool:
    """/start CODE with a collaborator's code -> linked (or asked to confirm the phone). False
    when the code is not a collaborator's (it may be an app user's)."""
    from server import db
    c = await db.collaborators.find_one({"code": (code or "").strip().upper()}, {"_id": 0})
    if not c:
        return False
    chat_id = update.effective_chat.id
    if not c.get("code_expires_at") or c["code_expires_at"] < _now().isoformat():
        await _reply(update, "⏳ Il codice è scaduto: chiedi un codice nuovo a chi ti ha invitato.")
        return True
    if await db.users.find_one({"telegram_chat_id": chat_id}, {"_id": 1}):
        await _reply(update, "Questo account Telegram è già collegato a un utente di mAIPAL: per collaborare usa un "
                             "altro account Telegram, oppure chiedi a chi ti ha invitato.")
        return True
    if c.get("phone"):
        await db.collaborators.update_one({"id": c["id"]}, {"$set": {"pending_chat_id": chat_id}})
        kb = ReplyKeyboardMarkup([[KeyboardButton("📱 Condividi il mio numero", request_contact=True)]],
                                 one_time_keyboard=True, resize_keyboard=True)
        await _reply(update, f"Ciao {c.get('first_name', '')}! Per sicurezza conferma il tuo numero di telefono con il "
                             "pulsante qui sotto.", reply_markup=kb)
        return True
    await _complete_link(update, c, chat_id)
    return True


async def on_contact(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> bool:
    """The contact shared to confirm the number: it must be their own and match the invitation."""
    from server import db, _phone_digits
    chat_id = update.effective_chat.id
    c = await db.collaborators.find_one({"pending_chat_id": chat_id}, {"_id": 0})
    if not c:
        return False
    contact = update.message.contact
    if contact.user_id and update.effective_user and contact.user_id != update.effective_user.id:
        await _reply(update, "Condividi il TUO numero, con il pulsante «Condividi il mio numero».")
        return True
    if _phone_digits(contact.phone_number)[-9:] != _phone_digits(c.get("phone"))[-9:]:
        await _reply(update, "Il numero non corrisponde a quello indicato da chi ti ha invitato: chiedigli di controllarlo.",
                     reply_markup=ReplyKeyboardRemove())
        return True
    if not c.get("code_expires_at") or c["code_expires_at"] < _now().isoformat():
        await _reply(update, "⏳ Il codice è scaduto: chiedi un codice nuovo a chi ti ha invitato.", reply_markup=ReplyKeyboardRemove())
        return True
    await _complete_link(update, c, chat_id)
    return True


async def _complete_link(update: Update, c: dict, chat_id: int):
    from server import db, _collab_targets, _collab_name, _notify_owner
    status = "suspended" if c.get("status") == "suspended" else "active"
    upd = {"telegram_chat_id": chat_id, "status": status, "linked_at": _now().isoformat(),
           "code": None, "code_expires_at": None, "pending_chat_id": None}
    await db.collaborators.update_one({"id": c["id"]}, {"$set": upd})
    c.update(upd)
    targets = await _collab_targets(c)
    jobs = "\n".join(f"• {v['title']} — {v['client_name']}" for _o, _cl, v in targets) or "nessuna, per ora"
    await _reply(update,
                 f"✅ Ciao {c.get('first_name', '')}, sei collegato a mAIPAL.\n\n{HELP}\n\nLe tue commesse:\n{jobs}\n\n"
                 "ℹ️ Quello che scrivi qui viene salvato nel diario delle commesse con il tuo nome, ed è visibile a chi ti ha "
                 f"invitato. {PRIVACY_PLACE} Per correggere o cancellare i tuoi dati rivolgiti a lui.",
                 reply_markup=presence_keyboard(False))
    owner = targets[0][0] if targets else None
    if owner is None:
        from server import User
        doc = await db.users.find_one({"user_id": c["owner_user_id"]}, {"_id": 0})
        owner = User(**doc) if doc else None
    if owner:
        who = _collab_name(c) + (f" ({c['company']})" if c.get("company") else "")
        await _notify_owner(owner, f"✅ {who} si è collegato a mAIPAL su Telegram come collaboratore.")


# ---------------- messages ----------------

async def _transcribe(ctx, file_id: str, owner_user_id: str, org_id: Optional[str]) -> str:
    from llm_integrations import OpenAISpeechToText
    stt = OpenAISpeechToText(api_key=os.environ.get("OPENAI_API_KEY"))
    tmp_path = mp3_path = None
    try:
        tg_file = await ctx.bot.get_file(file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            tmp_path = tmp.name
        await tg_file.download_to_drive(custom_path=tmp_path)
        mp3_path = tmp_path.replace(".ogg", ".mp3")
        proc = await asyncio.create_subprocess_exec("ffmpeg", "-y", "-loglevel", "error", "-i", tmp_path, "-ac", "1",
                                                    "-ar", "16000", "-b:a", "64k", mp3_path,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await proc.communicate()
        with open(mp3_path, "rb") as f:
            result = await stt.transcribe(file=f, model="whisper-1", response_format="verbose_json", language="it")
        stt.record_deferred(user_id=owner_user_id, feature="diario", channel="telegram", trigger="utente", org_id=org_id)
        return (getattr(result, "text", None) or (result.get("text") if isinstance(result, dict) else "") or "").strip()
    finally:
        for p in (tmp_path, mp3_path):
            try:
                if p:
                    os.unlink(p)
            except Exception:
                pass


def _target_buttons(targets: list) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"{v['title']} · {v['client_name']}"[:60], callback_data=f"clc:{v['id']}")]
                                 for _o, _cl, v in targets[:10]])


def _choose(rec: dict, content: str, targets: list) -> Optional[tuple]:
    """The commessa a message is about: the only one, the one it names, or the conversation's."""
    import retrieval
    if len(targets) == 1:
        return targets[0]
    by_id = {v["id"]: t for t in targets for v in [t[2]]}
    score, matched = retrieval._match_scored(content, [(v["id"], f"{v['client_name']} {v['title']}") for _o, _cl, v in targets])
    if matched and len(matched) == 1 and retrieval._is_strong_match(score, 1):
        return by_id[matched[0]]
    st = rec.get("tg_state") or {}
    if st.get("target") in by_id and st.get("at", "") >= (_now() - TARGET_FRESH).isoformat():
        return by_id[st["target"]]
    return None


async def _over_limit(db, rec: dict) -> bool:
    from server import COLLAB_DAILY_LIMIT
    today = _now().date().isoformat()
    n = (rec.get("msg_count") or 0) + 1 if rec.get("msg_day") == today else 1
    await db.collaborators.update_one({"id": rec["id"]}, {"$set": {"msg_day": today, "msg_count": n,
                                                                    "last_message_at": _now().isoformat()}})
    return n > COLLAB_DAILY_LIMIT


async def process(update: Update, rec: dict, target: tuple, content: str, images: Optional[list],
                  material_choice: Optional[str] = None):
    """Write in the commessa's diary, or answer the question about it."""
    from server import db, _save_job_log, _collab_answer, _collab_name, _notify_owner, COLLAB_UNDO_MINUTES
    owner, _clienti, view = target
    author = {"id": rec["id"], "first_name": rec.get("first_name") or "", "name": _collab_name(rec), "company": rec.get("company") or ""}
    await db.collaborators.update_one({"id": rec["id"]}, {"$set": {"tg_state": {"target": view["id"], "at": _now().isoformat()},
                                                                    "pending": None}})
    try:
        res = await _save_job_log(owner, content, images=images or None, commessa_id=view["id"], channel="telegram", author=author,
                                  material_choice=material_choice)
    except Exception as e:
        logger.exception("collaborator job log failed")
        await _reply(update, f"⚠️ Non sono riuscito a salvarlo: {str(getattr(e, 'detail', e))[:200]}")
        return
    if res["status"] == "planned":   # only things to take: a reminder, nothing in the diary
        ids = ",".join(t["id"] for t in res["todos"][:2])
        await _reply(update, res["message"], reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"↩️ Annulla ({COLLAB_UNDO_MINUTES} min)", callback_data=f"clt:{ids}")]]))
        await _still_working(update, [rec])
        return
    if res["status"] == "material_doubt":   # "10 scatole 503": used today or to take? asked
        await db.collaborators.update_one({"id": rec["id"]}, {"$set": {"pending_material": {"text": content, "images": images or [], "commessa_id": view["id"]}}})
        await _reply(update, res["message"], reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🧰 Usati oggi", callback_data="cmat:usato"), InlineKeyboardButton("📌 Da prendere", callback_data="cmat:da_prendere")]]))
        return
    if res["status"] == "ok":
        log = res["log"]
        kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"↩️ Annulla ({COLLAB_UNDO_MINUTES} min)", callback_data=f"clu:{log['id']}")]])
        await _reply(update, res["message"], reply_markup=kb)
        await _still_working(update, [rec])
        if log.get("problems"):
            who = _collab_name(rec) + (f" ({rec['company']})" if rec.get("company") else "")
            await _notify_owner(owner, f"⚠️ {who} segnala su «{view['title']}» — {view['client_name']}:\n"
                                       + "\n".join(f"• {p}" for p in log["problems"]))
        return
    if res["status"] == "question":
        history = list(rec.get("tg_history") or [])
        try:
            answer = await _collab_answer(rec, owner, view, content, history)
        except Exception:
            logger.exception("collaborator question failed")
            answer = "Non sono riuscito a rispondere, riprova tra poco."
        history = (history + [{"role": "user", "content": content}, {"role": "assistant", "content": answer}])[-HISTORY_KEEP:]
        await db.collaborators.update_one({"id": rec["id"]}, {"$set": {"tg_history": history}})
        await _reply(update, f"🔎 «{view['title']}» — {view['client_name']}\n{answer}", reply_markup=await _keyboard_for([rec]))
        return
    await _reply(update, "📒 " + (res.get("message") or "Non l'ho salvato: riscrivilo, per favore."), reply_markup=await _keyboard_for([rec]))


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE, recs: list):
    from server import db, _collab_targets, _image_bytes_to_journal_data_uri
    msg = update.message
    active = [r for r in recs if r.get("status") == "active"]
    if not active:
        await _reply(update, "Il tuo accesso a mAIPAL è sospeso: rivolgiti a chi ti ha invitato.")
        return
    rec = active[0]
    text = (msg.text or "").strip()
    if text.startswith("/") and text.split()[0].lower() not in ("/inizio", "/fine"):
        cmd = text.split()[0].lower()
        await _reply(update, (HELP if cmd in ("/help", "/start", "/aiuto") else
                     "Qui puoi solo scrivere nel diario delle tue commesse o chiedere informazioni su di esse.\n\n" + HELP)
                     + "\n\n" + PRIVACY_PLACE, reply_markup=await _keyboard_for(active))
        return
    targets = [t for r in active for t in await _collab_targets(r)]
    if not targets:
        await _reply(update, "Al momento non hai commesse abilitate (o sono chiuse): rivolgiti a chi ti ha invitato.")
        return
    command = sp.parse_command(text) if text else None
    place = getattr(msg, "location", None)
    if place or command:
        await presence(update, active, targets, command, {"lat": place.latitude, "lon": place.longitude} if place else None)
        return
    if await _over_limit(db, rec):
        await _reply(update, "Hai raggiunto il numero massimo di messaggi per oggi: riprova domani.")
        return
    await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    images = []
    if msg.voice:
        try:
            content = await _transcribe(ctx, msg.voice.file_id, targets[0][0].user_id, targets[0][0].org_id)
        except Exception:
            logger.exception("collaborator voice failed")
            content = ""
        if not content:
            await _reply(update, "🎙️ Non ho capito l'audio, riprova.")
            return
        await _reply(update, f"🎙️ {content}", reply_markup=await _keyboard_for(active))
    elif msg.photo:
        try:
            raw = await (await ctx.bot.get_file(msg.photo[-1].file_id)).download_as_bytearray()
            images = [_image_bytes_to_journal_data_uri(bytes(raw))]
        except Exception as e:
            logger.exception("collaborator photo failed")
            await _reply(update, f"⚠️ Errore con la foto: {str(e)[:150]}")
            return
        content = (msg.caption or "").strip() or "Foto dal cantiere"
    elif text:
        content = text
    else:
        await _reply(update, "Mandami un testo, un messaggio vocale o una foto.")
        return
    target = _choose(rec, content, targets)
    if not target:   # working on a commessa (time open): a message naming no other goes there
        from server import _open_presence
        for r in active:
            s_ = await _open_presence(r["id"])
            target = next((t for t in targets if s_ and t[2]["id"] == s_["commessa_id"]), None)
            if target:
                rec = r
                break
    if not target:
        await db.collaborators.update_one({"id": rec["id"]}, {"$set": {"pending": {"text": content, "images": images}}})
        await _reply(update, "📒 Di quale commessa si tratta?", reply_markup=_target_buttons(targets))
        return
    await process(update, rec, target, content, images)


def _pause_buttons(log_id: str) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(f"⏸️ −{sp.fmt_duration(m)}", callback_data=f"cpz:{log_id}:{m}") for m in sp.PAUSES]
    return InlineKeyboardMarkup([row + [InlineKeyboardButton("Nessuna pausa", callback_data=f"cpz:{log_id}:0")]])


async def presence(update: Update, active: list, targets: list, command: Optional[dict], loc: Optional[dict]):
    """"Sono arrivato" / "ho finito" (said, or the 📍 button that sends the position): the start
    or the end of the work. Without a word, the position starts when nothing is open, ends otherwise."""
    from server import db, _open_presence, _presence_start, _presence_stop, _commessa_geo, LOCAL_TZ
    now = _now()
    at = now
    if command and command.get("at"):
        at = datetime.combine(now.astimezone(LOCAL_TZ).date(), command["at"], tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        if at > now + timedelta(minutes=5):
            await _reply(update, f"Le {command['at'].strftime('%H:%M')} non sono ancora arrivate: scrivimi l'ora giusta.")
            return
    open_rec = None
    for r in active:
        if await _open_presence(r["id"]):
            open_rec = r
            break
    action = command["action"] if command else ("stop" if open_rec else "start")
    if action == "stop":
        rec = open_rec or active[0]
        answer, log_id = await _presence_stop(rec, at, loc)
        await _reply(update, answer, reply_markup=await _keyboard_for(active))
        if log_id:
            await _reply(update, "Hai fatto pause?", reply_markup=_pause_buttons(log_id))
        return
    if open_rec:   # already started: said (whatever the commessa)
        await _reply(update, await _presence_start(open_rec, None, None, at, loc), reply_markup=await _keyboard_for(active))
        return
    # start: the commessa - the only one, the nearest to the position, the one named, or asked
    target = targets[0] if len(targets) == 1 else None
    if not target and loc:
        sites = []
        for t in targets[:12]:
            geo = await _commessa_geo(t[2]["id"], t[2])
            if geo:
                sites.append((t[2]["id"], geo))
        hit = sp.nearest(loc, sites)
        target = next((t for t in targets if hit and t[2]["id"] == hit[0]), None)
    if not target and command and command.get("rest"):
        target = _choose({}, command["rest"], targets)
    rec = next((r for r in active if target and target[0].user_id == r["owner_user_id"]), active[0])
    if not target:
        await db.collaborators.update_one({"id": rec["id"]}, {"$set": {"pending_checkin": {"at": at.isoformat(), "loc": loc}}})
        await _reply(update, "⏱️ Su quale commessa inizi?", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{v['title']} · {v['client_name']}"[:60], callback_data=f"cin:{v['id']}")] for _o, _cl, v in targets[:10]]))
        return
    answer = await _presence_start(rec, target[0], target[2], at, loc)
    await _reply(update, answer, reply_markup=await _keyboard_for(active))


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE, recs: list):
    from server import db, _collab_targets, COLLAB_UNDO_MINUTES
    q = update.callback_query
    data = q.data or ""
    try:
        await q.answer()
    except Exception:
        pass
    active = [r for r in recs if r.get("status") == "active"]
    if not active:
        await _reply(update, "Il tuo accesso a mAIPAL è sospeso: rivolgiti a chi ti ha invitato.")
        return
    rec = active[0]
    if data.startswith("clc:"):
        cid = data[4:]
        targets = [t for r in active for t in await _collab_targets(r)]
        target = next((t for t in targets if t[2]["id"] == cid), None)
        if not target:
            await _reply(update, "Questa commessa non è più abilitata per te.")
            return
        pending = rec.get("pending") or {}
        if pending.get("text"):
            await process(update, rec, target, pending["text"], pending.get("images") or [])
            return
        await db.collaborators.update_one({"id": rec["id"]}, {"$set": {"tg_state": {"target": cid, "at": _now().isoformat()}}})
        await _reply(update, f"Ok, «{target[2]['title']}»: scrivimi (anche a voce) cosa avete fatto, o cosa vuoi sapere.")
        return
    if data.startswith("cin:"):   # the commessa of a start
        from server import _presence_start
        targets = [t for r in active for t in await _collab_targets(r)]
        target = next((t for t in targets if t[2]["id"] == data[4:]), None)
        rec_for = next((r for r in active if target and target[0].user_id == r["owner_user_id"]), rec)
        pend = rec_for.get("pending_checkin") or rec.get("pending_checkin")
        if not target or not pend:
            await _reply(update, "Riprova: tocca 📍 Sono arrivato in cantiere o scrivi «sono arrivato».")
            return
        await db.collaborators.update_one({"id": rec_for["id"]}, {"$set": {"pending_checkin": None}})
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        answer = await _presence_start(rec_for, target[0], target[2], datetime.fromisoformat(pend["at"]), pend.get("loc"))
        await _reply(update, answer, reply_markup=await _keyboard_for(active))
        return
    if data.startswith("cpz:"):   # a pause taken out of the hours just counted
        from server import _presence_pause, PRESENCE_GONE
        _, log_id, minutes = (data.split(":") + ["", "0"])[:3]
        answer = PRESENCE_GONE
        for r in active:
            answer = await _presence_pause(r, log_id, int(minutes or 0))
            if answer != PRESENCE_GONE:
                break
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _reply(update, answer)
        return
    if data.startswith("cldone:"):   # "✅ Fatto" under a To Do / milestone given to them
        from server import _collab_mark_done, COLLAB_NOT_YOURS as NOT_YOURS
        _, kind, item_id = (data.split(":", 2) + ["", ""])[:3]
        answer = NOT_YOURS
        for r in active:   # the record (owner) the item belongs to
            answer = await _collab_mark_done(r, kind, item_id)
            if answer != NOT_YOURS:
                break
        pressed_on = getattr(q.message, "message_id", None)
        pinned = bool(pressed_on) and any((r.get("day_pin") or {}).get("message_id") == pressed_on for r in active)
        if answer != NOT_YOURS and not pinned:   # the pinned message of the day keeps its other buttons (it is edited)
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        await _reply(update, answer)
        return
    if data.startswith("cmat:"):   # the answer to "usati oggi o da prendere?"
        choice = data[5:]
        pend = rec.get("pending_material") or {}
        targets = [t for r in active for t in await _collab_targets(r)]
        target = next((t for t in targets if t[2]["id"] == pend.get("commessa_id")), None)
        if not pend.get("text") or not target or choice not in ("usato", "da_prendere"):
            await _reply(update, "Riscrivimelo, per favore.")
            return
        await db.collaborators.update_one({"id": rec["id"]}, {"$set": {"pending_material": None}})
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await process(update, rec, target, pend["text"], pend.get("images") or [], material_choice=choice)
        return
    if data.startswith("clt:"):   # a reminder "Da prendere" undone
        limit = (_now() - timedelta(minutes=COLLAB_UNDO_MINUTES)).isoformat()
        mine = {r["id"] for r in recs}
        gone = 0
        for tid in data[4:].split(","):
            t = await db.job_todos.find_one({"id": tid}, {"_id": 0, "collaborator_id": 1, "created_at": 1})
            if t and t.get("collaborator_id") in mine and t.get("created_at", "") >= limit:
                await db.job_todos.delete_one({"id": tid})
                gone += 1
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _reply(update, "↩️ Promemoria annullato." if gone else
                     f"Sono passati più di {COLLAB_UNDO_MINUTES} minuti: per correggerlo rivolgiti a chi ti ha invitato.")
        return
    if data.startswith("clu:"):
        log = await db.job_logs.find_one({"id": data[4:]}, {"_id": 0, "id": 1, "collaborator_id": 1, "created_at": 1,
                                                            "described_at": 1, "before_description": 1})
        mine = log and log.get("collaborator_id") in {r["id"] for r in recs}
        limit = (_now() - timedelta(minutes=COLLAB_UNDO_MINUTES)).isoformat()
        if mine and log.get("before_description") and (log.get("described_at") or "") >= limit:
            # the last thing written was the description of a photo: only that goes, the photo stays
            await db.job_logs.update_one({"id": log["id"]}, {"$set": {**log["before_description"], "embedding": None},
                                                             "$unset": {"described_at": "", "before_description": ""}})
            try:
                await q.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
            await _reply(update, "↩️ Descrizione annullata: nel diario resta la foto.")
            return
        fresh = log and log.get("created_at", "") >= limit
        if not mine:
            await _reply(update, "Questa voce non c'è più.")
            return
        if not fresh:
            await _reply(update, f"Sono passati più di {COLLAB_UNDO_MINUTES} minuti: per correggerla rivolgiti a chi ti ha invitato.")
            return
        await db.job_logs.delete_one({"id": log["id"]})
        await db.job_photos.delete_many({"log_id": log["id"]})
        await db.job_todos.delete_many({"from_log_id": log["id"]})   # the reminder written with it, too
        try:
            await q.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _reply(update, "↩️ Voce annullata: non è più nel diario.")


# ---------------- the gate (group -1: before everything else) ----------------

async def gate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Messages: a collaborator's code, contact or message is handled here and the update stops."""
    from server import db
    msg = update.message
    if not msg or not update.effective_chat:
        return
    text = (msg.text or "").strip()
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        if len(parts) == 2 and await try_link(update, ctx, parts[1]):
            raise ApplicationHandlerStop
    if msg.contact:
        if await on_contact(update, ctx):
            raise ApplicationHandlerStop
        return
    recs = await _records(db, update.effective_chat.id)
    if not recs:
        return
    try:
        await handle_message(update, ctx, recs)
    except ApplicationHandlerStop:
        raise
    except Exception:
        logger.exception("collaborator message failed")
        await _reply(update, "⚠️ Qualcosa è andato storto, riprova tra poco.")
    raise ApplicationHandlerStop


async def gate_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Buttons: a collaborator's chat only ever gets the collaborator's buttons."""
    from server import db
    if not update.callback_query or not update.effective_chat:
        return
    recs = await _records(db, update.effective_chat.id)
    if not recs:
        return
    try:
        await handle_callback(update, ctx, recs)
    except Exception:
        logger.exception("collaborator button failed")
    raise ApplicationHandlerStop
