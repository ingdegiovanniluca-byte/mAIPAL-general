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

# a quote with two alternative solutions (like an automatic barrier offered in two versions)
QTEXT = """OFFERTA
Pagamento 30% all'ordine - saldo fine lavori
Descrizione U.M. Quantità Prezzo
OFFERTA PER FORNITURA ED INSTALLAZIONE SBARRA AUTOMATICA - soluzione 1
BARRIERA MOD.615 per aste fino 5m NR 1
MOLLA BILANCIAMENTO NR 1
LAMPEGGIANTE NR 1
COPPIA DI FOTOCELLULE REFLEX NR 1
TOTALE €2.650,00 +IVA
Comprensivo di fornitura, installazione, collaudo e due anni di garanzia.
OPTIONAL: kit luci asta +€250,00+IVA
OFFERTA PER FORNITURA ED INSTALLAZIONE SBARRA AUTOMATICA - soluzione 2
BARRIERA MOD.B614 per aste fino a 6m - uso intensivo NR 1
MOLLA DI BILANCIAMENTO NR 2
LAMPEGGIANTE SEMAFORICO INTEGRATO NR 1
COPPIA DI FOTOCELLULE REFLEX NR 1
TOTALE €2.850,00 +IVA
OPTIONAL: kit luci asta +€150,00+IVA
VALIDITA' OFFERTA: 30 gg."""

def opt(name, title, total, items, optional):
    return {"name": name, "title": title, "total": total, "taxable": None,
            "items": [{"description": d, "qty": q, "unit": "NR", "unit_price": None, "amount": None} for d, q in items],
            "materials_planned": [{"name": d, "qty": q, "unit": "NR"} for d, q in items],
            "activities": ["Installazione della sbarra", "Collaudo"], "optionals": [{"description": "kit luci asta", "amount": optional}]}
MODEL_QUOTE = {"total": 5500, "taxable": None, "items": [], "materials_planned": [], "activities": ["Installazione della sbarra", "Collaudo"],
               "payments": ["30% all'ordine - saldo fine lavori"], "description": "Fornitura e installazione di una sbarra automatica.",
               "options": [opt("Soluzione 1", "barriera MOD.615 per aste fino 5m", 2650, [("BARRIERA MOD.615 per aste fino 5m", 1), ("MOLLA BILANCIAMENTO", 1),
                                                                                    ("LAMPEGGIANTE", 1), ("COPPIA DI FOTOCELLULE REFLEX", 1)], 250),
                           opt("Soluzione 2", "barriera MOD.B614 uso intensivo", 2850, [("BARRIERA MOD.B614 per aste fino a 6m - uso intensivo", 1),
                                                                                       ("MOLLA DI BILANCIAMENTO", 2), ("LAMPEGGIANTE SEMAFORICO INTEGRATO", 1),
                                                                                       ("COPPIA DI FOTOCELLULE REFLEX", 1)], 150),
                           {"name": "Soluzione 3", "title": "inventata", "total": 9999, "items": [], "materials_planned": []}]}
class QuoteCompletions:
    async def create(self, **k):
        msg = types.SimpleNamespace(content=_json.dumps(MODEL_QUOTE))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None, model="x", id="r1")
class QuoteOpenAI:
    def __init__(self, *a, **k): self.chat = types.SimpleNamespace(completions=QuoteCompletions())


def note(materials=None, expenses=None, text=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web", photos=0):
        return {"kind": "nota", "doubt": "", "date": jl.today_local().isoformat(), "text": text or t, "hours": [],
                "materials": jl.clean_materials(materials or []), "problems": [], "expenses": expenses or [], "client": "", "commessa": ""}
    return f


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s1", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Sbarra", "stato": "nuova"}})
    db.collection_sub_items.docs.append({"id": "s2", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Sbarra garage", "stato": "nuova"}})

    # 1) reading: two solutions, each with its total, items, materials and optional; the sum and the invented one dropped
    import job_logs as real_jl
    # the real reader (the fake one is installed by the header): reloaded in its own module object
    import importlib.util
    spec = importlib.util.spec_from_file_location("jl_real", os.path.join(os.path.dirname(os.path.abspath(real_jl.__file__)), "job_logs.py"))
    jl_real = importlib.util.module_from_spec(spec); spec.loader.exec_module(jl_real)
    jl_real.openai.AsyncOpenAI = QuoteOpenAI
    jl_real._track = lambda *a, **k: None
    view = (await server._commessa_ctx("s1"))[3]
    q = await jl_real.read_quote(QTEXT, view)
    assert q["total"] is None and q["items"] == [] and q["materials_planned"] == [], q        # 5.500 is not written: not the total
    assert [o["name"] for o in q["options"]] == ["Soluzione 1", "Soluzione 2"], q["options"]   # 9.999 nowhere: dropped
    assert [o["total"] for o in q["options"]] == [2650.0, 2850.0] and q["options"][1]["optionals"] == [{"description": "kit luci asta", "amount": 150.0}]
    assert [m["qty"] for m in q["options"][1]["materials_planned"]] == [1.0, 2.0, 1.0, 1.0]
    one = dict(MODEL_QUOTE); one = {**one, "options": [], "total": 2650, "optionals": [{"description": "kit luci asta", "amount": 250}]}
    MQ = dict(MODEL_QUOTE); MODEL_QUOTE.clear(); MODEL_QUOTE.update(one)
    q1 = await jl_real.read_quote(QTEXT, view)
    assert q1["total"] == 2650.0 and q1["options"] == [] and q1["optionals"] == [{"description": "kit luci asta", "amount": 250.0}]
    MODEL_QUOTE.clear(); MODEL_QUOTE.update(MQ)

    # 2) the proposal: the solutions listed, no value until one is chosen
    QUOTE.clear(); QUOTE.update(q)
    clienti, sub, client, view = await server._commessa_ctx("s1")
    p = await server._quote_proposal(me, clienti, sub, view, "offerta.txt", QTEXT.encode(), "text/plain", QTEXT)
    assert p["value"] is None and [o["name"] for o in p["options"]] == ["Soluzione 1", "Soluzione 2"] and p["options"][1]["value"] == 2850.0
    assert "🔀 2 soluzioni alternative:\n1) Soluzione 1 — barriera MOD.615 per aste fino 5m: totale" in p["message"], p["message"]
    assert "optional: kit luci asta" in p["message"] and "Totale: non lo trovo" not in p["message"] and "Su quale soluzione lavoriamo?" in p["message"]

    # 3) confirmed, the solution chosen later: no value, no materials, no structure yet
    out = await server.confirm_quote(p["quote"]["id"], server.QuoteConfirmPayload(), me)
    qid = p["quote"]["id"]
    saved = next(x for x in db.job_quotes.docs if x["id"] == qid)
    assert saved["option_pending"] and out["options"] == ["Soluzione 1", "Soluzione 2"] and "soluzioni alternative" in out["message"]
    assert not next((e for e in db.job_economics.docs if e["commessa_id"] == "s1"), {}).get("budget")
    d = await server.get_job_commessa("s1", current=me)
    assert d["materials_plan"] is None and not [m for m in db.job_milestones.docs if m.get("commessa_id") == "s1"]
    assert any("Soluzioni alternative (da scegliere)" in (lg.get("text") or "") for lg in db.job_logs.docs if lg.get("commessa_id") == "s1")
    # a material used before the choice: nothing to compare with, nothing said
    jl.interpret = note([{"name": "interruttore 50 A", "qty": 1, "unit": "pz"}])
    r = await server._save_job_log(me, "montato un interruttore 50 A", commessa_id="s1")
    assert "Non previsto" not in r["message"]

    # 4) the client accepted: asked which solution (Telegram buttons)
    out = await server._quote_outcome(me, "s1", "accettato")
    assert out["choose_option"] == {"quote_id": qid, "options": ["Soluzione 1", "Soluzione 2"]} and "Quale soluzione ha scelto il cliente?" in out["message"]
    BOT_SENT.clear()
    await tg._on_callback(Upd(77, data=f"qs:{qid}:1"), Ctx())
    txt = to(77)[-1][0]
    assert "Soluzione 2" in txt and "Valore della commessa: 2.850" in txt.replace("€ ", "").replace(" €", ""), txt
    assert next(e for e in db.job_economics.docs if e["commessa_id"] == "s1")["budget"] == 2850.0
    saved = next(x for x in db.job_quotes.docs if x["id"] == qid)
    assert not saved["option_pending"] and saved["data"]["chosen_option"] == 1 and saved["data"]["total"] == 2850.0
    assert any("Soluzione scelta" in (lg.get("text") or "") and "Soluzione 2" in lg["text"] for lg in db.job_logs.docs if lg.get("commessa_id") == "s1")

    # 5) the materials of the solution: ticked when the diary says they were used, or by hand
    d = await server.get_job_commessa("s1", current=me)
    mp = d["materials_plan"]
    assert [r_["name"] for r_ in mp["rows"]][:2] == ["BARRIERA MOD.B614 per aste fino a 6m - uso intensivo", "MOLLA DI BILANCIAMENTO"] and mp["total"] == 4
    jl.interpret = note([{"name": "barriera B614", "qty": 1, "unit": "NR"}, {"name": "molla di bilanciamento", "qty": 1, "unit": "NR"}])
    await server._save_job_log(me, "montata la barriera B614 e 1 molla di bilanciamento", commessa_id="s1")
    mp = (await server.get_job_commessa("s1", current=me))["materials_plan"]
    rows = {r_["name"]: r_ for r_ in mp["rows"]}
    assert rows["BARRIERA MOD.B614 per aste fino a 6m - uso intensivo"]["done"] and not rows["MOLLA DI BILANCIAMENTO"]["done"]   # 1 of 2
    assert mp["done"] == 1
    out = await server.set_material_done("s1", server.MaterialDonePayload(name="LAMPEGGIANTE SEMAFORICO INTEGRATO", unit="pz", done=True), me)
    rows = {r_["name"]: r_ for r_ in out["materials_plan"]["rows"]}
    assert rows["LAMPEGGIANTE SEMAFORICO INTEGRATO"]["done"] and rows["LAMPEGGIANTE SEMAFORICO INTEGRATO"]["manual"] is True and out["materials_plan"]["done"] == 2
    out = await server.set_material_done("s1", server.MaterialDonePayload(name="LAMPEGGIANTE SEMAFORICO INTEGRATO", unit="pz", done=None), me)
    assert out["materials_plan"]["done"] == 1                                                       # back to the diary's

    # 6) a material not foreseen, with its price: said, flagged once as a possible extra, its cost counted once
    jl.interpret = note([{"name": "interruttore da 50 A", "qty": 1, "unit": "pz"}],
                        [{"description": "interruttore da 50 A", "amount": 50.0, "supplier": ""}])
    BOT_SENT.clear()
    r = await server._save_job_log(me, "ho usato un interruttore da 50 A con costo di 50 €", commessa_id="s1")
    await settle()
    assert "⚠️ Non previsto nel preventivo v1: 1 pz interruttore da 50 A — segnalato tra i possibili lavori extra (Preventivo)." in r["message"], r["message"]
    assert "🧰 Materiali: 1 pz interruttore da 50 A (" in r["message"] and "💶 Spese" not in r["message"], r["message"]
    xw = [x for x in db.job_extra_works.docs if x.get("kind") == "materiale"]
    assert len(xw) == 1 and xw[0]["work"] == "Materiale non previsto: 1 pz interruttore da 50 A" and xw[0]["status"] == "da_valutare"
    txt, kb = to(77)[-1]
    assert "Materiale non previsto" in txt and "pagato" in txt and buttons(kb)[0] == f"xw:extra:{xw[0]['id']}"
    e = await server.get_commessa_economics("s1", current=me)
    m = next(x for x in e["materials"] if x["name"] == "interruttore da 50 A")
    assert m["paid"] == 50.0 and m["cost"] == 50.0 and e["extras"] == [] and e["materials_total"] == 50.0, e
    assert "interruttore da 50 A" not in e["unpriced_materials"]
    # used again: said again, not flagged twice
    jl.interpret = note([{"name": "interruttore 50 A", "qty": 1, "unit": "pz"}])
    r = await server._save_job_log(me, "montato un altro interruttore 50 A", commessa_id="s1")
    assert "Non previsto nel preventivo v1" in r["message"] and "segnalato" not in r["message"]
    assert len([x for x in db.job_extra_works.docs if x.get("kind") == "materiale"]) == 1

    # 7) confirmed with the solution at once (app / Telegram "qc:<id>:o0")
    QUOTE.clear(); QUOTE.update(q)
    clienti, sub, client, view = await server._commessa_ctx("s2")
    p = await server._quote_proposal(me, clienti, sub, view, "offerta.txt", QTEXT.encode(), "text/plain", QTEXT)
    BOT_SENT.clear()
    await tg._on_callback(Upd(77, data=f"qc:{p['quote']['id']}:o0"), Ctx())
    txt = to(77)[-1][0]
    assert "🔀 Soluzione: Soluzione 1." in txt and "2.650" in txt, txt
    saved = next(x for x in db.job_quotes.docs if x["id"] == p["quote"]["id"])
    assert saved["data"]["chosen_option"] == 0 and not saved["option_pending"] and saved["data"]["optionals"][0]["amount"] == 250.0
    assert next(e for e in db.job_economics.docs if e["commessa_id"] == "s2")["budget"] == 2650.0
    # changed later: the other solution's value is the administrator's choice
    out = await server.choose_quote_option(p["quote"]["id"], server.QuoteOptionPayload(option=1, value_choice="new"), me)
    assert "Valore aggiornato: € 2.850 (era € 2.650)" in out["message"], out["message"]
    await deny(server.choose_quote_option(p["quote"]["id"], server.QuoteOptionPayload(option=5), me), 400)

    # 8) the materials of a quote without a list of them: its items with a quantity (not installation, not hours)
    pm = jl.planned_materials({"items": [{"description": "Centrale allarme", "qty": 1, "unit": "pz"}, {"description": "Installazione e collaudo", "qty": 1, "unit": "pz"},
                                         {"description": "Manodopera", "qty": 16, "unit": "ore"}, {"description": "Cavo 4x0,22", "qty": 100, "unit": "m"}]})
    assert [x["name"] for x in pm] == ["Centrale allarme", "Cavo 4x0,22"], pm
    # those who don't see the costs: the solutions without their amounts
    pub = server._quote_without_money(saved)
    assert "total" not in pub["data"]["options"][0] and pub["data"]["options"][0]["name"] == "Soluzione 1"
    print("ALL OK")

asyncio.run(main())
