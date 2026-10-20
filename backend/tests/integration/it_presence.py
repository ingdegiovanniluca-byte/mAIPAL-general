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

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    smap = cl.get("system_sub_map") or {}
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi",
                                         "data": {"titolo": "Bagno", "stato": "in corso", smap.get("indirizzo_cantiere", "indirizzo_cantiere"): "Via Roma 5, Torino"}})
    db.collection_sub_items.docs.append({"id": "s_tetto", "collection_id": cl["id"], "item_id": "c_rossi",
                                         "data": {"titolo": "Tetto", "stato": "in corso", smap.get("indirizzo_cantiere", "indirizzo_cantiere"): "Via Po 1, Torino"}})
    db.collaborators.docs.append({"id": "k1", "owner_user_id": "u1", "first_name": "Gino", "last_name": "Neri", "company": "Idraulica Neri",
                                  "status": "active", "telegram_chat_id": 900, "commesse": ["s_bagno", "s_tetto"]})
    loc = lambda d_lon=0.0: (45.0703, 7.6869 + d_lon)

    # 1) the commands are recognized; a diary entry is not
    assert sp.parse_command("sono arrivato")["action"] == "start" and sp.parse_command("ho finito il massetto") is None

    # 2) the 📍 button: the position picks the nearest commessa; the start is told, with the distance
    r = await say(loc=loc(0.0004))
    print(r[-1][0])
    assert "🟢 Inizio alle" in r[-1][0] and "«Bagno» — Mario Rossi" in r[-1][0] and "(in cantiere)" in r[-1][0]
    assert kb_label(r[-1][1]) == "📍 Ho finito"
    ws = [x for x in db.work_sessions.docs if x["collaborator_id"] == "k1"]
    assert len(ws) == 1 and ws[0]["commessa_id"] == "s_bagno" and ws[0]["start_m"] < 50 and ws[0]["site_known"]
    det = await server.get_job_commessa("s_bagno", current=me)
    assert det["on_site"][0]["name"] == "Gino Neri" and det["geo"]["lat"] == 45.0703
    # again: already open
    r = await say("sono arrivato")
    assert "Hai già il tempo aperto su «Bagno»" in r[-1][0] and len(ws) == 1

    # a diary message while working: saved with its Annulla, then the 📍 Ho finito button again
    jl.interpret = said(hours=[], materials=[{"name": "corrugato", "qty": 20, "unit": "m"}])
    next(c for c in db.collaborators.docs if c["id"] == "k1")["tg_state"] = None   # hours later: only the open time tells
    r = await say("posato 20 metri di corrugato")
    assert next(x for x in db.job_logs.docs if x.get("materials"))["commessa_id"] == "s_bagno"
    assert "📒 Diario" in r[-2][0] and r[-2][1].inline_keyboard[0][0].callback_data.startswith("clu:")
    assert r[-1][0].startswith("⏱️ Tempo in cantiere aperto dalle") and "«Bagno»" in r[-1][0] and kb_label(r[-1][1]) == "📍 Ho finito"
    assert len([x for x in db.work_sessions.docs if x["end_at"] is None]) == 1

    # 3) the end (2 h 37 min ago started): the hours in the diary, quarter-rounded; the owner hears it
    ws[0]["start_at"] = (datetime.now(timezone.utc) - timedelta(minutes=157)).isoformat()
    n_push = len(PUSHED)
    r = await say(loc=loc(0.0003))
    print(r[-2][0])
    assert "🔴 Fine alle" in r[-2][0] and "2 h 37 min su «Bagno»" in r[-2][0] and "2,5 h nel diario" in r[-2][0]
    assert kb_label(r[-2][1]) == "📍 Sono arrivato in cantiere" and r[-1][0] == "Hai fatto pause?"
    log = next(x for x in db.job_logs.docs if x.get("presence"))
    assert log["hours"] == [{"who": "Gino", "hours": 2.5}] and log["collaborator_id"] == "k1" and log["commessa_id"] == "s_bagno"
    assert log["text"].startswith("In cantiere dalle ") and "(2 h 37 min)" in log["text"] and "⚠️" not in log["text"]
    assert len(PUSHED) == n_push + 1 and PUSHED[-1][1] == "📒 Gino Neri · Bagno" and "In cantiere dalle" in PUSHED[-1][2]
    assert det_totals_ok(await server.get_job_commessa("s_bagno", current=me))
    # a pause of 30 min: 2 h 07 -> 2 h; again with none: back to 2,5
    pz = r[-1][1].inline_keyboard[0][0].callback_data
    assert pz == f"cpz:{log['id']}:30"
    out = await tap(pz)
    log = next(x for x in db.job_logs.docs if x["id"] == log["id"])
    assert "Pausa di 30 min tolta: 2 h" in out[-1][0] and log["hours"][0]["hours"] == 2.0 and "pausa 30 min esclusa" in log["text"]
    out = await tap(f"cpz:{log['id']}:0")
    assert next(x for x in db.job_logs.docs if x["id"] == log["id"])["hours"][0]["hours"] == 2.5
    # nothing open: said
    r = await say("ho finito")
    assert "Non hai un inizio aperto" in r[-1][0]

    # 4) said with a time and the commessa's name, no position; far away start told to the owner
    r = await say("sono arrivato dal Tetto alle 7:00")
    ws2 = [x for x in db.work_sessions.docs if x["end_at"] is None][0]
    assert ws2["commessa_id"] == "s_tetto" and ws2["start_loc"] is None and "(senza posizione)" in r[-1][0]
    r = await say("ho finito alle 6:30")
    assert "prima dell'inizio" in r[-1][0]
    if datetime.now(server.LOCAL_TZ).strftime("%H:%M") > "07:30":
        r = await say("ho finito alle 7:30")
        assert "30 min su «Tetto»" in r[-2][0] and "0,5 h nel diario" in r[-2][0]
    else:
        await say("ho finito")
    # far from both sites: asked which commessa; the start is told as far, the owner's phone hears it
    n_push = len(PUSHED)
    r = await say(loc=loc(0.0300))
    assert "Su quale commessa inizi?" in r[-1][0]
    out = await tap("cin:s_bagno")
    assert "⚠️ Risulti a 2,4 km dal cantiere" in out[-1][0], out[-1][0]
    assert any(t.startswith("⚠️ Gino Neri · Bagno") and "2,4 km" in b for _, t, b in PUSHED[n_push:])

    # 5) forgotten: closed without hours after 14 h, both told
    open_ = [x for x in db.work_sessions.docs if x["end_at"] is None][0]
    open_["start_at"] = (datetime.now(timezone.utc) - timedelta(hours=15)).isoformat()
    r = await say("ho finito")
    assert "più di 14 ore" in r[-1][0]
    n_logs = len(db.job_logs.docs)
    assert await server._presence_forgotten() == 1
    assert open_.get("forgotten") and len(db.job_logs.docs) == n_logs
    assert any("non ho contato le ore" in t for _, t, _d in TOLD) and any("non ha segnato la fine" in t for c_, t in NOTICES if c_ == 77)

    # 6) the owner sets the site's position (e.g. from the phone, on site); back from the address
    g = await server.set_commessa_geo("s_bagno", server.CommessaGeoPayload(lat=45.1, lon=7.7), me)
    assert g["source"] == "manual" and (await server._commessa_geo("s_bagno", {"address": "Via Roma 5, Torino"}))["lat"] == 45.1
    g = await server.set_commessa_geo("s_bagno", server.CommessaGeoPayload(), me)
    assert g["source"] == "address" and g["lat"] == 45.0703
    print("ALL OK")


def det_totals_ok(det):
    return det["totals"]["hours_total"] == 2.5 and det["on_site"] == []

asyncio.run(main())
