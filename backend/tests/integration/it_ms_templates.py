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

import milestone_templates as mtpl
from datetime import date

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    smap = cl.get("system_sub_map") or {}
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_items.docs.append({"id": "c_bianchi", "collection_id": cl["id"], "data": {"nome": "Anna Bianchi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    db.collection_sub_items.docs.append({"id": "s_bagno2", "collection_id": cl["id"], "item_id": "c_bianchi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    monday = jl.today_local() + timedelta(days=(7 - jl.today_local().weekday()))   # next Monday

    # 1) the ready-made ones
    lst = await server.list_milestone_templates(me)
    names = [t["name"] for t in lst["builtin"]]
    assert "Impianto elettrico domestico" in names and "Rifacimento bagno" in names and len(names) >= 8 and lst["custom"] == []

    # 2) applied to a commessa from a Monday: dates in working days
    r = await server.apply_milestone_template("s_bagno", server.ApplyMilestoneTemplatePayload(template_id="builtin:bagno", start_date=monday.isoformat()), me)
    assert r["created"] == 8 and r["skipped"] == [] and r["template"] == "Rifacimento bagno"
    by = {m["title"]: m["due_date"] for m in r["milestones"]}
    assert by["Smontaggio sanitari e demolizioni"] == (monday + timedelta(days=2)).isoformat()      # Wednesday
    assert by["Pulizia finale e consegna"] == (monday + timedelta(days=21)).isoformat()             # 15 working days = 3 weeks
    assert all(date.fromisoformat(d).weekday() < 5 for d in by.values())
    # again: nothing doubled
    r = await server.apply_milestone_template("s_bagno", server.ApplyMilestoneTemplatePayload(template_id="builtin:bagno", start_date=monday.isoformat()), me)
    assert r["created"] == 0 and len(r["skipped"]) == 8

    # 3) changed on this job, then saved as their own template (from the commessa's start date)
    ms = [m for m in db.job_milestones.docs if m["commessa_id"] == "s_bagno"]
    tiles = next(m for m in ms if m["title"] == "Posa pavimento e rivestimento")
    await server.delete_milestone(next(m for m in ms if m["title"] == "Box doccia e mobile bagno")["id"], me)
    await server.create_milestone("s_bagno", server.MilestonePayload(title="Controsoffitto", due_date=(monday + timedelta(days=9)).isoformat()), me)
    next(x for x in db.collection_sub_items.docs if x["id"] == "s_bagno")["data"][smap.get("data_inizio", "data_inizio")] = monday.isoformat()
    t = await server.save_milestone_template("s_bagno", server.SaveMilestoneTemplatePayload(name="Bagno chiavi in mano"), me)
    steps = {s["title"]: s["day"] for s in t["steps"]}
    assert len(t["steps"]) == 8 and "Box doccia e mobile bagno" not in steps and steps["Controsoffitto"] == 7 and steps["Posa pavimento e rivestimento"] == 11
    assert steps["Smontaggio sanitari e demolizioni"] == 2 and [s["day"] for s in t["steps"]] == sorted(s["day"] for s in t["steps"])
    for bad in ("", "  "):
        try:
            await server.save_milestone_template("s_bagno", server.SaveMilestoneTemplatePayload(name=bad), me); assert False
        except server.HTTPException as e:
            assert e.status_code == 400
    lst = await server.list_milestone_templates(me)
    assert [c["name"] for c in lst["custom"]] == ["Bagno chiavi in mano"]

    # 4) applied to another job, started on a Saturday (counts from Monday)
    saturday = monday - timedelta(days=2)
    r = await server.apply_milestone_template("s_bagno2", server.ApplyMilestoneTemplatePayload(template_id=t["id"], start_date=saturday.isoformat()), me)
    assert r["created"] == 8 and {m["title"]: m["due_date"] for m in r["milestones"]}["Controsoffitto"] == mtpl.add_workdays(monday, 7).isoformat()

    # 5) their own: edited, a ready-made one copied, deleted; others' / unknown: not found
    t2 = await server.update_milestone_template(t["id"], server.MilestoneTemplatePayload(name="Bagno completo", steps=[{"title": "Rilievo", "day": 0}, {"title": " ", "day": 3}]), me)
    assert t2["name"] == "Bagno completo" and t2["steps"] == [{"title": "Rilievo", "day": 0}]
    copy = await server.create_milestone_template(server.MilestoneTemplatePayload(name="Elettrico (mio)", steps=mtpl.builtin("builtin:elettrico_casa")["steps"]), me)
    assert len(copy["steps"]) == 8
    await server.delete_milestone_template(t["id"], me)
    assert [c["name"] for c in (await server.list_milestone_templates(me))["custom"]] == ["Elettrico (mio)"]
    for tid in ("mtpl_nope", "builtin:nope"):
        try:
            await server.apply_milestone_template("s_bagno2", server.ApplyMilestoneTemplatePayload(template_id=tid), me); assert False
        except server.HTTPException as e:
            assert e.status_code == 404
    print("ALL OK")
asyncio.run(main())
