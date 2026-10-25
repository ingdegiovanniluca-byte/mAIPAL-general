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
from datetime import date

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi",
                                         "data": {"titolo": "Bagno", "stato": "in corso", "data_inizio": "2026-10-01"}})
    db.collection_sub_items.docs.append({"id": "s_box", "collection_id": cl["id"], "item_id": "c_rossi",
                                         "data": {"titolo": "Box", "stato": "in corso", "data_inizio": "2026-10-01"}})
    T = date(2026, 10, 22)
    jl.today_local = lambda: T
    # milestones planned 5 + 5 + 10 + 5 working days; the first two took 15 instead of 10
    for i, (t, orig, done) in enumerate([("Demolizioni", "2026-10-08", "2026-10-12"), ("Tracce", "2026-10-15", "2026-10-22"),
                                         ("Impianti", "2026-10-29", None), ("Finiture", "2026-11-05", None)]):
        db.job_milestones.docs.append({"id": f"m{i}", "commessa_id": "s_bagno", "collection_id": cl["id"], "title": t, "who": "Luca",
                                       "due_date": orig, "original_due_date": orig, "done": bool(done), "done_date": done,
                                       "created_at": "2026-10-01T08:00:00+00:00"})
    for d in ("2026-10-02", "2026-10-06", "2026-10-09", "2026-10-13", "2026-10-15", "2026-10-19", "2026-10-20", "2026-10-21",
              "2026-10-22", "2026-10-07"):
        db.job_logs.docs.append({"id": f"l{d}", "commessa_id": "s_bagno", "date": d, "kind": None, "hours": [{"who": "Luca", "hours": 8}],
                                 "materials": [], "problems": [], "text": "lavori", "author_name": "Luca", "created_at": d + "T10:00:00+00:00"})
    await server.patch_job_costs(server.CostsPatch(default_rate=30), "s_bagno", me)          # 80 h x 30 = 2.400
    await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(budget=5000), me)

    # 1) the diary: progress 40%, real end, final cost
    d = await server.get_job_commessa("s_bagno", current=me)
    f = d["forecast"]
    assert f["progress"]["value"] == 0.4 and f["progress"]["source"] == "milestone"
    assert f["end"]["date"] == "2026-11-23" and f["end"]["delay_days"] == 12 and f["end"]["confidence"] == "media"
    assert f["cost"]["final"] == 6000 and f["cost"]["pct"] == 120 and f["cost"]["confidence"] == "media"
    assert "fine prevista 23/11/2026" in f["line"] and "costo finale previsto € 6.000 su € 5.000" in f["line"]
    # no milestones, no SAL: said, not guessed
    db.job_logs.docs.append({"id": "lbox", "commessa_id": "s_box", "date": "2026-10-21", "kind": None, "hours": [{"who": "Luca", "hours": 4}],
                             "materials": [], "problems": [], "text": "x", "created_at": "2026-10-21T10:00:00+00:00"})
    g = (await server.get_job_commessa("s_box", current=me))["forecast"]
    assert g["progress"] is None and g["end"] is None and g["line"].startswith("Per le previsioni servono le milestone")
    # a SAL with its percentage gives the progress
    db.work_reports.docs.append({"id": "r1", "commessa_id": "s_box", "report_type": "sal", "created_at": "2026-10-20T10:00:00+00:00",
                                 "sections": [{"title": "Avanzamento", "fields": {"Percentuale di avanzamento": "50%"}}]})
    g = (await server.get_job_commessa("s_box", current=me))["forecast"]
    assert g["progress"] == {"value": 0.5, "source": "sal", "date": "2026-10-20"} and "dall'ultimo SAL" in g["line"]

    # 2) the commessa's chat knows it
    await server.ask_job_commessa("s_bagno", server.CommessaAskPayload(question="quando finiamo?", history=[]), me)
    assert "fine prevista 23/11/2026" in ANSWERS[-1]["forecast_line"]

    # 3) told once on Telegram, from 8:15, both problems in one message
    from datetime import datetime, timezone
    early = datetime(2026, 10, 22, 6, 0, tzinfo=timezone.utc)      # 8:00 in Rome
    assert await server._forecast_alerts(early) == 0
    at = datetime(2026, 10, 22, 6, 30, tzinfo=timezone.utc)
    n0 = len(NOTICES)
    assert await server._forecast_alerts(at) == 1
    msg = NOTICES[-1][1]
    print(msg)
    assert NOTICES[-1][0] == 77 and "Previsione" in msg and "«Bagno»" in msg
    assert "finisce il *23/11/2026*, 12 giorni lavorativi dopo il previsto (05/11/2026)" in msg and "costa circa *€ 6.000* su € 5.000" in msg
    assert await server._forecast_alerts(at) == 0                                       # once a day
    assert await server._forecast_alerts(datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)) == 0   # and once per problem
    # solved (quote raised) and back again: told again
    await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(budget=7000), me)
    await server._forecast_alerts(datetime(2026, 10, 26, 8, 0, tzinfo=timezone.utc))
    await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(budget=5000), me)
    n1 = len(NOTICES)
    assert await server._forecast_alerts(datetime(2026, 10, 27, 8, 0, tzinfo=timezone.utc)) == 1
    assert "costa circa" in NOTICES[-1][1] and "finisce il" not in NOTICES[-1][1]          # the late end was never solved
    # a closed / suspended commessa is not watched
    db.collection_sub_items.docs[0]["data"]["stato"] = "sospesa"
    db.job_forecasts.docs.clear()
    assert await server._forecast_alerts(datetime(2026, 10, 28, 8, 0, tzinfo=timezone.utc)) == 0
    db.collection_sub_items.docs[0]["data"]["stato"] = "in corso"

    # 4) the Monday summary lists where the sites are heading
    text = await server._job_weekly_summary(me, datetime(2026, 10, 26, 8, 0, tzinfo=ZoneInfo("Europe/Rome")))
    print(text)
    assert "🔮 Previsioni:" in text and "«Bagno»: fine prevista" in text and "% del preventivo" in text
    # deleting the commessa drops its forecast state
    await server._delete_job_diaries(["s_bagno"])
    assert not [x for x in db.job_forecasts.docs if x["commessa_id"] == "s_bagno"]
    print("ALL OK")
asyncio.run(main())
