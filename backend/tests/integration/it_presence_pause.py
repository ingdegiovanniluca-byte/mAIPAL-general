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

def kb_all(markup):
    return [b.text for row in (markup.keyboard if markup is not None and hasattr(markup, "keyboard") else []) for b in row]


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    smap = cl.get("system_sub_map") or {}
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi",
                                         "data": {"titolo": "Bagno", "stato": "in corso", smap.get("indirizzo_cantiere", "indirizzo_cantiere"): "Via Roma 5, Torino"}})
    db.collaborators.docs.append({"id": "k1", "owner_user_id": "u1", "first_name": "Gino", "last_name": "Neri", "company": "Idraulica Neri",
                                  "status": "active", "telegram_chat_id": 900, "commesse": ["s_bagno"]})
    jl.interpret = said()

    # 1) the words of a pause (and the buttons' text), not diary entries
    P = sp.parse_command
    for t in ["⏸️ Pausa", "sono in pausa", "vado in pausa pranzo", "pausa pranzo", "faccio una pausa", "vado a pranzo", "stacco per pranzo", "in pausa dalle 12:30"]:
        assert P(t)["action"] == "pause_start", t
    for t in ["▶️ Riprendo", "riprendo", "ho ripreso alle 13:15", "fine pausa", "sono tornato", "torno al lavoro", "ho finito la pausa"]:
        assert P(t)["action"] == "pause_end", t
    for t, m in [("ho fatto mezz'ora di pausa", 30), ("pausa di 30 minuti", 30), ("pausa pranzo di un'ora", 60), ("ho fatto 45 minuti di pausa", 45),
                 ("abbiamo fatto una pausa di 1 ora e mezza", 90), ("pausa di 1,5 ore", 90), ("pausa dalle 12 alle 13", 60), ("pausa pranzo dalle 12.30 alle 13.15", 45)]:
        assert P(t) == {**P(t), "action": "pause_add", "minutes": m}, (t, P(t))
    assert P("la pausa è stata lunga perché pioveva") is None and P("ho finito il massetto") is None and P("stacco")["action"] == "stop"

    # 2) on Telegram: 📍 arrived -> the keyboard has ⏸️ Pausa next to 📍 Ho finito
    r = await say("sono arrivato")
    assert "🟢 Inizio alle" in r[-1][0] and kb_all(r[-1][1]) == ["📍 Ho finito", "⏸️ Pausa"], kb_all(r[-1][1])
    ws = next(x for x in db.work_sessions.docs if x["collaborator_id"] == "k1")
    ws["start_at"] = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()      # arrived 5 hours ago
    # the button ⏸️ Pausa (its text): in pause now; ▶️ Riprendo in its place; not a diary note
    n_logs = len(db.job_logs.docs)
    r = await say("⏸️ Pausa")
    assert r[-1][0].startswith("⏸️ In pausa dalle") and "«Bagno»" in r[-1][0] and kb_all(r[-1][1]) == ["📍 Ho finito", "▶️ Riprendo"], r
    assert len(db.job_logs.docs) == n_logs and ws["paused_at"]
    r = await say("sono in pausa")
    assert r[-1][0].startswith("Sei già in pausa dalle")
    # who is on site sees it (the owner's page, Cerca)
    det = await server.get_job_commessa("s_bagno", current=me)
    assert det["on_site"][0]["paused_since"] == ws["paused_at"]
    assert "IN PAUSA dalle" in (await server._presence_context("u1"))[0]["display"]
    # 45 minutes later: ▶️ Riprendo
    ws["paused_at"] = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    r = await say("▶️ Riprendo")
    assert r[-1][0].startswith("▶️ Ripreso alle") and "pausa di 45 min" in r[-1][0] and kb_all(r[-1][1]) == ["📍 Ho finito", "⏸️ Pausa"], r[-1][0]
    r = await say("riprendo")
    assert r[-1][0].startswith("Non risulti in pausa")
    # written, not with the button: "ho fatto mezz'ora di pausa" adds up
    r = await say("ho fatto mezz'ora di pausa")
    assert "Pausa di 30 min segnata" in r[-1][0] and "oggi in tutto 1 h 15 min" in r[-1][0], r[-1][0]
    # 3) the end: 5 h less 1 h 15 of pauses = 3 h 45 -> 3,5 h (to the half hour); no "Hai fatto pause?"
    r = await say("ho finito")
    end = [t for t, _kb in r if t.startswith("🔴 Fine")][-1]
    assert "⏸️ Pause segnate: 1 h 15 min, escluse dalle ore." in end, end
    assert not any(t == "Hai fatto pause?" for t, _kb in r)
    log = next(x for x in db.job_logs.docs if x.get("presence"))
    assert log["hours"][0]["hours"] == 3.5 and log["presence"]["pause_min"] == 75 and log["presence"]["pause_registered"]
    assert "pausa 1 h 15 min esclusa" in log["text"], log["text"]
    ws = next(x for x in db.work_sessions.docs if x["collaborator_id"] == "k1")
    assert len(ws["pauses"]) == 2 and not ws["paused_at"]
    # said after the end: added to today's time
    r = await say("pausa di 15 minuti")
    log = next(x for x in db.job_logs.docs if x["id"] == log["id"])
    assert "Pausa di 1 h 30 min tolta" in r[-1][0] and log["presence"]["pause_min"] == 90 and log["hours"][0]["hours"] == 3.5, r[-1][0]

    # 4) a pause left open at the end: closed there; no pause registered -> asked as before
    r = await say("sono arrivato")
    ws2 = next(x for x in db.work_sessions.docs if x["collaborator_id"] == "k1" and x["end_at"] is None)
    ws2["start_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    ws2["paused_at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    r = await say("ho finito")
    log2 = next(x for x in db.job_logs.docs if (x.get("presence") or {}).get("session_id") == ws2["id"])
    assert log2["presence"]["pause_min"] == 20 and log2["hours"][0]["hours"] == 1.5
    r = await say("sono arrivato")
    ws3 = next(x for x in db.work_sessions.docs if x["collaborator_id"] == "k1" and x["end_at"] is None)
    ws3["start_at"] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    r = await say("ho finito")
    assert r[-1][0] == "Hai fatto pause?"                                                    # none registered: asked
    # not on site: a pause is not a diary note, and says what to do
    r = await say("sono in pausa")
    assert r[-1][0].startswith("Non risulti in cantiere")

    # 5) the app's users: in the app (⏸️ / ▶️) and on Telegram the same
    s0 = await server.presence_start_app("s_bagno", server.PresencePayload(), me)
    try:
        await server.presence_break_app(server.PresenceBreakPayload(action="end"), me)
        raise AssertionError("not refused")
    except server.HTTPException as e:
        assert e.status_code == 400
    out = await server.presence_break_app(server.PresenceBreakPayload(action="start"), me)
    assert out["open"]["paused_at"] and out["message"].startswith("⏸️ In pausa dalle")
    mine = next(x for x in db.work_sessions.docs if x["collaborator_id"] == "usr_u1" and x["end_at"] is None)
    mine["start_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    mine["paused_at"] = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    out = await server.presence_break_app(server.PresenceBreakPayload(action="end"), me)
    assert "pausa di 30 min" in out["message"] and not out["open"]["paused_at"] and out["open"]["pause_min"] == 30
    end = await server.presence_stop_app(server.PresencePayload(), me)
    assert end["pause_registered"] and end["pause_min"] == 30 and end["hours"] == 2.5
    import team_presence_tg as tp
    class TUpd:
        def __init__(s, text): s.message = Msg(text); s.effective_chat = type("C", (), {"id": 77})(); s.callback_query = None
    udoc = next(u for u in db.users.docs if u["user_id"] == "u1")
    await server.presence_start_app("s_bagno", server.PresencePayload(), me)
    u = TUpd("vado in pausa pranzo")
    assert await tp.try_presence(u, None, udoc, "vado in pausa pranzo")
    assert u.message.replies[-1][0].startswith("⏸️ In pausa dalle") and kb_all(u.message.replies[-1][1]) == ["📍 Ho finito", "▶️ Riprendo"]
    print("ALL OK")

asyncio.run(main())
