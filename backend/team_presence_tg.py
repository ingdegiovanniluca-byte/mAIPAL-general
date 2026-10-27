"""Presence on site for the app's users (the owner, the colleagues), on the main Telegram bot:
the same as the collaborators' (collab_telegram.py) - "sono arrivato" / "ho finito (alle 17:30)",
or the 📍 button that sends the position (/cantiere shows it) - on the commesse of their Clienti
list that are not closed. Also: the pauses, the evening's "are you still there?" and the answer
to "how did it go?", which goes to that commessa's diary.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

import site_presence as sp
from collab_telegram import presence_keyboard

logger = logging.getLogger(__name__)

NOTE_VALID = timedelta(hours=12)   # how long "how did it go?" waits for its answer


def _now() -> datetime:
    return datetime.now(timezone.utc)


def is_artigiano(user_doc: dict) -> bool:
    return (user_doc or {}).get("business_vertical") == "artigiano"


async def _worker_and_targets(user_doc: dict):
    """(the user as "who is on site", the owner of their Clienti list, [commessa views not closed])."""
    from server import db, User, _clienti_list, _all_commesse, _user_worker
    user = User(**user_doc)
    clienti = await _clienti_list(user)
    if not clienti:
        return _user_worker(user_doc), None, [], None
    owner_doc = await db.users.find_one({"user_id": clienti.get("user_id")}, {"_id": 0}) or user_doc
    commesse, _ = await _all_commesse(clienti)
    open_ = [c for c in commesse if c["stato"] != "chiusa"]
    open_.sort(key=lambda c: (c["stato"] != "in corso", c["title"].lower()))
    return _user_worker(user_doc, clienti.get("user_id")), User(**owner_doc), open_, clienti


async def _keyboard(worker: dict):
    from server import _open_presence
    return presence_keyboard(bool(await _open_presence(worker["id"])))


def _pause_buttons(log_id: str) -> InlineKeyboardMarkup:
    row = [InlineKeyboardButton(f"⏸️ −{sp.fmt_duration(m)}", callback_data=f"cpz:{log_id}:{m}") for m in sp.PAUSES]
    return InlineKeyboardMarkup([row + [InlineKeyboardButton("Nessuna pausa", callback_data=f"cpz:{log_id}:0")]])


def _pick(targets: list, rest: str) -> Optional[dict]:
    """The commessa named after "sono arrivato" ("dai Rossi", "al bagno")."""
    from server import _norm_title
    words = [w for w in _norm_title(rest).split() if len(w) >= 3 and w not in ("dai", "dal", "dalla", "presso", "cantiere")]
    if not words:
        return None
    hits = [c for c in targets if any(w in _norm_title(f"{c['title']} {c['client_name']}").split() for w in words)]
    return hits[0] if len(hits) == 1 else None


async def cmd_cantiere(update: Update, ctx) -> None:
    from server import db, _open_presence, _local
    from telegram_bot import _get_user_by_chat
    user_doc = await _get_user_by_chat(db, update.effective_chat.id)
    if not user_doc:
        await update.message.reply_text("Devi prima collegare l'account: apri mAIPAL → Impostazioni → Telegram e usa /start <codice>.")
        return
    worker, _owner, targets, _cl = await _worker_and_targets(user_doc)
    s_ = await _open_presence(worker["id"])
    if s_:
        text = (f"⏱️ Sei in cantiere su «{s_['commessa_title']}» dalle {sp.hhmm(_local(s_['start_at']))}: "
                "quando hai finito tocca 📍 Ho finito (o scrivi «ho finito»).")
    elif not targets:
        text = "Non hai commesse aperte: le crei nella lista Clienti dell'app."
    else:
        text = ("📍 Quando arrivi in cantiere tocca *Sono arrivato in cantiere*, quando hai finito *Ho finito*: le ore vanno nel diario "
                "della commessa. Puoi anche scrivere «sono arrivato dai Rossi» o «ho finito alle 17:30».\n"
                "La posizione viene salvata solo in quei due momenti.")
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=presence_keyboard(bool(s_)))


async def try_presence(update: Update, ctx, user_doc: dict, text: str = "", loc: Optional[dict] = None) -> bool:
    """A presence command or the position, for an artigiano: handled here (-> True)."""
    if not is_artigiano(user_doc):
        return False
    command = sp.parse_command(text) if text else None
    if not command and not loc:
        return False
    from server import (db, LOCAL_TZ, _open_presence, _presence_start, _presence_stop, _commessa_geo)
    from telegram_bot import _set_state
    worker, owner, targets, clienti = await _worker_and_targets(user_doc)
    now = _now()
    at = now
    if command and command.get("at"):
        at = datetime.combine(now.astimezone(LOCAL_TZ).date(), command["at"], tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        if at > now + timedelta(minutes=5):
            await update.message.reply_text(f"Le {command['at'].strftime('%H:%M')} non sono ancora arrivate: scrivimi l'ora giusta.")
            return True
    open_ = await _open_presence(worker["id"])
    action = command["action"] if command else ("stop" if open_ else "start")
    if action == "stop":
        if open_:
            worker["owner_user_id"] = open_.get("owner_user_id") or worker["owner_user_id"]
        answer, log_id = await _presence_stop(worker, at, loc)
        await update.message.reply_text(answer, reply_markup=await _keyboard(worker))
        if log_id:
            await update.message.reply_text("Hai fatto pause?", reply_markup=_pause_buttons(log_id))
        return True
    if open_:   # already started: said
        await update.message.reply_text(await _presence_start(worker, None, None, at, loc), reply_markup=await _keyboard(worker))
        return True
    if not targets:
        await update.message.reply_text("Non hai commesse aperte: le crei nella lista Clienti dell'app.")
        return True
    # the commessa: the only one, the nearest to the position, the one named, or asked
    target = targets[0] if len(targets) == 1 else None
    if not target and loc:
        sites = []
        for c in targets[:15]:
            geo = await _commessa_geo(c["id"], c)
            if geo:
                sites.append((c["id"], geo))
        hit = sp.nearest(loc, sites)
        target = next((c for c in targets if hit and c["id"] == hit[0]), None)
    if not target and command and command.get("rest"):
        target = _pick(targets, command["rest"])
    if not target:
        await _set_state(db, update.effective_chat.id, user_doc["user_id"], pending_checkin={"at": at.isoformat(), "loc": loc})
        await update.message.reply_text("⏱️ Su quale commessa inizi?", reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton(f"{c['title']} · {c['client_name']}"[:60], callback_data=f"upin:{c['id']}")] for c in targets[:10]]))
        return True
    answer = await _presence_start(worker, owner, target, at, loc)
    await update.message.reply_text(answer, reply_markup=await _keyboard(worker))
    return True


async def handle_callback(update: Update, ctx, user_doc: dict, data: str) -> bool:
    """The buttons of the presence (-> True when it was one of them)."""
    if not data.split(":", 1)[0] in ("upin", "cpz", "pls", "ple"):
        return False
    from server import (db, _presence_start, _presence_pause, PRESENCE_GONE, _presence_late_answer, _presence_left_at,
                        _presence_left_buttons, _open_presence)
    from telegram_bot import _get_state, _set_state
    q = update.callback_query
    chat_id = q.message.chat.id
    send = lambda text, kb=None: ctx.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb)
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
    worker, owner, targets, _cl = await _worker_and_targets(user_doc)
    if data.startswith("upin:"):   # the commessa of a start
        state = await _get_state(db, user_doc["user_id"], chat_id)
        pend = state.get("pending_checkin")
        target = next((c for c in targets if c["id"] == data[5:]), None)
        if not target or not pend:
            await send("Riprova: tocca 📍 Sono arrivato in cantiere o scrivi «sono arrivato».")
            return True
        await _set_state(db, chat_id, user_doc["user_id"], pending_checkin=None)
        if await _open_presence(worker["id"]):
            await send(await _presence_start(worker, None, None, _now(), None), await _keyboard(worker))
            return True
        await send(await _presence_start(worker, owner, target, datetime.fromisoformat(pend["at"]), pend.get("loc")), await _keyboard(worker))
        return True
    if data.startswith("cpz:"):   # a pause taken out of the hours just counted
        _, log_id, minutes = (data.split(":") + ["", "0"])[:3]
        await send(await _presence_pause(worker, log_id, int(minutes or 0)))
        return True
    if data.startswith("pls:"):
        _, yn, sid = (data.split(":") + ["", ""])[:3]
        answer = await _presence_late_answer(worker, sid, yn == "y")
        kb = await _presence_left_buttons(sid) if yn == "n" and not answer.startswith("Il tempo") else None
        await send(answer, kb)
        return True
    _, sid, hhmm = (data.split(":") + ["", ""])[:3]
    answer, log_id = await _presence_left_at(worker, sid, hhmm)
    await send(answer, await _keyboard(worker))
    if log_id:
        await send("Hai fatto pause?", _pause_buttons(log_id))
    return True


async def try_note(update_or_query, ctx, user_doc: dict, state: dict, content: str) -> bool:
    """The answer to "how did it go?": an entry in that commessa's diary (-> True)."""
    pend = state.get("pending_presence_note") or {}
    if not pend.get("commessa_id"):
        return False
    from server import db
    from telegram_bot import _set_state, _run_job_log_flow
    chat_id = update_or_query.effective_chat.id
    await _set_state(db, chat_id, user_doc["user_id"], pending_presence_note=None)
    try:
        fresh = _now() - datetime.fromisoformat(pend["at"]) < NOTE_VALID
    except (KeyError, ValueError):
        fresh = False
    if not fresh:
        return False
    await _run_job_log_flow(update_or_query, ctx, db, user_doc, content, commessa_id=pend["commessa_id"])
    return True


async def on_location(update: Update, ctx) -> None:
    from server import db
    from telegram_bot import _get_user_by_chat
    user_doc = await _get_user_by_chat(db, update.effective_chat.id)
    if not user_doc:
        return
    place = update.message.location
    if not await try_presence(update, ctx, user_doc, "", {"lat": place.latitude, "lon": place.longitude}):
        await update.message.reply_text("Ho ricevuto la posizione, ma la uso solo per le presenze in cantiere (artigiani).")
