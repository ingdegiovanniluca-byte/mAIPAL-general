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

import work_reports as wr
async def no_deliver(*a, **k): return None, None, False
server._deliver_work_report = no_deliver
SEEN = []
def interp(fields, job="Bagno"):
    async def f(text, sections, user_name="", user_id=None, channel="web", report_name=""):
        SEEN.append(report_name)
        out = [{"title": s["title"], "fields": {k: fields.get(k, "") for k in s["fields"]}} for s in sections]
        return {"sections": out, "client": {"name": "Mario Rossi", "phone": "", "email": "", "address": ""}, "job_title": job, "summary": "ok"}
    return f

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso", "data_inizio": "2026-09-01"}})
    db.collection_sub_items.docs.append({"id": "s_cucina", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Cucina", "stato": "in corso"}})

    # ===== 1) useful contacts =====
    for bad in (server.JobContactPayload(name=" "), server.JobContactPayload(name="Pino", email="pino@")):
        try:
            await server.create_job_contact("s_bagno", bad, me); assert False
        except server.HTTPException as e:
            assert e.status_code == 400
    p = await server.create_job_contact("s_bagno", server.JobContactPayload(role="Idraulico", name="Pino  Verdi", phone="333 111 2222", email="pino@verdi.it"), me)
    e = await server.create_job_contact("s_bagno", server.JobContactPayload(role="Elettricista", name="Elettro Sud", phone="06 1234", note="chiedere di Marco"), me)
    assert p["name"] == "Pino Verdi" and p["collection_id"] == cl["id"]
    lst = await server.list_job_contacts("s_bagno", me)
    assert [c["role"] for c in lst] == ["Elettricista", "Idraulico"]
    e = await server.update_job_contact(e["id"], server.JobContactPayload(role="Elettricista", name="Elettro Sud srl", phone="06 1234"), me)
    assert e["name"] == "Elettro Sud srl" and e["note"] == ""
    # the directory: what was used elsewhere, once, and the usual roles
    await server.create_job_contact("s_cucina", server.JobContactPayload(role="Idraulico", name="Pino Verdi", phone="333 1112222"), me)
    d = await server.job_contacts_directory(me)
    assert sum(1 for c in d["contacts"] if c["name"] == "Pino Verdi") == 1 and "Idraulico" in d["roles"] and "Direttore lavori" in d["roles"]
    # in the diary and in the commessa's chat
    det = await server.get_job_commessa("s_bagno", current=me)
    assert len(det["contacts"]) == 2
    ANS = []
    async def cap(commessa, logs, reports, question, history, user_id=None, channel="web"):
        ANS.append(commessa); return {"answer": "ok", "is_entry": False}
    jl.answer = cap
    await server.ask_job_commessa("s_bagno", server.CommessaAskPayload(question="numero dell'idraulico?", history=[]), me)
    assert "Idraulico, Pino Verdi, 333 111 2222, pino@verdi.it" in ANS[-1]["contacts_line"]
    await server.delete_job_contact(e["id"], me)
    assert len(await server.list_job_contacts("s_bagno", me)) == 1

    # ===== 2) the reports: five models, the kind told to the model =====
    assert list(wr.BUILTIN_TEMPLATES) == ["sopralluogo", "intervento", "sal", "fine_lavori", "variante"]
    t = await server.list_work_templates(me)
    assert [x["name"] for x in t["builtin"]] == ["Primo sopralluogo", "Rapporto di intervento", "Stato avanzamento lavori",
                                                  "Verbale di fine lavori", "Lavori extra / variante"] and all(x["hint"] for x in t["builtin"])
    # diary of the Bagno: entries, a milestone
    jl.interpret = said(hours=[{"who": "io", "hours": 6}, {"who": "Gino", "hours": 4}], materials=[{"name": "corrugato", "qty": 20, "unit": "m"}],
                        problems=["manca il miscelatore"], date="2026-10-10")
    await server._save_job_log(me, "6 ore io e 4 Gino, 20 m di corrugato, manca il miscelatore", commessa_id="s_bagno")
    await server.create_milestone("s_bagno", server.MilestonePayload(title="Impianto idraulico", who="Pino", due_date="2026-10-30"), me)
    # SAL: the empty fields from the diary, what was dictated wins
    wr.interpret = interp({"Lavori eseguiti": "Impianti completati", "Percentuale di avanzamento": "60%"})
    r = await server._generate_work_report(me, "SAL del Bagno dei Rossi: 60%, impianti completati", "sal")
    assert SEEN[-1] == "Stato avanzamento lavori" and r["commessa_id"] == "s_bagno"
    f = {k: v for sec in r["sections"] for k, v in sec["fields"].items()}
    print({k: f[k] for k in ("Periodo di riferimento", "Ore impiegate", "Materiali impiegati", "Problemi riscontrati", "Milestone")})
    assert f["Percentuale di avanzamento"] == "60%" and f["Lavori eseguiti"] == "Impianti completati"
    assert f["Ore impiegate"] == "10 h" and "20 m corrugato" in f["Materiali impiegati"] and "manca il miscelatore" in f["Problemi riscontrati"]
    assert f["Periodo di riferimento"].startswith("dal 10/10/2026") and "Impianto idraulico: prevista entro il 30/10/2026" in f["Milestone"]
    # a second SAL: only what came after the first
    for x in db.work_reports.docs:
        x["created_at"] = "2026-10-12T10:00:00+00:00"
    jl.interpret = said(hours=[{"who": "io", "hours": 3}], date=jl.today_local().isoformat())
    await server._save_job_log(me, "3 ore io", commessa_id="s_bagno")
    r = await server._generate_work_report(me, "Nuovo SAL del Bagno dei Rossi", "sal")
    f = {k: v for sec in r["sections"] for k, v in sec["fields"].items()}
    assert f["Ore impiegate"] == "3 h" and f["Periodo di riferimento"].startswith("dal 13/10/2026") and not f["Problemi riscontrati"], f
    # end of works: start date of the commessa, today, all the hours
    wr.interpret = interp({"Oggetto dei lavori": "Rifacimento bagno"})
    r = await server._generate_work_report(me, "Fine lavori del Bagno dei Rossi", "fine_lavori")
    f = {k: v for sec in r["sections"] for k, v in sec["fields"].items()}
    assert SEEN[-1] == "Verbale di fine lavori" and f["Data inizio lavori"] == "01/09/2026" and f["Ore complessive"] == "13 h" and f["Data fine lavori"]
    # the other models: nothing from the diary
    wr.interpret = interp({"Attività svolte": "Sostituito il miscelatore"})
    r = await server._generate_work_report(me, "Intervento dal Bagno dei Rossi", "intervento")
    f = {k: v for sec in r["sections"] for k, v in sec["fields"].items()}
    assert SEEN[-1] == "Rapporto di intervento" and f["Attività svolte"] == "Sostituito il miscelatore" and "Ore impiegate" not in f
    r = await server._generate_work_report(me, "Variante del Bagno dei Rossi", "variante")
    assert r["template_name"] == "Lavori extra / variante"

    # ===== 3) deleting the commessa takes its contacts =====
    await server._delete_job_diaries(["s_bagno"])
    assert not [c for c in db.job_contacts.docs if c["commessa_id"] == "s_bagno"]
    print("ALL OK")
asyncio.run(main())
