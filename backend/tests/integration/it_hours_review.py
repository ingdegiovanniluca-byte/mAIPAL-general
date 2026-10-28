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
REAL_ANSWER = jl.answer
jl.answer = fake_answer

async def settle():
    for _ in range(5):
        await asyncio.sleep(0)

import json as _json
import collab_telegram as ct

# the model's answer is faked; interpret's own checks (materials used / to take) run for real
MODEL_SAYS = {}
class _Resp:
    def __init__(s, content): s.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]; s.usage = None
class _Completions:
    async def create(s, **kw): return _Resp(_json.dumps(MODEL_SAYS))
class _Client:
    def __init__(s, **kw): s.chat = type("Ch", (), {"completions": _Completions()})()
jl.openai.AsyncOpenAI = _Client
jl._track = lambda *a, **k: None
def model(text="", hours=None, materials=None, problems=None):
    MODEL_SAYS.clear(); MODEL_SAYS.update({"kind": "nota", "doubt": "", "date": "", "text": text, "hours": hours or [],
                                           "materials": materials or [], "problems": problems or [], "client": "", "commessa": ""})
PUSHED = []
server.push.fire_and_forget = lambda db_, uid, title, body, url="/", tag=None: PUSHED.append((uid, title, body))

class Msg:
    def __init__(s, text): s.text = text; s.location = None; s.voice = None; s.photo = None; s.caption = None; s.contact = None; s.replies = []
    async def reply_text(s, text, **kw): s.replies.append((text, kw.get("reply_markup")))
class Chat:
    id = 900
class Bot:
    async def send_chat_action(s, **kw): pass
class Ctx:
    bot = Bot()
class Upd:
    def __init__(s, msg): s.message = msg; s.callback_query = None; s.effective_chat = Chat()
class Q:
    def __init__(s, data): s.data = data; s.message = Msg(""); s.cleared = False
    async def answer(s): pass
    async def edit_message_reply_markup(s, reply_markup=None): s.cleared = True
class CbUpd:
    def __init__(s, data): s.message = None; s.callback_query = Q(data); s.effective_chat = Chat()
def recs():
    return [c for c in db.collaborators.docs if c.get("telegram_chat_id") == 900]
async def say(text):
    m = Msg(text)
    await ct.handle_message(Upd(m), Ctx(), recs())
    return m.replies

SEEN = []   # what the model was given
class _Completions2:
    async def create(s, **kw):
        SEEN.append(kw["messages"]); return _Resp(_json.dumps(MODEL_SAYS))
class _Client2:
    def __init__(s, **kw): s.chat = type("Ch", (), {"completions": _Completions2()})()
jl.openai.AsyncOpenAI = _Client2
server._day_pin_touch = lambda *ids: None
LOC = server.LOCAL_TZ
def at(day, hm):
    return datetime.combine(day, datetime.strptime(hm, "%H:%M").time(), tzinfo=LOC).astimezone(timezone.utc).isoformat()
def model_says(kind="nota", text="", hours=None, date="", times=None):
    MODEL_SAYS.clear(); MODEL_SAYS.update({"kind": kind, "doubt": "Quale giorno?" if kind == "non_chiara" else "", "date": date, "text": text,
                                           "hours": hours or [], "materials": [], "problems": [], "times": times or {"start": None, "end": None},
                                           "client": "", "commessa": "", "answer": "ok", "is_entry": False})
def get(lid):
    return next(x for x in db.job_logs.docs if x["id"] == lid)
def presence_log(lid, who_id, day, start, end, hours, user=False):
    doc = {"id": lid, "user_id": "u1", "commessa_id": "s_bagno", "commessa_title": "Bagno", "client_name": "Mario Rossi", "date": day.isoformat(),
           "author_name": "Luca" if user else "Gino", "collaborator_id": None if user else who_id, "text": f"In cantiere dalle {start} alle {end}",
           "hours": [{"who": "Luca" if user else "Gino", "hours": hours}], "materials": [], "problems": [], "photos": [],
           "presence": {"session_id": "ws_" + lid, "start_at": at(day, start), "end_at": at(day, end), "minutes": 0, "pause_min": 0},
           "created_at": at(day, end)}
    db.job_logs.docs.append(doc)
    return doc


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    db.collaborators.docs.append({"id": "k1", "owner_user_id": "u1", "first_name": "Gino", "last_name": "Neri", "company": "Idraulica Neri",
                                  "status": "active", "telegram_chat_id": 900, "commesse": ["s_bagno"]})
    today = jl.today_local()
    yesterday = today - timedelta(days=1)

    # the clock reader (the note's own words; "ho finito il massetto alle 12" is not the day's end)
    assert jl.clock_times(None, "Annota che ho sbagliato a segnare l orario di fine..ho finito alle 17.10") == {"start": None, "end": "17:10"}
    assert jl.clock_times(None, "ieri dalle 8 alle 17") == {"start": "08:00", "end": "17:00"}
    assert jl.clock_times(None, "ho finito il massetto alle 12") == {"start": None, "end": None}
    assert jl.clock_times({"end": "18:00"}, "ho finito alle 17.10")["end"] == "17:10"   # the model's number not in the message

    # 1) the screenshot: the end marked with 📍 at 18:10, the note says 17:10 - the model even finds it unclear
    pres = presence_log("jp1", "k1", today, "07:58", "18:10", 10)
    model_says(kind="non_chiara")
    NOTICES.clear()
    r = await say("Annota che ho sbagliato a segnare l orario di fine..ho finito alle 17.10")
    print(r[-1][0])
    lg = [x for x in db.job_logs.docs if x.get("hours_review")][-1]
    assert lg["hours"] == [] and lg["hours_pending"] == [{"who": "Gino", "hours": 9.0}] and lg["date"] == today.isoformat()
    rv = lg["hours_review"]
    assert rv["status"] == "pending" and rv["kind"] == "correzione" and rv["replaces_log_id"] == "jp1" and (rv["start"], rv["end"]) == ("07:58", "17:10")
    assert "⏳ Ore da approvare: Gino 9 h (dalle 07:58 alle 17:10, al posto delle 10 h segnate con 📍)" in r[-1][0]
    assert any("🕒 Ore da approvare: Gino Neri (Idraulica Neri) su «Bagno»" in t for _c, t in NOTICES)
    assert get("jp1")["hours"] == [{"who": "Gino", "hours": 10}]          # still the 📍 ones until approved
    # in the app, the chat's answers and the reports: apart, not counted
    det = await server.get_job_commessa("s_bagno", current=me)
    t = det["totals"]
    assert t["hours_total"] == 10 and t["hours_pending_total"] == 9 and t["pending"][0]["log_id"] == lg["id"]
    assert (await server.get_commessa_economics("s_bagno", current=me))["labor"][0]["hours"] == 10
    assert "Ore da approvare (scritte nella nota, non ancora conteggiate): Gino 9 h" in jl.search_text(lg)
    SEEN.clear()
    await REAL_ANSWER({"title": "Bagno", "client_name": "Mario Rossi"}, det["logs"], [], "quante ore ha fatto Gino?", [])
    system = SEEN[-1][0]["content"]
    assert "Ore da approvare, NON comprese nel totale: 9 h (Gino 9 h)" in system and "non ancora conteggiate" in system
    # approved: they count, in the place of the 📍 hours; Gino told
    TOLD.clear()
    out = await server.review_job_log_hours(lg["id"], server.HoursReviewPayload(approve=True), me)
    assert out["log"]["hours"] == [{"who": "Gino", "hours": 9.0}] and out["log"]["hours_review"]["status"] == "approved"
    assert get("jp1")["hours"] == [] and get("jp1")["hours_replaced_by"] == lg["id"] and get("jp1")["hours_replaced"] == [{"who": "Gino", "hours": 10}]
    t = (await server.get_job_commessa("s_bagno", current=me))["totals"]
    assert t["hours_total"] == 9 and t["hours_pending_total"] == 0
    assert TOLD and TOLD[-1][0] == "k1" and "✅ Approvate le ore" in TOLD[-1][1]
    try:
        await server.review_job_log_hours(lg["id"], server.HoursReviewPayload(approve=True), me); assert False
    except HTTPException as e:
        assert e.status_code == 400

    # 2) hours written for yesterday (no 📍 that day): to approve; not approved -> nothing counted
    model_says(text="Ieri montati i sanitari, 8 ore.", hours=[{"who": "io", "hours": 8}], date=yesterday.isoformat())
    r = await say("ieri montati i sanitari, 8 ore")
    lg2 = [x for x in db.job_logs.docs if x.get("hours_review")][-1]
    assert lg2["hours_pending"] == [{"who": "Gino", "hours": 8.0}] and lg2["hours_review"]["kind"] == "dichiarate" and lg2["date"] == yesterday.isoformat()
    assert "⏳ Ore da approvare: Gino 8 h. Contano" in r[-1][0]
    TOLD.clear()
    out = await server.review_job_log_hours(lg2["id"], server.HoursReviewPayload(approve=False), me)
    assert out["log"]["hours"] == [] and out["log"]["hours_pending"] == [] and out["log"]["hours_review"]["rejected_hours"] == [{"who": "Gino", "hours": 8.0}]
    assert "non sono state approvate" in TOLD[-1][1]
    assert (await server.get_job_commessa("s_bagno", current=me))["totals"]["hours_total"] == 9

    # 3) a start never ended (closed as forgotten): "ho finito alle 17:30", short, with nothing open,
    # goes to the diary - from its start, to approve; the start is closed with it
    db.work_sessions.docs.append({"id": "ws_f", "collaborator_id": "k1", "commessa_id": "s_bagno", "commessa_title": "Bagno", "owner_user_id": "u1",
                                  "start_at": at(yesterday, "08:00"), "end_at": at(yesterday, "08:00"), "forgotten": True})
    model_says(text="Ho finito alle 17:30.", date=yesterday.isoformat(), times={"start": None, "end": "17:30"})
    r = await say("ho finito alle 17:30")
    lg3 = [x for x in db.job_logs.docs if x.get("hours_review")][-1]
    assert lg3["hours_pending"] == [{"who": "Gino", "hours": 9.5}] and lg3["hours_review"]["start"] == "08:00" and lg3["date"] == yesterday.isoformat()
    ws = next(x for x in db.work_sessions.docs if x["id"] == "ws_f")
    assert ws["log_id"] == lg3["id"] and ws["declared"] and ws["end_at"] == at(yesterday, "17:30")

    # 4) only the end, nothing to start from: the note is kept, the start asked
    db.job_logs.docs[:] = [x for x in db.job_logs.docs if not x.get("presence")]
    day3 = today - timedelta(days=5)
    model_says(text="Finito alle 16.", date=day3.isoformat(), times={"start": None, "end": "16:00"})
    r = await say("il " + str(day3.day) + " ho finito alle 16")
    assert "Non so a che ora sei arrivato" in r[-1][0] and not [x for x in db.job_logs.docs if x.get("date") == day3.isoformat() and x.get("hours_pending")]
    # end before start: nothing saved
    model_says(text="", date=yesterday.isoformat(), times={"start": "17:00", "end": "08:00"})
    n = len(db.job_logs.docs)
    r = await say("ieri arrivato alle 17 e andato via alle 8")
    assert "è prima dell'inizio" in r[-1][0] and len(db.job_logs.docs) == n

    # 5) not clear, then completed by the answer ("giorno di ieri")
    model_says(kind="non_chiara")
    r = await say("ho sbagliato l'orario")
    assert "non è chiara" in r[-1][0]
    model_says(text="Ieri ho finito alle 17.10.", date=yesterday.isoformat(), times={"start": None, "end": "17:10"})
    SEEN.clear()
    r = await say("giorno di ieri")
    assert SEEN[0][-1]["content"] == "ho sbagliato l'orario\ngiorno di ieri"
    assert not next(c for c in db.collaborators.docs if c["id"] == "k1").get("unclear")

    # 6) the owner's own correction (app / main bot): counted at once, in the place of their 📍
    presence_log("jp9", None, today, "07:00", "19:00", 12, user=True)
    model_says(text="Ho finito alle 16.", times={"start": None, "end": "16:00"})
    r = await server._save_job_log(me, "ho finito alle 16", commessa_id="s_bagno")
    assert r["status"] == "ok" and r["log"]["hours"] == [{"who": "Luca", "hours": 9.0}] and not r["log"].get("hours_pending")
    assert get("jp9")["hours"] == [] and get("jp9")["hours_replaced_by"] == r["log"]["id"]
    assert "⏱ Ore: Luca 9 h (dalle 07:00 alle 16:00, al posto delle 12 h segnate con 📍)" in r["message"]
    # the owner's plain hours: as before
    model_says(text="Oggi 3 ore di sopralluogo.", hours=[{"who": "io", "hours": 3}])
    r = await server._save_job_log(me, "oggi 3 ore di sopralluogo", commessa_id="s_bagno")
    assert r["log"]["hours"] == [{"who": "Luca", "hours": 3.0}] and not r["log"].get("hours_review")
    # 7) which commessa, with two: the one named; then the next messages, a few minutes apart, the
    # same; after longer, the site they are on now (time open); with neither, asked
    db.collection_sub_items.docs.append({"id": "s_cucina", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Cucina", "stato": "in corso"}})
    k1 = next(c for c in db.collaborators.docs if c["id"] == "k1")
    k1["commesse"] = ["s_bagno", "s_cucina"]
    k1["tg_state"] = None; k1["unclear"] = None
    last = lambda: [x for x in db.job_logs.docs if not x.get("kind")][-1]
    model_says(text="Fatte 10 ore in cucina.", hours=[{"who": "io", "hours": 10}])
    r = await say("ho fatto 10 h nella commessa cucina")
    assert last()["commessa_id"] == "s_cucina" and last()["hours_pending"] == [{"who": "Gino", "hours": 10.0}]
    model_says(text="Montati i pensili e posato il top.")
    r = await say("montati i pensili e posato il top")
    assert last()["commessa_id"] == "s_cucina" and last()["text"] == "Montati i pensili e posato il top."
    k1["tg_state"]["at"] = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()   # half an hour later…
    db.work_sessions.docs.append({"id": "ws_open", "collaborator_id": "k1", "commessa_id": "s_bagno", "commessa_title": "Bagno", "owner_user_id": "u1",
                                  "start_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(), "end_at": None})
    model_says(text="Posato il piatto doccia.")
    r = await say("posato il piatto doccia")                     # … on site at the Bagno
    assert last()["commessa_id"] == "s_bagno" and last()["text"] == "Posato il piatto doccia."
    db.work_sessions.docs[:] = [x for x in db.work_sessions.docs if x["id"] != "ws_open"]
    k1["tg_state"]["at"] = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    n = len(db.job_logs.docs)
    r = await say("stuccate le fughe")
    assert "Di quale commessa si tratta?" in r[-1][0] and len(db.job_logs.docs) == n
    print("ALL OK")

from fastapi import HTTPException
asyncio.run(main())
