import asyncio, os, sys, copy
from datetime import datetime, timezone, timedelta
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import server, scheduled_actions as sa, list_updates as lu, usage_tracking as ut, retrieval

def _get(doc, k):
    return doc.get(k)

def _match(doc, q):
    for k, v in (q or {}).items():
        if k == "$or":
            if not any(_match(doc, s) for s in v): return False
            continue
        if k == "$and":
            if not all(_match(doc, s) for s in v): return False
            continue
        val = _get(doc, k)
        if isinstance(v, dict):
            for op, arg in v.items():
                if op == "$in" and not (any(x in arg for x in val) if isinstance(val, list) else val in arg): return False
                if op == "$nin" and val in arg: return False
                if op == "$ne" and val == arg: return False
                if op == "$gte" and (val is None or val < arg): return False
                if op == "$gt" and (val is None or val <= arg): return False
                if op == "$lte" and (val is None or val > arg): return False
                if op == "$lt" and (val is None or val >= arg): return False
                if op == "$exists" and ((k in doc) != arg): return False
        elif val != v:
            return False
    return True

class Cur:
    def __init__(s, d): s.d = d
    def sort(s, f, dr=1): s.d = sorted(s.d, key=lambda x: x.get(f) or "", reverse=dr == -1); return s
    async def to_list(s, n): return [copy.deepcopy(x) for x in s.d[:n]]
    def __aiter__(s):
        s._it = iter(copy.deepcopy(s.d)); return s
    async def __anext__(s):
        try: return next(s._it)
        except StopIteration: raise StopAsyncIteration

class R:
    def __init__(s, n): s.modified_count = n; s.deleted_count = n

class Coll:
    def __init__(s): s.docs = []
    def find(s, q=None, proj=None): return Cur([d for d in s.docs if _match(d, q)])
    async def find_one(s, q=None, proj=None):
        for d in s.docs:
            if _match(d, q): return copy.deepcopy(d)
    async def insert_one(s, d): s.docs.append(copy.deepcopy(d))
    async def count_documents(s, q): return sum(1 for d in s.docs if _match(d, q))
    async def update_one(s, q, u, upsert=False):
        for d in s.docs:
            if _match(d, q):
                d.update(u.get("$set", {}))
                for k in u.get("$unset", {}): d.pop(k, None)
                for k, v in u.get("$addToSet", {}).items():
                    arr = d.setdefault(k, [])
                    if v not in arr: arr.append(v)
                for k, v in u.get("$pull", {}).items():
                    out = v.get("$in") if isinstance(v, dict) else [v]
                    d[k] = [x for x in d.get(k, []) if x not in out]
                for k, v in u.get("$inc", {}).items(): d[k] = (d.get(k) or 0) + v
                for k, v in u.get("$push", {}).items():
                    arr = d.setdefault(k, [])
                    if isinstance(v, dict) and "$each" in v:
                        arr.extend(v["$each"]); 
                        if "$slice" in v: d[k] = arr[v["$slice"]:]
                    else: arr.append(v)
                return R(1)
        if upsert:
            d = {k: v for k, v in q.items() if not isinstance(v, dict)}; d.update(u.get("$set", {})); s.docs.append(d)
        return R(0)
    async def insert_many(s, ds): s.docs.extend(copy.deepcopy(d) for d in ds)
    async def update_many(s, q, u):
        n = 0
        for d in s.docs:
            if _match(d, q):
                d.update(u.get("$set", {})); n += 1
                for k, v in u.get("$pull", {}).items():
                    out = v.get("$in") if isinstance(v, dict) else [v]
                    d[k] = [x for x in d.get(k, []) if x not in out]
        return R(n)
    async def delete_one(s, q):
        for i, d in enumerate(s.docs):
            if _match(d, q): s.docs.pop(i); return R(1)
        return R(0)
    async def delete_many(s, q):
        n = len(s.docs); s.docs = [d for d in s.docs if not _match(d, q)]; return R(n - len(s.docs))

class DB:
    def __getattr__(s, n):
        c = Coll(); setattr(s, n, c); return c

db = DB()
server.db = db
ut.fire_and_forget_feature_event = lambda **k: None
ut.fire_and_forget_llm_call = lambda **k: None
from llm_integrations import TextDelta, StreamDone
import job_logs as jl, telegram_bot as tg, retrieval, embeddings as emb
import scheduled_actions as sa
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77}
db.users.docs.append(dict(U))
tg.bot_token = lambda: "123:abc"
NOTICES = []
async def fake_send(chat_id, text):
    NOTICES.append((chat_id, text)); return True
server._send_telegram_text = fake_send
TOLD = []
async def fake_tell(c, text, done_data=None):   # a collaborator's message (with the "Fatto" button)
    if c.get("status") != "active" or not c.get("telegram_chat_id"):
        return False
    NOTICES.append((c["telegram_chat_id"], text)); TOLD.append((c["id"], text, done_data)); return True
server._tell_collaborator = fake_tell
async def no_emb(q): raise RuntimeError("offline")
emb.embed_query = no_emb
def said(hours=None, materials=None, problems=None, date=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web"):
        return {"kind": "nota", "doubt": "", "date": date or jl.today_local().isoformat(), "text": t,
                "hours": jl.clean_hours(hours or [], speaker), "materials": jl.clean_materials(materials or []),
                "problems": problems or [], "client": "", "commessa": ""}
    return f
ANSWERS = []
async def fake_answer(commessa, logs, reports, question, history, user_id=None, channel="web"):
    ANSWERS.append(commessa); return {"answer": "ok", "is_entry": False}
jl.answer = fake_answer

async def settle():
    for _ in range(5):
        await asyncio.sleep(0)

import collab_telegram as ct
import site_presence as sp

SITES = {"Via Roma 5, Torino": {"lat": 45.0703, "lon": 7.6869}, "Via Po 1, Torino": {"lat": 45.0680, "lon": 7.6950}}
GEOCODED = []
async def fake_geocode(addr):
    GEOCODED.append(addr); return SITES.get(addr)
sp.geocode = fake_geocode
PUSHED = []
server.push.fire_and_forget = lambda db_, uid, title, body, url="/", tag=None: PUSHED.append((uid, title, body))

class Loc:
    def __init__(s, lat, lon): s.latitude = lat; s.longitude = lon
class Msg:
    def __init__(s, text=None, loc=None):
        s.text = text; s.location = loc; s.voice = None; s.photo = None; s.caption = None; s.contact = None; s.replies = []
    async def reply_text(s, text, **kw): s.replies.append((text, kw.get("reply_markup")))
class Chat:
    id = 900
class Upd:
    def __init__(s, msg): s.message = msg; s.callback_query = None; s.effective_chat = Chat()
class Q:
    def __init__(s, data): s.data = data; s.message = Msg(); s.cleared = False
    async def answer(s): pass
    async def edit_message_reply_markup(s, reply_markup=None): s.cleared = True
class CbUpd:
    def __init__(s, data): s.message = None; s.callback_query = Q(data); s.effective_chat = Chat()

def recs():
    return [c for c in db.collaborators.docs if c.get("telegram_chat_id") == 900]
class _Bot:
    async def send_chat_action(s, **kw): pass
class Ctx:
    bot = _Bot()
async def say(text=None, loc=None):
    m = Msg(text, Loc(*loc) if loc else None)
    await ct.handle_message(Upd(m), Ctx(), recs())
    return m.replies
async def tap(data):
    u = CbUpd(data)
    await ct.handle_callback(u, None, recs())
    return u.callback_query.message.replies
def kb_label(markup):
    return markup.keyboard[0][0].text if markup is not None and hasattr(markup, "keyboard") else None

import team_presence_tg as tp
from fastapi import HTTPException

TG = []   # every Telegram message of the presence: (chat, text, buttons)
async def fake_tg_send(chat_id, text, kb=None):
    if not chat_id:
        return False
    TG.append((chat_id, text, kb)); return True
server._tg_send = fake_tg_send
_Bot.send_message = lambda s, chat_id, text, reply_markup=None, **kw: _sent(chat_id, text, reply_markup)
async def _sent(chat_id, text, kb):
    TG.append((chat_id, text, kb)); return None
class Chat77:
    id = 77
class Upd77:
    def __init__(s, msg): msg.chat = Chat77(); s.message = msg; s.callback_query = None; s.effective_chat = Chat77()
class Q77(Q):
    def __init__(s, data): super().__init__(data); s.message = type("M", (), {"chat": Chat77()})()
class CbUpd77:
    def __init__(s, data): s.message = None; s.callback_query = Q77(data); s.effective_chat = Chat77()
def me_doc():
    return next(u for u in db.users.docs if u["user_id"] == "u1")
async def me_say(text=None, loc=None):
    m = Msg(text, None)
    done = await tp.try_presence(Upd77(m), Ctx(), me_doc(), text or "", {"lat": loc[0], "lon": loc[1]} if loc else None)
    return done, m.replies
async def me_tap(data):
    n = len(TG)
    done = await tp.handle_callback(CbUpd77(data), Ctx(), me_doc(), data)
    return done, TG[n:]
def btns(kb):
    return [b.callback_data for row in (kb.inline_keyboard if kb else []) for b in row]
LOCAL = ZoneInfo("Europe/Rome")
def at_local(day, hh, mm=0):
    return datetime.combine(day, datetime.min.time().replace(hour=hh, minute=mm), tzinfo=LOCAL).astimezone(timezone.utc)

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    smap = cl.get("system_sub_map") or {}
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    for sid, title, addr in (("s_bagno", "Bagno", "Via Roma 5, Torino"), ("s_tetto", "Tetto", "Via Po 1, Torino")):
        db.collection_sub_items.docs.append({"id": sid, "collection_id": cl["id"], "item_id": "c_rossi",
                                             "data": {"titolo": title, "stato": "in corso", smap.get("indirizzo_cantiere", "indirizzo_cantiere"): addr}})
    db.collaborators.docs.append({"id": "k1", "owner_user_id": "u1", "first_name": "Gino", "last_name": "Neri", "company": "Idraulica Neri",
                                  "status": "active", "telegram_chat_id": 900, "commesse": ["s_bagno", "s_tetto"]})
    jl.interpret = said()
    yesterday = (datetime.now(LOCAL) - timedelta(days=1)).date()
    sessions = lambda wid: [x for x in db.work_sessions.docs if x["collaborator_id"] == wid]

    # 1) the owner, from the app: "📍 Sono in cantiere" with the position, "who is on site", "Ho finito"
    r = await server.presence_start_app("s_bagno", server.PresencePayload(lat=45.0705, lon=7.6870), me)
    assert r["open"]["commessa_id"] == "s_bagno" and r["open"]["start_m"] < 50 and not r["open"]["late_asked"]
    assert (await server.my_presence(me))["open"]["commessa_title"] == "Bagno"
    det = await server.get_job_commessa("s_bagno", current=me)
    assert det["on_site"] == [{"name": "Luca Rossi", "is_user": True, "since": r["open"]["start_at"], "start_m": r["open"]["start_m"], "far": False, "role": "", "company": ""}]
    try:
        await server.presence_start_app("s_tetto", server.PresencePayload(), me); assert False
    except HTTPException as ex:
        assert ex.status_code == 409 and "Sei già in cantiere su «Bagno»" in ex.detail
    s0 = sessions("usr_u1")[0]
    s0["start_at"] = (datetime.now(timezone.utc) - timedelta(hours=4, minutes=5)).isoformat()   # four hours ago
    out = await server.presence_stop_app(server.PresencePayload(), me)
    assert out["hours"] == 4.0 and out["commessa_id"] == "s_bagno"
    log = next(x for x in db.job_logs.docs if x["id"] == out["log_id"])
    assert log["user_id"] == "u1" and log["collaborator_id"] is None and log["channel"] == "web" and log["author_name"] == "Luca"
    assert log["hours"] == [{"who": "Luca", "hours": 4.0}] and not [p for p in PUSHED if p[1].startswith("📒")]   # no "a collaborator wrote" to myself
    assert (await server.presence_pause_app(server.PresencePausePayload(log_id=out["log_id"], minutes=30), me))["message"].startswith("⏸️ Pausa di 30 min")
    assert next(x for x in db.job_logs.docs if x["id"] == out["log_id"])["hours"][0]["hours"] == 3.5
    assert (await server.my_presence(me))["open"] is None
    try:
        await server.presence_stop_app(server.PresencePayload(), me); assert False
    except HTTPException as ex:
        assert ex.status_code == 400
    # a closed commessa can't be started on
    db.collection_sub_items.docs.append({"id": "s_old", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Vecchia", "stato": "chiusa"}})
    try:
        await server.presence_start_app("s_old", server.PresencePayload(), me); assert False
    except HTTPException as ex:
        assert ex.status_code == 400

    # 2) the owner on Telegram: two open commesse and no position -> asked which; "ho finito" -> pauses
    done, rep = await me_say("sono arrivato")
    assert done and rep[-1][0] == "⏱️ Su quale commessa inizi?" and btns(rep[-1][1]) == ["upin:s_bagno", "upin:s_tetto"]
    done, sent = await me_tap("upin:s_tetto")
    assert done and "🟢 Inizio alle" in sent[-1][1] and "«Tetto»" in sent[-1][1] and sessions("usr_u1")[-1]["commessa_id"] == "s_tetto"
    done, rep = await me_say("sono arrivato dai Rossi")
    assert "già il tempo aperto su «Tetto»" in rep[-1][0]
    sessions("usr_u1")[-1]["start_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    done, rep = await me_say("ho finito")
    assert "🔴 Fine alle" in rep[0][0] and "2 h nel diario" in rep[0][0] and rep[1][0] == "Hai fatto pause?" and btns(rep[1][1])[-1].endswith(":0")
    done, sent = await me_tap(btns(rep[1][1])[-1])
    assert "Nessuna pausa" in sent[-1][1]
    # the position alone, near the Bagno: started there; a sentence that is a diary entry is not a command
    done, rep = await me_say(loc=(45.0703, 7.6872))
    assert "«Bagno»" in rep[-1][0] and kb_label(rep[-1][1]) == "📍 Ho finito"
    assert (await me_say("ho finito il massetto"))[0] is False
    # not an artigiano: none of this
    assert (await tp.try_presence(Upd77(Msg("sono arrivato")), Ctx(), {**me_doc(), "business_vertical": "fitness"}, "sono arrivato")) is False
    db.work_sessions.docs = [x for x in db.work_sessions.docs if x.get("end_at")]   # (start the evening from scratch)

    # 3) the evening: Gino still "in cantiere" at 19:05 -> asked, the owner told; "No" -> when -> closed there
    await say(loc=loc(0.0004)) if False else None
    await ct.handle_message(Upd(Msg(None, Loc(45.0703, 7.6873))), Ctx(), recs())
    g = sessions("k1")[-1]
    g["start_at"] = at_local(yesterday, 8).isoformat()
    n_tg, n_not = len(TG), len(NOTICES)
    assert await server._presence_late_check(at_local(yesterday, 18, 55)) == 0                  # not yet
    assert await server._presence_late_check(at_local(yesterday, 19, 5)) == 1
    ask = TG[-1]
    assert ask[0] == 900 and "Sei ancora in cantiere su «Bagno»? Risulti lì dalle 08:00" in ask[1] and btns(ask[2]) == [f"pls:y:{g['id']}", f"pls:n:{g['id']}"]
    told = NOTICES[-1]
    assert told[0] == 77 and "risulta ancora in cantiere *Gino Neri* su «Bagno» (dalle 08:00)" in told[1]
    assert await server._presence_late_check(at_local(yesterday, 19, 30)) == 0                  # asked once
    rep = await tap(f"pls:n:{g['id']}")
    assert rep[-1][0].startswith("🚪 A che ora sei andato via?")
    times = btns(rep[-1][1])
    assert times and all(t.startswith(f"ple:{g['id']}:") for t in times) and len(times) <= 6
    rep = await tap(f"ple:{g['id']}:1730")
    assert "🔴 Fine alle 17:30" in rep[0][0] and "9 h 30 min" in rep[0][0] and rep[1][0] == "Hai fatto pause?"
    assert g["end_at"] == at_local(yesterday, 17, 30).isoformat() and g["late_answer"] == "no"
    assert "Gino Neri era andato via da «Bagno» alle 17:30" in NOTICES[-1][1] and NOTICES[-1][0] == 77
    assert (await tap(f"pls:y:{g['id']}"))[-1][0] == "Il tempo in cantiere è già chiuso."

    # 4) "how did it go?": Gino wrote nothing that day -> asked, and his next message goes to the Bagno
    assert await server._presence_day_note(at_local(yesterday, 17, 40)) == 0                    # too soon after the end
    assert await server._presence_day_note(at_local(yesterday, 18, 0)) == 1
    assert NOTICES[-1][0] == 900 and "Com'è andata oggi su «Bagno»?" in NOTICES[-1][1]
    assert next(c for c in db.collaborators.docs if c["id"] == "k1")["tg_state"]["target"] == "s_bagno"
    assert await server._presence_day_note(at_local(yesterday, 18, 30)) == 0                    # once

    # 5) the owner too: still there in the evening (owner = the one on site: no notice to himself), "Sì"
    # in the app -> asked again two hours later; his own hour (18:00) counts
    await server.update_profile(server.ProfilePatch(presence_late_at="18:00"), me)
    r = await server.presence_start_app("s_bagno", server.PresencePayload(), me)
    m = sessions("usr_u1")[-1]
    m["start_at"] = at_local(yesterday, 9).isoformat()
    n_not = len(NOTICES)
    assert await server._presence_late_check(at_local(yesterday, 18, 2)) == 1
    assert TG[-1][0] == 77 and "Sei ancora in cantiere su «Bagno»?" in TG[-1][1] and PUSHED[-1][1] == "🕖 Sei ancora in cantiere?"
    assert len(NOTICES) == n_not and (await server.my_presence(me))["open"]["late_asked"]
    assert (await server.presence_still_app(me))["message"].startswith("👍")
    assert not (await server.my_presence(me))["open"]["late_asked"]
    assert await server._presence_late_check(at_local(yesterday, 19, 0)) == 0
    assert await server._presence_late_check(at_local(yesterday, 20, 10)) == 0                  # (2 h after the real now)
    m["late_next_at"] = at_local(yesterday, 20, 2).isoformat()
    assert await server._presence_late_check(at_local(yesterday, 20, 10)) == 1                  # asked again
    # he left at 19:30, said in the app
    out = await server.presence_stop_app(server.PresencePayload(at="19:30"), me)
    assert m["end_at"] == at_local(yesterday, 19, 30).isoformat() and out["hours"] == 10.5
    try:
        await server.presence_stop_app(server.PresencePayload(at="25:00"), me); assert False
    except HTTPException as ex:
        assert ex.status_code == 400
    # his "how did it go?": on Telegram (the answer goes to the Bagno's diary) and on the phone
    assert await server._presence_day_note(at_local(yesterday, 20, 0)) == 1
    assert TG[-1][0] == 77 and "Com'è andata oggi su «Bagno»?" in TG[-1][1] and PUSHED[-1][1] == "📝 Com'è andata oggi?"
    state = await tg._get_state(db, "u1", 77)
    assert state["pending_presence_note"]["commessa_id"] == "s_bagno"
    n_logs = len(db.job_logs.docs)
    state["pending_presence_note"]["at"] = datetime.now(timezone.utc).isoformat()   # (asked "yesterday" in this test: answered at once)
    assert await tp.try_note(Upd77(Msg("posati i sanitari")), Ctx(), me_doc(), state, "posati i sanitari")
    new = db.job_logs.docs[n_logs:]
    assert new and new[0]["commessa_id"] == "s_bagno" and new[0]["user_id"] == "u1" and "sanitari" in new[0]["text"]
    assert not (await tg._get_state(db, "u1", 77)).get("pending_presence_note")
    # someone who already wrote that day is not asked
    db.work_sessions.docs.append({**m, "id": "ws_x", "note_asked": False, "end_at": at_local(yesterday, 20, 0).isoformat(), "log_id": "x",
                                  "start_at": at_local(yesterday, 9).isoformat()})
    new[0]["date"] = yesterday.isoformat()
    assert await server._presence_day_note(at_local(yesterday, 20, 30)) == 0

    # 6) a start made late is asked two hours after it; one never ended is still closed after 14 h
    await server.presence_start_app("s_tetto", server.PresencePayload(), me)
    late = sessions("usr_u1")[-1]
    late["start_at"] = at_local(yesterday, 18, 30).isoformat()
    assert await server._presence_late_check(at_local(yesterday, 20, 0)) == 0
    assert await server._presence_late_check(at_local(yesterday, 20, 31)) == 1
    print("ALL OK")
asyncio.run(main())
