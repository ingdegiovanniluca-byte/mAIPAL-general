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

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    db.collaborators.docs.append({"id": "k1", "first_name": "Gino", "last_name": "Neri", "status": "active", "telegram_chat_id": 900, "commesse": ["s_bagno"]})
    today = jl.today_local()
    d = lambda n: (today + timedelta(days=n)).isoformat()

    # 1) created: who, deadline; the first date kept
    for bad in (server.MilestonePayload(title=" ", due_date=d(3)), server.MilestonePayload(title="x", due_date="domani")):
        try:
            await server.create_milestone("s_bagno", bad, me); assert False
        except server.HTTPException as e:
            assert e.status_code == 400
    a = await server.create_milestone("s_bagno", server.MilestonePayload(title="Impianto elettrico", who="Gino", due_date=d(1)), me)
    b = await server.create_milestone("s_bagno", server.MilestonePayload(title="Massetto", due_date=d(10)), me)
    c = await server.create_milestone("s_bagno", server.MilestonePayload(title="Demolizioni", who="Gino", due_date=d(-3)), me)
    assert a["original_due_date"] == d(1) and a["status"] == "soon" and b["who"] == "Luca" and b["status"] == "planned"
    assert c["status"] == "late" and c["late_days"] == 3
    # moved before anything slipped: a new plan, not a delay
    b = await server.update_milestone(b["id"], server.MilestonePatch(due_date=d(12)), me)
    assert b["original_due_date"] == d(12) and b["slip_days"] == 0

    # 2) reminders on Telegram: to whoever made it and to Gino (collaborator); once
    import zoneinfo
    at9 = datetime.now(ZoneInfo("Europe/Rome")).replace(hour=9, minute=0).astimezone(timezone.utc)
    n = len(NOTICES)
    sent = await server._milestone_reminders(at9)
    got = NOTICES[n:]
    print("\n---\n".join(f"{c_}: {t}" for c_, t in got))
    assert sent == 4 and {c_ for c_, _ in got} == {77, 900}
    assert any("Domani scade la milestone *Impianto elettrico*" in t for _, t in got)
    assert any("ritardo di 3 giorni: *Demolizioni*" in t and "azione correttiva" in t for _, t in got)
    assert await server._milestone_reminders(at9) == 0                          # not twice
    assert await server._milestone_reminders(at9.replace(hour=4)) == 0          # never before 8

    # 3) a corrective action with a new date: the delay stays measured against the first date
    c = await server.add_milestone_action(c["id"], server.MilestoneActionPayload(text="Squadra in più da lunedì", new_due_date=d(2)), me)
    assert c["due_date"] == d(2) and c["original_due_date"] == d(-3) and c["slip_days"] == 5 and c["status"] == "soon"
    assert c["corrective_actions"][0]["old_due_date"] == d(-3) and c["delay_days"] == 5
    ev = [x for x in db.job_logs.docs if x.get("kind") == "milestone"]
    assert "azione correttiva — Squadra in più da lunedì" in ev[-1]["text"] and "Nuova scadenza" in ev[-1]["text"]
    # a later move is a slip too (after an action)
    c = await server.update_milestone(c["id"], server.MilestonePatch(due_date=d(4)), me)
    assert c["original_due_date"] == d(-3) and c["slip_days"] == 7

    # 4) done: the execution date, the delay against the first plan, a line in the diary
    a = await server.update_milestone(a["id"], server.MilestonePatch(done=True, done_date=d(3)), me)
    assert a["status"] == "done" and a["done_date"] == d(3) and a["delay_days"] == 2
    assert "completata" in [x for x in db.job_logs.docs if x.get("kind") == "milestone"][-1]["text"] and "2 giorni di ritardo" in db.job_logs.docs[-1]["text"]
    try:
        await server.update_job_log(db.job_logs.docs[-1]["id"], server.JobLogPatch(text="x"), me); assert False
    except server.HTTPException as e:
        assert "non si modifica" in e.detail
    b2 = await server.update_milestone(b["id"], server.MilestonePatch(done=True), me)
    assert b2["delay_days"] == 0 and b2["done_date"] == today.isoformat()
    b2 = await server.update_milestone(b["id"], server.MilestonePatch(done=False), me)
    assert b2["status"] == "planned" and b2["done_date"] is None

    # 5) the diary: list and summary; events are not entries
    det = await server.get_job_commessa("s_bagno", current=me)
    ms, sm = det["milestones"], det["milestones_summary"]
    assert [m["title"] for m in ms] == ["Impianto elettrico", "Demolizioni", "Massetto"]
    assert sm["total"] == 3 and sm["done"] == 1 and sm["late"] == 0 and sm["avg_delay"] == 2 and sm["next"]["title"] == "Demolizioni"
    assert det["totals"]["entries"] == 0
    # the commessa's chat knows them
    ANS = []
    async def cap(commessa, logs, reports, question, history, user_id=None, channel="web"):
        ANS.append(commessa); return {"answer": "ok", "is_entry": False}
    jl.answer = cap
    await server.ask_job_commessa("s_bagno", server.CommessaAskPayload(question="a che punto siamo con le milestone?", history=[]), me)
    assert "«Impianto elettrico» (Gino)" in ANS[-1]["milestones_line"] and "2 giorni di ritardo" in ANS[-1]["milestones_line"]
    assert "azioni correttive: Squadra in più da lunedì" in ANS[-1]["milestones_line"]

    # 6) the Monday summary: late ones and this week's
    late = await server.create_milestone("s_bagno", server.MilestonePayload(title="Collaudo", who="Luca", due_date=d(-1)), me)
    text = await server._job_weekly_summary(me, datetime.now(ZoneInfo("Europe/Rome")))
    assert "🔴 Milestone in ritardo:" in text and "Collaudo" in text and "🚩 Milestone di questa settimana:" in text and "Demolizioni" in text, text

    # 7) deleted with the commessa
    await server.delete_milestone(late["id"], me)
    assert not any(x["id"] == late["id"] for x in db.job_milestones.docs)
    await server._delete_job_diaries(["s_bagno"])
    assert not db.job_milestones.docs
    print("ALL OK")
asyncio.run(main())
