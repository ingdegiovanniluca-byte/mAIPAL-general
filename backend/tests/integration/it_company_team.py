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
def recs(chat=900):
    return [c for c in db.collaborators.docs if c.get("telegram_chat_id") == chat]
async def say(text):
    m = Msg(text)
    await ct.handle_message(Upd(m), Ctx(), recs())
    return m.replies
async def tap(data, chat=900):
    u = CbUpd(data)
    await ct.handle_callback(u, None, recs(chat))
    return u.callback_query.message.replies

async def _bot_name(): return "maipal_bot"
tg.bot_username = _bot_name
# the day's pinned message: refreshed in the background - recorded here
PINNED = []
server._day_pin_touch = lambda *ids: PINNED.append({x for x in ids if x})


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    db.collection_sub_items.docs.append({"id": "s_cucina", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Cucina", "stato": "in corso"}})
    today = jl.today_local()
    tomorrow = (today + timedelta(days=1)).isoformat()

    # 1) the hourly cost given with the collaborator: theirs on every commessa, Costi can change it
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Neri", phone="333 1234567", role="Elettricista",
                                                                    company="Elettro Srl", commesse=["s_bagno"], hourly_rate=32.5), me)
    gino = r["collaborator"]
    assert gino["hourly_rate"] == 32.5
    db.job_logs.docs.append({"id": "l1", "user_id": "u1", "commessa_id": "s_bagno", "date": today.isoformat(), "hours": [{"who": "Gino", "hours": 4}]})
    e = await server.get_commessa_economics("s_bagno", current=me)
    assert e["labor"][0] == {"who": "Gino", "hours": 4.0, "rate": 32.5, "own_rate": True, "cost": 130.0}
    assert {"who": "Gino", "rate": 32.5} in e["people"]
    # changed from the diary's Costi: the collaborator's card shows the new one
    await server.patch_job_costs(server.CostsPatch(rates={"Gino": 35}), "s_bagno", current=me)
    assert next(c for c in await server.list_collaborators(me) if c["id"] == gino["id"])["hourly_rate"] == 35
    # changed on the card: Costi follow; cleared: back to the general cost
    await server.patch_job_costs(server.CostsPatch(default_rate=25), current=me)
    out = await server.update_collaborator(gino["id"], server.CollaboratorPatch(hourly_rate=30), me)
    assert out["hourly_rate"] == 30 and (await server.get_commessa_economics("s_bagno", current=me))["labor_total"] == 120
    out = await server.update_collaborator(gino["id"], server.CollaboratorPatch(clear_hourly_rate=True), me)
    e = await server.get_commessa_economics("s_bagno", current=me)
    assert out["hourly_rate"] is None and e["labor"][0]["rate"] == 25 and not e["labor"][0]["own_rate"]
    # a collaborator without one: nothing set
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Pino", last_name="Verdi", phone="347 765 4321", role="idraulico",
                                                                    company="Idro", commesse=["s_bagno"]), me)
    assert r["collaborator"]["hourly_rate"] is None
    pino = r["collaborator"]
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Ugo", last_name="Bassi", phone="347 765 4322", role="elettricista",
                                                                    company="elettro srl ", commesse=["s_bagno"]), me)
    ugo = r["collaborator"]
    # (linked on Telegram)
    for cid, chat in ((gino["id"], 900), (pino["id"], 902), (ugo["id"], 901)):
        d = next(c for c in db.collaborators.docs if c["id"] == cid)
        d.update(status="active", telegram_chat_id=chat)

    # 2) who is on site: everyone, with their role and company (the app groups them)
    now = datetime.now(timezone.utc)
    for i, cid in enumerate((gino["id"], pino["id"], ugo["id"])):
        db.work_sessions.docs.append({"id": f"ws{i}", "collaborator_id": cid, "commessa_id": "s_bagno", "owner_user_id": "u1",
                                      "start_at": (now - timedelta(hours=3 - i)).isoformat(), "end_at": None, "start_m": 40})
    det = await server.get_job_commessa("s_bagno", current=me)
    assert [(p["name"], p["role"], p["company"]) for p in det["on_site"]] == [
        ("Gino Neri", "Elettricista", "Elettro Srl"), ("Pino Verdi", "idraulico", "Idro"), ("Ugo Bassi", "elettricista", "elettro srl")]
    db.work_sessions.docs.clear()

    # 3) a material to take written by Gino: Ugo (same company, same commessa) sees it too, Pino not
    mat_todos = lambda: [x for x in db.job_todos.docs if x.get("kind") == "materiale"]
    model(text="Domani porto 10 scatole 503", materials=[{"name": "scatole 503", "qty": 10, "unit": "pz", "status": "da_prendere", "for_date": tomorrow}])
    TOLD.clear(); PINNED.clear()
    r = await say("domani prendere 10 scatole 503")
    print(r[-1][0])
    t = mat_todos()[-1]
    assert t["collaborator_id"] == gino["id"] and t["shared_with"] == [ugo["id"]]
    assert "Lo vedono anche Ugo" in r[-1][0] and "solo per me" in r[-1][0]
    told = [x for x in TOLD if x[0] == ugo["id"]]
    assert len(told) == 1 and "📌 Gino ha segnato da prendere domani per «Bagno»" in told[0][1] and "10 pz scatole 503" in told[0][1] \
        and told[0][2] == f"cldone:t:{t['id']}"
    assert not [x for x in TOLD if x[0] == pino["id"]]
    assert any(ugo["id"] in p for p in PINNED)
    # their day: the pinned message of tomorrow has it for both
    ugo_doc = next(c for c in db.collaborators.docs if c["id"] == ugo["id"])
    items = await server._collab_day_items(ugo_doc, tomorrow)
    assert any(row[1] == t["id"] for _v, rows in items for row in rows)
    pino_doc = next(c for c in db.collaborators.docs if c["id"] == pino["id"])
    assert not await server._collab_day_items(pino_doc, tomorrow)
    # the reminders go to both (to Ugo saying who wrote it)
    eve = datetime.combine(today, datetime.strptime("19:31", "%H:%M").time(), tzinfo=server.LOCAL_TZ).astimezone(timezone.utc)
    t_doc = next(x for x in db.job_todos.docs if x["id"] == t["id"])
    t_doc["reminded"] = {}
    TOLD.clear()
    assert await server._material_reminders(eve) == 2
    assert {x[0] for x in TOLD} == {gino["id"], ugo["id"]}
    assert "(segnato da Gino)" in next(x[1] for x in TOLD if x[0] == ugo["id"]) and "segnato da" not in next(x[1] for x in TOLD if x[0] == gino["id"])
    # Ugo took it: done for everyone, both pinned messages follow; Pino can't
    out = await tap(f"cldone:t:{t['id']}", chat=902)
    assert out[-1][0] == server.COLLAB_NOT_YOURS
    PINNED.clear()
    out = await tap(f"cldone:t:{t['id']}", chat=901)
    assert out[-1][0].startswith("✅ Fatto!") and next(x for x in db.job_todos.docs if x["id"] == t["id"])["done"]
    assert any({gino["id"], ugo["id"]} <= p for p in PINNED)

    # 4) "solo per me": only Gino's
    model(text="Domani porto il flessibile", materials=[{"name": "flessibile", "qty": None, "unit": "", "status": "da_prendere", "for_date": tomorrow}])
    TOLD.clear()
    r = await say("domani prendere il flessibile, solo per me")
    t = mat_todos()[-1]
    assert not t.get("shared_with") and "lo vedono anche" not in r[-1][0] and not [x for x in TOLD if x[0] == ugo["id"]]
    # undone: (nothing shared)
    # 5) given by Gino to Pino by name: Pino's only, no sharing with Gino's company
    model(text="Pino porta il silicone", materials=[{"name": "silicone", "qty": None, "unit": "", "status": "da_prendere", "for_date": tomorrow, "who": "Pino"}])
    TOLD.clear()
    r = await say("ricorda a Pino di portare il silicone domani")
    t = mat_todos()[-1]
    assert t["collaborator_id"] == pino["id"] and not t.get("shared_with") and {x[0] for x in TOLD} == {pino["id"]}
    # 6) a shared one undone by Gino: Ugo's pinned message follows
    model(text="Domani porto la colla", materials=[{"name": "colla", "qty": None, "unit": "", "status": "da_prendere", "for_date": tomorrow}])
    r = await say("domani prendere la colla")
    t = mat_todos()[-1]
    assert t["shared_with"] == [ugo["id"]]
    PINNED.clear()
    out = await tap(f"clt:{t['id']}")
    assert "Promemoria annullato" in out[-1][0] and t["id"] not in {x["id"] for x in db.job_todos.docs} and any(ugo["id"] in p for p in PINNED)
    # 7) no company: nobody else
    d = next(c for c in db.collaborators.docs if c["id"] == gino["id"])
    d["company"] = ""
    model(text="Domani porto i tasselli", materials=[{"name": "tasselli", "qty": None, "unit": "", "status": "da_prendere", "for_date": tomorrow}])
    await say("domani prendere i tasselli")
    assert not mat_todos()[-1].get("shared_with")
    print("ALL OK")

asyncio.run(main())
