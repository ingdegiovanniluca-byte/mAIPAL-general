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
    for i, t, st in (("s_bagno", "Bagno", "in corso"), ("s_cucina", "Cucina", "in corso"), ("s_old", "Caldaia", "chiusa")):
        db.collection_sub_items.docs.append({"id": i, "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": t, "stato": st}})

    # 1) the preconfigured action: created once with the vertical, never again after deleting it
    weekly = [a for a in db.scheduled_actions.docs if a.get("kind") == "job_weekly"]
    assert len(weekly) == 1 and weekly[0]["enabled"] and weekly[0]["title"] == "Riepilogo cantieri"
    assert weekly[0]["schedule"]["weekdays"] == [0] and weekly[0]["schedule"]["time"] == "08:00"
    lst = await server.list_scheduled_actions(me)
    assert sum(1 for a in lst if a["kind"] == "job_weekly") == 1
    await server.delete_scheduled_action(weekly[0]["id"], me)
    await server.list_scheduled_actions(me)
    assert not [a for a in db.scheduled_actions.docs if a.get("kind") == "job_weekly"]

    # 2) entries with hours and materials
    jl.interpret = said(hours=[{"who": "io", "hours": 8}, {"who": "Gino", "hours": 6}],
                        materials=[{"name": "corrugato 25", "qty": 20, "unit": "m"}, {"name": "scatola 503", "qty": 2, "unit": "pz"}])
    await server._save_job_log(me, "oggi io 8 ore e Gino 6 ore, 20 metri di corrugato 25 e 2 scatole 503", commessa_id="s_bagno")
    # 3) without rates or prices: nothing guessed, counted apart
    e = await server.get_commessa_economics("s_bagno", me)
    assert e["cost_total"] == 0 and e["unpriced_hours"] == 14 and set(e["unpriced_materials"]) == {"corrugato 25", "scatola 503"} and not e["complete"]
    assert [p["who"] for p in e["people"]][:2] == ["Gino", "Luca"]
    # 4) rates (the default one and Gino's) and a price -> the costs
    await server.patch_job_costs(server.CostsPatch(default_rate=30), "s_bagno", me)
    await server.patch_job_costs(server.CostsPatch(rates={"Gino": 25}), "s_bagno", me)
    e = await server.patch_job_costs(server.CostsPatch(prices=[{"name": "Corrugato 25", "unit": "m", "price": 0.8}]), "s_bagno", me)
    lab = {x["who"]: x for x in e["labor"]}
    assert lab["Luca"]["cost"] == 240 and lab["Gino"]["cost"] == 150 and lab["Gino"]["own_rate"] and not lab["Luca"]["own_rate"]
    assert e["materials_total"] == 16 and e["unpriced_materials"] == ["scatola 503"] and e["cost_total"] == 406
    # the same rates apply to every commessa of the list
    assert next(c for c in db.collections.docs if c["id"] == cl["id"])["costs"]["rates"] == {"Gino": 25}
    # 5) the quote -> margin; 80% -> one note to the owner, not twice
    n0 = len(NOTICES)
    e = await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(budget=500), me)
    assert e["margin"] == 94 and e["used_pct"] == 81.2
    assert len(NOTICES) == n0 + 1 and NOTICES[-1][0] == 77 and "Attenzione al preventivo" in NOTICES[-1][1] and "«Bagno»" in NOTICES[-1][1]
    await server.patch_job_costs(server.CostsPatch(default_rate=30), "s_bagno", me)
    assert len(NOTICES) == n0 + 1
    # an extra cost past 100% -> "superato"; removed and the quote raised -> re-armed
    e = await server.add_commessa_extra("s_bagno", server.ExtraCostPayload(label="Noleggio ponteggio", amount=150), me)
    assert e["cost_total"] == 556 and e["extras_total"] == 150 and "Preventivo superato" in NOTICES[-1][1]
    for bad in (server.ExtraCostPayload(label=" ", amount=10), server.ExtraCostPayload(label="x", amount=-3)):
        try:
            await server.add_commessa_extra("s_bagno", bad, me); assert False
        except server.HTTPException as ex:
            assert ex.status_code == 400
    e = await server.delete_commessa_extra("s_bagno", e["extras"][0]["id"], me)
    e = await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(budget=2000), me)
    assert e["used_pct"] < 80 and next(x for x in db.job_economics.docs if x["commessa_id"] == "s_bagno")["alerts"] == []
    # a new entry pushes it up again (checked after saving)
    await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(budget=500), me)
    n1 = len(NOTICES)
    jl.interpret = said(hours=[{"who": "io", "hours": 4}])
    await server._save_job_log(me, "oggi io 4 ore sul bagno", commessa_id="s_bagno")
    await settle()
    assert len(NOTICES) == n1 + 1 and "superato" in NOTICES[-1][1]
    # 6) the diary's card on top, the owner's chat knows the money, a collaborator's never
    d = await server.get_job_commessa("s_bagno", current=me)
    assert d["economics"]["budget"] == 500 and d["economics"]["cost_total"] == 526
    await server.ask_job_commessa("s_bagno", server.CommessaAskPayload(question="quanto margine ho?", history=[]), me)
    assert "preventivo € 500" in ANSWERS[-1]["economics_line"]
    view = server._commessa_view(next(x for x in db.collection_sub_items.docs if x["id"] == "s_bagno"), None, cl)
    await server._collab_answer({"show_client_contacts": False}, me, view, "quanto costa?", [])
    assert "economics_line" not in ANSWERS[-1]
    # 7) Cerca: the commessa's summary carries costs and margin
    res = await retrieval.retrieve(db, "u1", "quanto ho speso sulla commessa Bagno di Mario Rossi", scope="all", org_id=me.org_id)
    summ = next(c for c in res if c.get("source") == "summary" and "Bagno" in c["display"])
    assert "Economia: costi € 526" in summ["display"] and "margine" in summ["display"], summ["display"]

    # 8) the Monday summary: last week's hours, problems, quote, sites standing still, To Do due
    monday = datetime(2026, 10, 19, 8, 0, tzinfo=ZoneInfo("Europe/Rome"))
    jl.interpret = said(hours=[{"who": "io", "hours": 5}], problems=["manca il miscelatore"], date="2026-10-14")
    await server._save_job_log(me, "io 5 ore, manca il miscelatore", commessa_id="s_bagno")
    for x in db.job_logs.docs:
        if x["commessa_id"] == "s_bagno" and x["date"] != "2026-10-14":
            x["date"] = "2026-10-13"
    await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Montare i sanitari", who="Gino", due_date="2026-10-21"), me)
    text = await server._job_weekly_summary(me, monday)
    print(text)
    assert "la settimana passata (dal 12 ottobre al 18 ottobre)" in text and "*Bagno* — Mario Rossi: 23 h" in text
    assert "⚠️ manca il miscelatore" in text and "di € 500" in text and "🔴" in text
    assert "«Cucina» (mai)" in text and "Caldaia" not in text
    assert "Montare i sanitari — Gino entro" in text
    # run as an action: delivered on Telegram
    a = {"id": "sched_t", "user_id": "u1", "kind": "job_weekly", "title": "Riepilogo cantieri"}
    db.scheduled_actions.docs.append(dict(a, runs=[]))
    run = await server._execute_scheduled_action(a, manual=True)
    assert run["status"] == "ok" and run["delivered"] and NOTICES[-1][0] == 77 and "Cantieri" in NOTICES[-1][1]
    # deleting the commessa drops its economics
    await server._delete_job_diaries(["s_bagno"])
    assert not [x for x in db.job_economics.docs if x["commessa_id"] == "s_bagno"]
    print("ALL OK")
asyncio.run(main())
