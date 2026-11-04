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


import importlib.util, io
from starlette.datastructures import UploadFile
_spec = importlib.util.spec_from_file_location("jl_fresh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "job_logs.py"))
jlf = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(jlf)   # the real quote reader (the shared one is faked)

QDATA = dict(total=12200.0, taxable=10000.0, vat=2200.0, items=[{"description": "Centrale allarme 8 zone", "amount": 900.0},
             {"description": "Sensori volumetrici", "amount": 1200.0}], start="", end="", validity="", payments=["50% all'ordine", "saldo a fine lavori"],
             activities=["Posa centrale", "Cablaggio sensori"], materials=["centrale 8 zone"], description="",
             warranty="garanzia 2 anni su materiali e manodopera", warranty_months=24,
             maintenance=[{"text": "verifica semestrale dell'impianto di allarme", "every_months": 6},
                          {"text": "sostituzione batterie dei sensori", "every_months": None}])


class TgFile:
    async def download_as_bytearray(self): return bytearray(b"OFFERTA impianto allarme Totale 12.200,00")
class TgBot:
    async def get_file(self, fid): return TgFile()
    async def send_message(self, chat_id=None, text=None, reply_markup=None, **k): BOT_SENT.append((chat_id, text, reply_markup))
class TgCtx: bot = TgBot()


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_lucad", "collection_id": cl["id"], "data": {"nome": "Luca D"}})
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_all", "collection_id": cl["id"], "item_id": "c_lucad", "data": {"titolo": "Impianto allarme", "stato": "nuova"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "nuova"}})

    # 0) the quote reader: warranty and maintenance only when written, how often from the words
    MODEL_EXTRAS.clear(); MODEL_EXTRAS.update({"total": 12200, "taxable": 10000, "items": [], "activities": [], "materials": [], "payments": [],
                                               "warranty": "garanzia 2 anni su materiali e manodopera",
                                               "maintenance": ["verifica semestrale dell'impianto di allarme", "manutenzione annuale del condizionatore"],
                                               "description": ""})
    src = "Totale imponibile 10.000,00 Totale 12.200,00. Garanzia 2 anni su materiali e manodopera. Verifica semestrale dell'impianto di allarme."
    q = await jlf.read_quote(src, {"title": "Impianto allarme", "client_name": "Luca D"})
    assert q["warranty"] == "garanzia 2 anni su materiali e manodopera" and q["warranty_months"] == 24
    assert q["maintenance"] == [{"text": "verifica semestrale dell'impianto di allarme", "every_months": 6}], q["maintenance"]   # the 2nd is not in the text
    assert jlf.months_every("manutenzione annuale caldaia") == 12 and jlf.months_every("controllo ogni 3 mesi") == 3 and jlf.months_every("pulizia filtri") is None

    # 1) Salva chat: "questo è il preventivo della commessa impianto allarme di Luca D" + the file -> that commessa's quote
    QUOTE.clear(); QUOTE.update(QDATA)
    READ_DOC.update(kind="altro")                    # the content alone would not say it: the words do
    r = await server.quote_from_chat(UploadFile(file=io.BytesIO(b"OFFERTA ... Totale 12.200,00"), filename="offerta.txt"),
                                     "questo è il preventivo della commessa impianto allarme di Luca D", None, me)
    assert r["type"] == "quote" and r["quote"]["commessa_id"] == "s_all" and r["value"] == 10000.0, r
    assert "🛡 Garanzia: garanzia 2 anni" in r["message"] and "🔧 Manutenzione prevista: verifica semestrale" in r["message"]
    # no commessa in the words: the choices; then the one chosen
    r2 = await server.quote_from_chat(UploadFile(file=io.BytesIO(b"PREVENTIVO bagno Rossi Totale 5.000,00 euro"), filename="p.txt"), "ecco il preventivo", None, me)
    assert r2["type"] == "pick_commessa" and {c["commessa_id"] for c in r2["candidates"]} == {"s_all", "s_bagno"}, r2
    r3 = await server.quote_from_chat(UploadFile(file=io.BytesIO(b"PREVENTIVO bagno Rossi Totale 5.000,00 euro"), filename="p.txt"), "ecco il preventivo", "s_bagno", me)
    assert r3["type"] == "quote" and r3["quote"]["commessa_id"] == "s_bagno"
    await server.discard_quote(r3["quote"]["id"], me)

    # 2) Telegram: "preventivo" in the caption -> always a quote (the content would say "altro")
    BOT_SENT.clear()
    await tg._ingest_tg_document(TgCtx(), 77, db, db.users.docs[0], "s_all", {"file_id": "f1", "name": "offerta.txt", "mime": "text/plain",
                                                                               "caption": "preventivo allarme Luca D"})
    txt, kb = BOT_SENT[-1][1], BOT_SENT[-1][2]
    assert "📄 Preventivo per «Impianto allarme» — Luca D" in txt and buttons(kb)[0].startswith("qc:"), (txt, buttons(kb))
    # without the word: as before, from the content (here a note)
    BOT_SENT.clear()
    READ_DOC.update(kind="altro", description="Scheda tecnica della centrale", amount=None, amount_basis="")
    await tg._ingest_tg_document(TgCtx(), 77, db, db.users.docs[0], "s_all", {"file_id": "f2", "name": "scheda.txt", "mime": "text/plain", "caption": "scheda centrale"})
    assert not BOT_SENT[-1][1].startswith("📄 Preventivo"), BOT_SENT[-1][1]

    # 3) confirmed: in the diary with what it says (the commessa's chat, reports and searches read it)
    out = await server.confirm_quote(r["quote"]["id"], server.QuoteConfirmPayload(), me)
    ev = next(lg for lg in db.job_logs.docs if lg.get("commessa_id") == "s_all" and lg.get("kind") == "preventivo")
    for part in ("Voci: Centrale allarme 8 zone; Sensori volumetrici", "Attività previste: Posa centrale; Cablaggio sensori",
                 "Pagamenti: 50% all'ordine; saldo a fine lavori", "Garanzia: garanzia 2 anni su materiali e manodopera",
                 "Manutenzione prevista: verifica semestrale dell'impianto di allarme; sostituzione batterie dei sensori"):
        assert part in ev["text"], (part, ev["text"])
    SEEN = []
    async def capture(commessa, logs, reports, question, history, user_id=None, channel="web"):
        SEEN.append(logs); return {"answer": "Garanzia 2 anni.", "is_entry": False}
    jl.answer = capture
    await server.ask_job_commessa("s_all", server.CommessaAskPayload(question="quanto dura la garanzia?"), me)
    assert any("Garanzia: garanzia 2 anni" in (lg.get("text") or "") for lg in SEEN[-1])
    # in the commessa's report
    rep = await server._generate_commessa_report(me, server.CommessaReportPayload(commessa_id="s_all", include=["stato"]))
    f = rep["sections"][0]["fields"]
    assert f["Garanzia"] == "garanzia 2 anni su materiali e manodopera" and "- verifica semestrale" in f["Manutenzione prevista"] and f["Preventivo"].startswith("v1"), f

    # 4) the works concluded: the maintenance as recurring reminders, the warranty's end, what has no frequency pointed out
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == "s_all")
    sub["data"]["stato"] = "in lavorazione"
    NOTICES.clear()
    await server.set_job_commessa_stato("s_all", server.CommessaStatoPayload(stato="completata", confirm_close=True), me)
    await settle()
    today = jl.today_local()
    tasks = [t for t in db.tasks.docs if t.get("commessa_id") == "s_all"]
    mt = next(t for t in tasks if t["kind"] == "manutenzione")
    assert mt["title"] == "Manutenzione: verifica semestrale dell'impianto di allarme — Luca D" and mt["due_date"] == server._add_months(today, 6).isoformat()
    assert mt["reminder_enabled"] and mt.get("series_id") and next(x for x in db.task_series.docs if x["id"] == mt["series_id"])["rule"]["interval"] == 6
    wt = next(t for t in tasks if t["kind"] == "garanzia")
    assert wt["due_date"] == server._add_months(today, 23).isoformat() and "Scade tra un mese la garanzia" in wt["title"]
    note = next(t for c, t in NOTICES if "ho fissato i promemoria dal preventivo" in t)
    assert "verifica semestrale dell'impianto di allarme: dal" in note and "poi ogni 6 mesi" in note
    assert "Senza frequenza scritta (dimmi ogni quanto e lo fisso): sostituzione batterie dei sensori" in note
    assert any(lg.get("kind") == "manutenzione" for lg in db.job_logs.docs)
    n = len(db.tasks.docs)
    await server._maintenance_reminders(me, cl, "s_all")
    assert len(db.tasks.docs) == n                                                       # once
    # 5) the commessa's page always opens: a part that fails is left out (and logged), no NaN in the answer
    real_q, real_h = server._commessa_quotes, server._commessa_history
    async def broken(*a, **k): raise RuntimeError("bad data")
    server._commessa_quotes, server._commessa_history = broken, broken
    d = await server.get_job_commessa("s_all", current=me)
    assert d["quotes"] == [] and d["history"] == [] and d["commessa"]["id"] == "s_all" and d["logs"]
    server._commessa_quotes, server._commessa_history = real_q, real_h
    assert server._json_safe({"a": float("nan"), "b": [1.5, float("inf")], "c": "x"}) == {"a": None, "b": [1.5, None], "c": "x"}
    print("ALL OK")

asyncio.run(main())
