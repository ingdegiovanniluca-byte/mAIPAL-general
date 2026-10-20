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
def recs():
    return [c for c in db.collaborators.docs if c.get("telegram_chat_id") == 900]
async def say(text):
    m = Msg(text)
    await ct.handle_message(Upd(m), Ctx(), recs())
    return m.replies
async def tap(data):
    u = CbUpd(data)
    await ct.handle_callback(u, None, recs())
    return u.callback_query.message.replies

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    db.collaborators.docs.append({"id": "k1", "owner_user_id": "u1", "first_name": "Gino", "last_name": "Neri", "company": "",
                                  "status": "active", "telegram_chat_id": 900, "commesse": ["s_bagno"]})
    today = jl.today_local()
    tomorrow = (today + timedelta(days=1)).isoformat()
    entries = lambda: [x for x in db.job_logs.docs if not x.get("kind")]
    mat_todos = lambda: [x for x in db.job_todos.docs if x.get("kind") == "materiale"]

    # 1) only things to take (the model even calls them used): a reminder, nothing in the diary
    model(text="Domani porto 10 scatole 503 e il flessibile",
          materials=[{"name": "scatole 503", "qty": 10, "unit": "pz", "status": "usato"}, {"name": "flessibile", "qty": None, "unit": ""}])
    r = await say("domani porto 10 scatole 503 e il flessibile")
    print(r[-1][0])
    assert "📌 Promemoria per «Bagno» — Mario Rossi" in r[-1][0] and "10 pz scatole 503, flessibile" in r[-1][0] and "Non l'ho messo tra i materiali usati" in r[-1][0]
    assert not entries() and len(mat_todos()) == 1
    t = mat_todos()[0]
    assert t["due_date"] == tomorrow and t["collaborator_id"] == "k1" and t["who"] == "Gino Neri" and t["text"] == "Da prendere: 10 pz scatole 503, flessibile"
    assert r[-1][1].inline_keyboard[0][0].callback_data == f"clt:{t['id']}"
    # undone at once
    out = await tap(f"clt:{t['id']}")
    assert "Promemoria annullato" in out[-1][0] and not mat_todos()

    # 2) mixed: the entry with what was used, the reminder with what to take
    model(text="Posato il corrugato, 4 ore.", hours=[{"who": "Gino", "hours": 4}],
          materials=[{"name": "corrugato", "qty": 20, "unit": "m", "status": "usato"}, {"name": "scatole 503", "qty": 10, "unit": "pz", "status": "da_prendere", "for_date": tomorrow}])
    r = await say("oggi 4 ore, posato 20 metri di corrugato; domani porto 10 scatole 503")
    print(r[-1][0])
    e = entries()[-1]
    assert [m["name"] for m in e["materials"]] == ["corrugato"] and "status" not in e["materials"][0]
    assert "🧰 Materiali: 20 m corrugato" in r[-1][0] and "📌 Da prendere domani: 10 pz scatole 503" in r[-1][0]
    t = mat_todos()[-1]
    assert t["from_log_id"] == e["id"]
    # the totals count only what was used
    det = await server.get_job_commessa("s_bagno", current=me)
    assert [m["name"] for m in det["totals"]["materials"]] == ["corrugato"]
    # undoing the entry takes its reminder away too
    out = await tap(r[-1][1].inline_keyboard[0][0].callback_data)
    assert "Voce annullata" in out[-1][0] and not mat_todos() and not entries()

    # 3) not clear ("10 scatole 503"): asked; the answer decides
    model(text="10 scatole 503", materials=[{"name": "scatole 503", "qty": 10, "unit": "pz", "status": "dubbio"}])
    r = await say("10 scatole 503")
    assert "li avete usati oggi o sono da prendere?" in r[-1][0] and not entries() and not mat_todos()
    assert [b.callback_data for b in r[-1][1].inline_keyboard[0]] == ["cmat:usato", "cmat:da_prendere"]
    out = await tap("cmat:da_prendere")
    assert "📌 Promemoria" in out[-1][0] and not entries() and len(mat_todos()) == 1
    r = await say("10 scatole 503")
    out = await tap("cmat:usato")
    assert entries() and entries()[-1]["materials"][0]["name"] == "scatole 503" and len(mat_todos()) == 1

    # 4) reminders: the evening before at 19:30 and that morning at 7, once each
    t = mat_todos()[0]
    eve = datetime.combine(today, datetime.strptime("19:31", "%H:%M").time(), tzinfo=server.LOCAL_TZ).astimezone(timezone.utc)
    t["reminded"] = {}
    n = len(TOLD)
    assert await server._material_reminders(eve - timedelta(minutes=10)) == 0           # 19:21: not yet
    assert await server._material_reminders(eve) == 1 and "🧰 Domani da prendere per «Bagno»" in TOLD[-1][1] and TOLD[-1][2] == f"cldone:t:{t['id']}"
    assert await server._material_reminders(eve + timedelta(minutes=5)) == 0             # not twice
    morning = datetime.combine(today + timedelta(days=1), datetime.strptime("07:01", "%H:%M").time(), tzinfo=server.LOCAL_TZ).astimezone(timezone.utc)
    assert await server._material_reminders(morning) == 1 and "🧰 Oggi da prendere" in TOLD[-1][1]
    assert await server._material_reminders(morning) == 0 and len(TOLD) == n + 2
    # the generic To Do reminders leave them alone
    at9 = morning + timedelta(hours=2)
    k = len(TOLD)
    await server._todo_reminders(at9)
    assert all("Da prendere" not in x[1] for x in TOLD[k:])
    # taken: ✅ Fatto
    out = await tap(f"cldone:t:{t['id']}")
    assert out[-1][0].startswith("✅ Fatto!") and next(x for x in db.job_todos.docs if x["id"] == t["id"])["done"]

    # 5) the user's own (app chat): reminded on the phone (app notification) and Telegram
    model(text="", materials=[{"name": "sacchi di cemento", "qty": 3, "unit": "", "status": "da_prendere", "for_date": tomorrow}])
    r = await server._save_job_log(me, "domani prendo 3 sacchi di cemento", commessa_id="s_bagno")
    assert r["status"] == "planned" and r["todos"][0]["assignee_user_id"] == "u1" and r["todos"][0]["who"] == "Luca"
    db.job_todos.docs[-1]["reminded"] = {}
    p = len(PUSHED)
    assert await server._material_reminders(eve) == 1 and PUSHED[p][0] == "u1" and "Domani da prendere" in PUSHED[p][1]
    assert any("3 sacchi di cemento" in t_ for c_, t_ in NOTICES if c_ == 77)

    # 5b) "ricorda a Mario di prendere…" written in the app: the reminder is Mario's (a collaborator),
    # told at once on Telegram, reminded to him; one not on Telegram: the writer is reminded
    db.collaborators.docs.append({"id": "k2", "owner_user_id": "u1", "first_name": "Mario", "last_name": "Bianchi", "company": "",
                                  "status": "active", "telegram_chat_id": 901, "commesse": ["s_bagno"]})
    model(text="", materials=[{"name": "scatole 503", "qty": 10, "unit": "pz", "status": "da_prendere", "for_date": tomorrow, "who": "Mario"}])
    n = len(TOLD)
    r = await server.create_job_log(server.JobLogPayload(text="ricorda a Mario di prendere domani 10 scatole 503", commessa_id="s_bagno"), me)
    t = r["todos"][0]
    print(r["message"])
    assert r["status"] == "planned" and t["collaborator_id"] == "k2" and t["who"] == "Mario Bianchi" and t["assignee_user_id"] is None and t["notified"]
    assert TOLD[n][0] == "k2" and "📌 Nuova attività per te: *Da prendere: 10 pz scatole 503*" in TOLD[n][1] and TOLD[n][2] == f"cldone:t:{t['id']}"
    assert "(Mario Bianchi)" in r["message"] and "Mandato su Telegram a Mario Bianchi" in r["message"]
    db.job_todos.docs[-1]["reminded"] = {}
    n, p = len(TOLD), len(PUSHED)
    assert await server._material_reminders(eve) == 1 and TOLD[n][0] == "k2" and len(PUSHED) == p
    # the model missing the name: found in the words ("Mario deve prendere"); not on Telegram -> the writer
    next(c for c in db.collaborators.docs if c["id"] == "k2")["telegram_chat_id"] = None
    model(text="", materials=[{"name": "flessibile", "qty": None, "unit": "", "status": "da_prendere", "for_date": tomorrow}])
    r = await server.create_job_log(server.JobLogPayload(text="domani Mario deve prendere il flessibile", commessa_id="s_bagno"), me)
    t = r["todos"][0]
    assert t["collaborator_id"] == "k2" and t["assignee_user_id"] == "u1" and not t["notified"]

    # 6) an entry already saved with a material to take: moved out, into a reminder
    model(text="Montato il lavabo, serve il sifone", materials=[{"name": "lavabo", "qty": 1, "unit": "pz", "status": "usato"},
                                                                {"name": "sifone", "qty": 1, "unit": "pz", "status": "usato"}])
    r = await server._save_job_log(me, "montato il lavabo, il sifone", commessa_id="s_bagno")   # (both seen as used)
    lg = r["log"]
    assert [m["name"] for m in lg["materials"]] == ["lavabo", "sifone"]
    moved = await server.plan_material_from_log(lg["id"], server.PlanMaterialPayload(index=1), me)
    assert [m["name"] for m in moved["log"]["materials"]] == ["lavabo"] and moved["todo"]["text"] == "Da prendere: 1 pz sifone"
    assert moved["todo"]["due_date"] == tomorrow
    print("ALL OK")
asyncio.run(main())
