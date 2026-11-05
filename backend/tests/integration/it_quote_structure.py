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
    def __init__(s, n): s.modified_count = n; s.deleted_count = n; s.matched_count = n

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
import job_logs as jl, collab_telegram as ct, telegram_bot as tg
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from telegram.ext import ApplicationHandlerStop
import telegram

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77, "tenant_id": "ten_1"}
db.users.docs.append(dict(U))
db.users.docs.append({"user_id": "u2", "email": "x@b.it", "name": "Marco Bianchi", "role": "user", "tenant_id": "ten_1", "org_id": None,
                      "telegram_chat_id": 78})
async def uname(): return "maipal_bot"
tg.bot_username = uname
tg.bot_token = lambda: "123:abc"
NOTICES = []
async def fake_send(chat_id, text):
    NOTICES.append((chat_id, text)); return True
server._send_telegram_text = fake_send
BOT_SENT = []
class FakeBot:
    def __init__(self, token=None): pass
    async def send_message(self, chat_id=None, text=None, reply_markup=None, **k): BOT_SENT.append((chat_id, text, reply_markup))
telegram.Bot = FakeBot

def said(kind="nota", text=None, hours=None, problems=None, materials=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web", photos=0):
        f.last = {"speaker": speaker, "team": team, "known": known}
        return {"kind": kind, "doubt": "", "date": jl.today_local().isoformat(), "text": text or t,
                "hours": jl.clean_hours(hours or [], speaker), "materials": jl.clean_materials(materials or []), "problems": problems or [], "client": "", "commessa": ""}
    return f
ANSWERS = []
async def fake_answer(commessa, logs, reports, question, history, user_id=None, channel="web"):
    ANSWERS.append({"view": commessa, "question": question, "history": history})
    return {"answer": "Mancano i sanitari.", "is_entry": False}
jl.answer = fake_answer

# ---- fake Telegram objects ----
REPLIES = []
class Chat:
    def __init__(s, i): s.id = i
class Msg:
    def __init__(s, chat, text=None, contact=None):
        s.chat = Chat(chat); s.text = text; s.contact = contact; s.voice = None; s.photo = None; s.caption = None
    async def reply_text(s, text, reply_markup=None, **k): REPLIES.append((text, reply_markup))
class Upd:
    def __init__(s, chat, text=None, contact=None, uid=500, data=None):
        s.effective_chat = Chat(chat); s.effective_user = type("U", (), {"id": uid})()
        if data:
            s.message = None
            q = type("Q", (), {})(); q.data = data; q.message = Msg(chat)
            async def ans(*a, **k): pass
            async def edit(*a, **k): pass
            q.answer = ans; q.edit_message_reply_markup = edit
            s.callback_query = q
        else:
            s.message = Msg(chat, text, contact); s.callback_query = None
class Bot:
    async def send_chat_action(s, **k): pass
    async def send_message(s, chat_id=None, text=None, reply_markup=None, **k): BOT_SENT.append((chat_id, text, reply_markup))
class Ctx: bot = Bot()

async def send(chat, text=None, contact=None, uid=500):
    """-> True when the collaborator gate took the message (the update stopped there)."""
    try:
        await ct.gate(Upd(chat, text, contact, uid), Ctx())
    except ApplicationHandlerStop:
        return True
    return False

async def tap(chat, data):
    try:
        await ct.gate_callback(Upd(chat, data=data), Ctx())
    except ApplicationHandlerStop:
        return True
    return False

def buttons(markup):
    return [b.callback_data for row in (markup.inline_keyboard if markup else []) for b in row]

db.tenants.docs.append({"id": "ten_1", "name": "Impresa Rossi", "owner_user_id": "u1", "owner_email": "a@b.it",
                       "plan": {"max_users": 5, "max_collaborators": 5, "max_admins": 1}, "sharing": {"users_share": True, "collab_contacts": False}})
import verticals as vx, org_settings as osettings


import io, base64
from datetime import date as _date
from PIL import Image
import archive_names as an


async def deny(coro, code=403):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code in (code if isinstance(code, tuple) else (code,)), (e.status_code, e.detail)
        return e.detail
    raise AssertionError("not denied")


def jpeg_uri():
    buf = io.BytesIO(); Image.new("RGB", (40, 30), (200, 80, 80)).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# the archive: one Drive, made of folders and files kept here
FOLDERS, SAVED = [], []
DRIVE = {"up": True}
async def fake_targets(uid): return ["google"] if DRIVE["up"] else []
async def fake_path(current, folder, subs):
    FOLDERS.append(" / ".join([folder] + list(subs)))
    return {"name": " / ".join([folder] + list(subs)), "ids": {"google": "f1"}, "links": {"google": "https://drive/f/" + str(len(FOLDERS))}}
async def fake_save(user_id, folder, tmp_path, filename, ctype, only=None, subfolders=None):
    if DRIVE.get("fail"):
        raise HTTPException(status_code=500, detail="Drive non risponde")
    SAVED.append((" / ".join([folder] + list(subfolders or [])), filename))
    return {"saved": ["google"], "links": {"google": f"https://drive/{filename}"}, "web_view_link": f"https://drive/{filename}", "errors": {}}
server._storage_targets = fake_targets
server._ensure_storage_path = fake_path
server._storage_save = fake_save
async def new_job(text, user_id=None, channel="web"):
    return dict(NEXT_JOB)
jl.read_new_commessa = new_job
NEXT_JOB = {}


from starlette.datastructures import UploadFile

READ_DOC = {}
async def fake_read_doc(text, commessa, user_id=None, channel="web"):
    return dict(READ_DOC)
jl.read_document = fake_read_doc
QUOTE = {}
async def fake_read_quote(text, commessa, user_id=None, channel="web"):
    return dict(QUOTE)
jl.read_quote = fake_read_quote
SUMMARIES = []
async def fake_summary(entries, commessa, user_id=None, channel="web"):
    SUMMARIES.append(entries)
    return {"date_participants": "28/10, Luca", "state": "bagno 3x2 m", "requests": "doccia al posto della vasca", "issues": "", "materials": ""}
jl.survey_summary = fake_summary
async def fake_ocr(contents, filename, user_id=None, channel="web"):
    return "Appunti: parete 300 cm, altezza 270 cm, scarico da spostare"
server._ocr_image_bytes = fake_ocr


async def settle():
    for _ in range(40):
        await asyncio.sleep(0.03)


import weather as wx, client_updates as cu
from zoneinfo import ZoneInfo
ROME = ZoneInfo("Europe/Rome")
async def sunny(lat, lon, day):
    return {"rain_pct": 70, "wind_kmh": 10, "tmin": 8, "tmax": 14, "code": 61}
wx.provider = sunny
PINS = []
async def fake_pin_send(chat_id, text, kb):
    PINS.append(("send", chat_id, text, kb)); return 1000 + len(PINS)
async def fake_pin_edit(chat_id, mid, text, kb):
    PINS.append(("edit", chat_id, text, kb))
async def fake_pin_unpin(chat_id, mid):
    PINS.append(("unpin", chat_id, None, None))
server._day_pin_send, server._day_pin_edit, server._day_pin_unpin = fake_pin_send, fake_pin_edit, fake_pin_unpin
async def client_lines(title, notes, user_id=None):
    return ["Smontati i sanitari del bagno"] if notes else []
cu.summarize = client_lines
async def fake_commessa_summary(*a, **k):
    return {"stato": "Lavori conclusi.", "attivita": "Rifacimento del bagno."}
import work_reports
work_reports.commessa_summary = fake_commessa_summary
REPORTS = []
async def fake_deliver(current, docx_bytes, fname, folder, subs, caption):
    REPORTS.append((fname, " / ".join([folder] + list(subs)))); return "https://drive/r", "https://drive/f", False
server._deliver_work_report = fake_deliver


def at(day, hh, mm=0):
    return datetime.combine(day, datetime.min.time(), tzinfo=ROME).replace(hour=hh, minute=mm).astimezone(timezone.utc)


def to(chat):
    return [(t, kb) for c, t, kb in BOT_SENT if c == chat]


import json as _json, types
MODEL_EXTRAS = {"extras": []}
CALLS = []
class FakeCompletions:
    async def create(self, **k):
        CALLS.append(k["messages"][1]["content"])
        msg = types.SimpleNamespace(content=_json.dumps(MODEL_EXTRAS))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None, model="x", id="r1")
class FakeOpenAI:
    def __init__(self, *a, **k): self.chat = types.SimpleNamespace(completions=FakeCompletions())
jl.openai.AsyncOpenAI = FakeOpenAI


from datetime import date
import io, milestone_templates as mt
from starlette.datastructures import UploadFile


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_r", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    for sid, title in (("s1", "Impianto elettrico"), ("s2", "Allarme"), ("s3", "Cancello")):
        db.collection_sub_items.docs.append({"id": sid, "collection_id": cl["id"], "item_id": "c_r", "data": {"titolo": title, "stato": "nuova"}})

    # 0) the planned materials: quantities only when written; an old quote's lines read too
    text = "Materiali: 20 m corrugato 25, 12 scatole 503, centralino 12 moduli. Totale 3.000,00"
    pm = jl.clean_planned_materials([{"name": "corrugato 25", "qty": 20, "unit": "metri"}, {"name": "scatole 503", "qty": 15, "unit": "pz"},
                                     {"name": "centralino 12 moduli", "qty": None, "unit": ""}, {"name": "quadro inventato", "qty": 1, "unit": "pz"}], text)
    assert pm == [{"name": "corrugato 25", "qty": 20.0, "unit": "m"}, {"name": "scatole 503", "qty": None, "unit": ""},
                  {"name": "centralino 12 moduli", "qty": None, "unit": ""}], pm               # 15 is not written; the 4th is not in the text
    assert jl.planned_materials({"materials": ["20 m corrugato 25", "2 sacchi di colla"]}) == [
        {"name": "corrugato 25", "qty": 20.0, "unit": "m"}, {"name": "colla", "qty": 2.0, "unit": "sacchi"}]

    # 1) a quote with activities and the works' dates: milestones spread from start to end, in order
    QUOTE.clear(); QUOTE.update(total=3000.0, taxable=None, vat=None, items=[], start="2026-11-10", end="2026-11-20", validity="", payments=[],
                                activities=["Tracce", "Posa corrugati", "Cablaggio", "Montaggio frutti"], materials=["20 m corrugato 25"],
                                materials_planned=[{"name": "corrugato 25", "qty": 20.0, "unit": "m"}, {"name": "scatole 503", "qty": 12.0, "unit": "pz"},
                                                   {"name": "centralino 12 moduli", "qty": None, "unit": ""}],
                                description="", warranty="", warranty_months=None, maintenance=[])
    READ_DOC.update(kind="preventivo")
    up = await server._ingest_commessa_document(me, "s1", "prev.txt", b"PREVENTIVO impianto elettrico Totale 3.000,00 euro", "text/plain", hint="preventivo")
    assert up["plan_default"] == "milestone" and up["plan_dates"] == {"start": "2026-11-10", "end": "2026-11-20"}
    out = await server.confirm_quote(up["quote"]["id"], server.QuoteConfirmPayload(), me)
    ms = sorted([m for m in db.job_milestones.docs if m["commessa_id"] == "s1"], key=lambda m: m["due_date"])
    assert [m["title"] for m in ms] == ["Tracce", "Posa corrugati", "Cablaggio", "Montaggio frutti"]
    assert [m["due_date"] for m in ms] == [d.isoformat() for d in jl.spread_due_dates(4, date(2026, 11, 10), date(2026, 11, 20), mt.add_workdays, mt.workdays_between)]
    assert ms[-1]["due_date"] == "2026-11-20" and all(m["from_quote"] for m in ms)
    assert "🚩 Ho creato 4 milestone dalle attività del preventivo, dal" in out["message"] and "3 materiali previsti" in out["message"], out["message"]
    # a new version: the activities already there are not made twice
    QUOTE["activities"] = ["Tracce", "Posa corrugati", "Collaudo"]
    up = await server._ingest_commessa_document(me, "s1", "prev2.txt", b"PREVENTIVO v2 impianto elettrico Totale 3.200,00", "text/plain", hint="preventivo")
    await server.confirm_quote(up["quote"]["id"], server.QuoteConfirmPayload(value_choice="new"), me)
    assert [m["title"] for m in db.job_milestones.docs if m["commessa_id"] == "s1"][-1] == "Collaudo"
    assert len([m for m in db.job_milestones.docs if m["commessa_id"] == "s1"]) == 5

    # 2) no dates: To Do; the choice "Niente": nothing
    QUOTE.update(start="", end="", activities=["Smontaggio centrale vecchia", "Posa sirena"])
    up = await server._ingest_commessa_document(me, "s2", "prev.txt", b"PREVENTIVO allarme Totale 3.000,00 euro", "text/plain", hint="preventivo")
    assert up["plan_default"] == "todo"
    out = await server.confirm_quote(up["quote"]["id"], server.QuoteConfirmPayload(), me)
    assert [t["text"] for t in db.job_todos.docs if t["commessa_id"] == "s2"] == ["Smontaggio centrale vecchia", "Posa sirena"]
    assert "📌 Ho creato 2 To Do" in out["message"] and "senza date di inizio e fine" in out["message"]
    up = await server._ingest_commessa_document(me, "s3", "prev.txt", b"PREVENTIVO cancello Totale 3.000,00 euro", "text/plain", hint="preventivo")
    await server.confirm_quote(up["quote"]["id"], server.QuoteConfirmPayload(plan="none"), me)
    assert not [t for t in db.job_todos.docs if t["commessa_id"] == "s3"] and not [m for m in db.job_milestones.docs if m["commessa_id"] == "s3"]

    # 3) the materials section: planned against used (the diary), what is over, left, not foreseen
    for i, mats in enumerate(([{"name": "corrugato 25", "qty": 15, "unit": "m"}], [{"name": "corrugato 25", "qty": 10, "unit": "metri"},
                                                                                    {"name": "scatole 503", "qty": 4, "unit": "pz"}],
                              [{"name": "silicone", "qty": 1, "unit": "pz"}])):
        db.job_logs.docs.append({"id": f"lm{i}", "commessa_id": "s1", "date": f"2026-11-1{i}", "text": "lavori", "hours": [], "materials": mats, "problems": []})
    d = await server.get_job_commessa("s1", current=me)
    plan = d["materials_plan"]
    rows = {r["name"]: r for r in plan["rows"]}
    assert rows["corrugato 25"]["used"] == 25.0 and rows["corrugato 25"]["status"] == "oltre" and rows["corrugato 25"]["left"] == -5.0
    assert rows["scatole 503"]["used"] == 4.0 and rows["scatole 503"]["status"] == "in_uso" and rows["scatole 503"]["left"] == 8.0
    assert rows["centralino 12 moduli"]["status"] == "da_usare" and plan["unplanned"] == [{"name": "silicone", "qty": 1.0, "unit": "pz"}], plan
    assert plan["quote_version"] == 2
    # in the diary, for the chat and the reports
    ev = [lg for lg in db.job_logs.docs if lg.get("commessa_id") == "s1" and lg.get("kind") == "preventivo"][0]
    assert "Materiali previsti: 20 m corrugato 25; 12 pz scatole 503; centralino 12 moduli" in ev["text"], ev["text"]
    assert (await server.get_job_commessa("s3", current=me))["materials_plan"]["rows"]       # (same materials on the others)
    # 4) the quote reader: quantities from the items too ("1.200"), only the written numbers; the man-hours
    import importlib.util
    spec = importlib.util.spec_from_file_location("jl_fresh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "job_logs.py"))
    jlf = importlib.util.module_from_spec(spec); spec.loader.exec_module(jlf)
    doc = ("PREVENTIVO impianto elettrico\n1) Fornitura e posa corrugato Ø25 ml 1.200 x 0,80 = 960,00\n2) Scatole 503 n. 12 x 2,00 = 24,00\n"
           "3) Manodopera elettricista ore 32 x 30,00 = 960,00\n4) Manodopera aiutante ore 16 x 25,00 = 400,00\nTotale 2.344,00")
    MODEL_EXTRAS.clear(); MODEL_EXTRAS.update({
        "total": 2344, "items": [{"description": "Fornitura e posa corrugato Ø25", "qty": 1200, "unit": "ml", "unit_price": 0.8, "amount": 960},
                                 {"description": "Scatole 503", "qty": 12, "unit": "n.", "unit_price": 2, "amount": 24},
                                 {"description": "Manodopera elettricista", "qty": 32, "unit": "ore", "unit_price": 30, "amount": 960},
                                 {"description": "Manodopera aiutante", "qty": 16, "unit": "ore", "unit_price": 25, "amount": 400}],
        "materials_planned": [{"name": "corrugato Ø25", "qty": 1200, "unit": "ml"}, {"name": "scatole 503", "qty": 12, "unit": "n."},
                              {"name": "scatole 503", "qty": 120, "unit": "pz"}],
        "labor_hours": 50, "labor": ["Manodopera elettricista ore 32", "Manodopera aiutante ore 16"]})
    q = await jlf.read_quote(doc, {"title": "Impianto", "client_name": "Mario Rossi"})
    assert [(i["qty"], i["unit"]) for i in q["items"]] == [(1200.0, "m"), (12.0, "pz"), (32.0, "ore"), (16.0, "ore")], q["items"]
    assert q["materials_planned"][:2] == [{"name": "corrugato Ø25", "qty": 1200.0, "unit": "m"}, {"name": "scatole 503", "qty": 12.0, "unit": "pz"}]
    assert q["materials_planned"][2]["qty"] is None                     # 120 is not written: not taken
    assert q["labor_hours"] == 48.0, q["labor_hours"]                    # 50 is not written: the items in hours added up (32 + 16)
    MODEL_EXTRAS["labor_hours"] = 48
    assert (await jlf.read_quote(doc + "\nTotale ore uomo 48", {"title": "x"}))["labor_hours"] == 48.0
    assert "Ore uomo previste: 48 h" in "\n".join(jlf.quote_detail_lines(q))

    # 5) the Ore section: the man-hours planned against the ones written in the diary
    QUOTE.update(labor_hours=48.0, labor=["Manodopera elettricista ore 32"], start="", end="", activities=[])
    up = await server._ingest_commessa_document(me, "s1", "prev3.txt", b"PREVENTIVO v3 impianto elettrico Totale 3.300,00", "text/plain", hint="preventivo")
    assert "👷 Ore uomo previste: 48 h" in up["message"] and "🧰 Materiali previsti (3, 2 con la quantità)" in up["message"], up["message"]
    await server.confirm_quote(up["quote"]["id"], server.QuoteConfirmPayload(value_choice="new"), me)
    db.job_logs.docs.append({"id": "lh1", "commessa_id": "s1", "date": "2026-11-12", "text": "lavori", "hours": [{"who": "Luca", "hours": 20}], "materials": [], "problems": []})
    db.job_logs.docs.append({"id": "lh2", "commessa_id": "s1", "date": "2026-11-13", "text": "lavori", "hours": [{"who": "Gino", "hours": 16}], "materials": [], "problems": []})
    hp = (await server.get_job_commessa("s1", current=me))["hours_plan"]
    assert hp["planned"] == 48.0 and hp["done"] == 36.0 and hp["left"] == 12.0 and hp["pct"] == 75 and hp["quote_version"] == 3, hp
    rep = await server._job_weekly_summary(me, datetime(2026, 11, 13, 18, 0, tzinfo=ROME))
    assert "👷 Ore: 36 h fatte di 48 previste dal preventivo (75%)" in rep, rep
    print("ALL OK")

asyncio.run(main())
