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

class FakeMsg:
    def __init__(s): s.replies = []
    async def reply_text(s, text, **kw): s.replies.append(text)
class FakeQuery:
    def __init__(s, data): s.data = data; s.message = FakeMsg(); s.cleared = False
    async def answer(s): pass
    async def edit_message_reply_markup(s, reply_markup=None): s.cleared = True
class FakeUpdate:
    def __init__(s, data): s.message = None; s.callback_query = FakeQuery(data)

async def press(rec_ids, data):
    """the collaborator taps a button under one of their messages"""
    upd = FakeUpdate(data)
    recs = [c for c in db.collaborators.docs if c["id"] in rec_ids]
    await ct.handle_callback(upd, None, recs)
    return upd.callback_query

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    db.collection_sub_items.docs.append({"id": "s_tetto", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Tetto", "stato": "in corso"}})
    db.collaborators.docs += [
        {"id": "k1", "owner_user_id": "u1", "first_name": "Gino", "last_name": "Neri", "company": "Idraulica Neri", "status": "active", "telegram_chat_id": 900, "commesse": ["s_bagno"]},
        {"id": "k2", "owner_user_id": "u1", "first_name": "Pino", "last_name": "Verdi", "status": "invited", "telegram_chat_id": None, "commesse": ["s_bagno"]},
        {"id": "k3", "owner_user_id": "u1", "first_name": "Ugo", "last_name": "Bassi", "status": "active", "telegram_chat_id": 901, "commesse": ["s_tetto"]},
    ]
    today = jl.today_local()
    d = lambda n: (today + timedelta(days=n)).isoformat()

    # 1) who the To Do / milestones can be given to: the collaborators of the commessa
    det = await server.get_job_commessa("s_bagno", current=me)
    assert {c["id"]: c["telegram"] for c in det["collaborators"]} == {"k1": True, "k2": False}

    # 2) a To Do given to Gino: he hears it on Telegram, with the button
    t = await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Montare i sanitari", collaborator_id="k1", due_date=d(1)), me)
    assert t["who"] == "Gino Neri" and t["collaborator_id"] == "k1" and t["notified"]
    cid, text, done = TOLD[-1]
    print(text)
    assert cid == "k1" and "📌 Nuova attività per te: *Montare i sanitari*" in text and "«Bagno» — Mario Rossi" in text and done == f"cldone:t:{t['id']}"
    # not enabled on this commessa: refused; by name: found (Pino, not on Telegram yet: nobody told)
    try:
        await server.create_job_todo("s_bagno", server.JobTodoPayload(text="x", collaborator_id="k3"), me); assert False
    except server.HTTPException as e:
        assert e.status_code == 400
    n = len(TOLD)
    p = await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Tracce bagno", who="Pino"), me)
    assert p["collaborator_id"] == "k2" and p["who"] == "Pino Verdi" and not p["notified"] and len(TOLD) == n
    # a team mate's: nobody told
    mine = await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Ordinare il piatto doccia", who="Luca"), me)
    assert mine["collaborator_id"] is None and len(TOLD) == n

    # 3) its date moves: told; given back to the team: no more his
    t = await server.update_job_todo(t["id"], server.JobTodoPatch(due_date=d(2)), me)
    assert "📅 Nuova scadenza" in TOLD[-1][1] and "era" in TOLD[-1][1]
    n = len(TOLD)
    x = await server.update_job_todo(p["id"], server.JobTodoPatch(who="Luca", collaborator_id=""), me)
    assert x["collaborator_id"] is None and x["who"] == "Luca" and len(TOLD) == n
    x = await server.update_job_todo(mine["id"], server.JobTodoPatch(collaborator_id="k1"), me)
    assert x["who"] == "Gino Neri" and "📌 Nuova attività per te: *Ordinare il piatto doccia*" in TOLD[-1][1]
    await server.update_job_todo(mine["id"], server.JobTodoPatch(text="Ordinare il piatto doccia 80x120"), me)
    assert len(TOLD) == n + 1   # the text alone: not told again

    # 4) reminders: the day before, once; never before 8
    at9 = datetime.now(ZoneInfo("Europe/Rome")).replace(hour=9, minute=0).astimezone(timezone.utc)
    t2 = await server.update_job_todo(t["id"], server.JobTodoPatch(due_date=d(1)), me)
    n = len(TOLD)
    assert await server._todo_reminders(at9.replace(hour=5)) == 0
    assert await server._todo_reminders(at9) == 1 and "⏰ Domani va fatta: *Montare i sanitari*" in TOLD[-1][1] and TOLD[-1][2] == f"cldone:t:{t['id']}"
    assert await server._todo_reminders(at9) == 0

    # 5) a milestone given to him
    m = await server.create_milestone("s_bagno", server.MilestonePayload(title="Impianto idraulico", collaborator_id="k1", due_date=d(5)), me)
    assert m["notified"] and m["who"] == "Gino Neri" and "🚩 Milestone affidata a te: *Impianto idraulico*" in TOLD[-1][1] and TOLD[-1][2] == f"cldone:m:{m['id']}"
    await server.add_milestone_action(m["id"], server.MilestoneActionPayload(text="Manca il materiale", new_due_date=d(7)), me)
    assert "📅 Nuova scadenza per la milestone *Impianto idraulico*" in TOLD[-1][1]

    # 6) he taps ✅ Fatto: done, in the diary with his name, the owner told
    n_owner = len([1 for c_, _ in NOTICES if c_ == 77])
    q = await press(["k1"], f"cldone:t:{t['id']}")
    print(q.message.replies)
    assert q.message.replies[-1].startswith("✅ Fatto!") and q.cleared
    td = next(x for x in db.job_todos.docs if x["id"] == t["id"])
    assert td["done"] and td["done_by"] == "Gino Neri"
    ev = [x for x in db.job_logs.docs if x.get("kind") == "todo"][-1]
    assert ev["author_name"] == "Gino" and "«Montare i sanitari» fatta (segnata da Gino Neri (Idraulica Neri) su Telegram)" in ev["text"] and not ev.get("collaborator_id")
    assert len([1 for c_, _ in NOTICES if c_ == 77]) == n_owner + 1 and "ha segnato come fatta" in NOTICES[-1][1]
    # again: already done; someone else / not enabled: not theirs
    q = await press(["k1"], f"cldone:t:{t['id']}")
    assert "era già segnata come fatta" in q.message.replies[-1]
    q = await press(["k3"], f"cldone:m:{m['id']}")
    assert q.message.replies[-1] == server.COLLAB_NOT_YOURS
    # the milestone: done today, the line in the diary
    q = await press(["k1"], f"cldone:m:{m['id']}")
    ms = next(x for x in db.job_milestones.docs if x["id"] == m["id"])
    assert ms["done"] and ms["done_date"] == today.isoformat()
    assert "Milestone «Impianto idraulico» completata" in [x for x in db.job_logs.docs if x.get("kind") == "milestone"][-1]["text"]
    # done ones are not reminded
    n = len(TOLD)
    await server._milestone_reminders(at9 + timedelta(days=7))
    assert all("Impianto idraulico" not in x[1] for x in TOLD[n:])

    # 7) he can ask what is left to do
    ANS = []
    async def cap(commessa, logs, reports, question, history, user_id=None, channel="web"):
        ANS.append(commessa); return {"answer": "ok", "is_entry": False}
    jl.answer = cap
    rec = next(c for c in db.collaborators.docs if c["id"] == "k1")
    owner, _cl, view = (await server._collab_targets(rec))[0]
    await server._collab_answer(rec, owner, view, "cosa devo ancora fare?", [])
    assert "«Ordinare il piatto doccia 80x120» (Gino Neri)" in ANS[-1]["todos_line"] and "Montare i sanitari" not in ANS[-1]["todos_line"]
    print("ALL OK")
asyncio.run(main())
