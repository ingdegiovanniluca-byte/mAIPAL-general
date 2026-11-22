import asyncio, os, sys, copy
from datetime import datetime, timezone, timedelta
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import server, scheduled_actions as sa, list_updates as lu, usage_tracking as ut, retrieval

def _get(doc, k):
    for part in k.split("."):   # ("meta.log_id")
        doc = doc.get(part) if isinstance(doc, dict) else None
    return doc

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
CALLS, SYSTEMS = [], []
class FakeCompletions:
    async def create(self, **k):
        CALLS.append(k["messages"][1]["content"]); SYSTEMS.append(k["messages"][0]["content"])
        msg = types.SimpleNamespace(content=_json.dumps(MODEL_EXTRAS))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None, model="x", id="r1")
class FakeOpenAI:
    def __init__(self, *a, **k): self.chat = types.SimpleNamespace(completions=FakeCompletions())
jl.openai.AsyncOpenAI = FakeOpenAI


INTERP = []
async def fake_interpret(text, sections, user_name="", user_id=None, channel="web", report_name=""):
    INTERP.append(text)
    secs = [{"title": s["title"], "fields": {f: "" for f in s["fields"]}} for s in sections]
    return {"sections": secs, "client": {"name": "", "phone": "", "email": "", "address": ""}, "job_title": "", "summary": "ok"}
work_reports.interpret = fake_interpret


async def main():
    """The report's chat: several messages, the type and the commessa understood (asked with buttons only when not clear),
    the active commesse on request, the report only when asked - from everything said; saved in the commessa's Report folder,
    or in Report/<type> without one."""
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_items.docs.append({"id": "c_verdi", "collection_id": cl["id"], "data": {"nome": "Anna Verdi"}})
    for sid, item, title in (("s1", "c_rossi", "Manutenzione caldaia"), ("s2", "c_rossi", "Bagno"), ("s3", "c_verdi", "Manutenzione centrale termica")):
        db.collection_sub_items.docs.append({"id": sid, "collection_id": cl["id"], "item_id": item,
                                             "data": {"titolo": title, "stato": "in lavorazione", "codice": f"2026-00{sid[-1]}"}})
    n_items = len(db.collection_items.docs)
    chat = lambda **k: server.report_chat(server.ReportChatPayload(**k), me)

    # 1) the first message names the type and the client with two commesse: kept, the commessa asked (buttons)
    r = await chat(text="SAL dai Rossi: oggi smontata la caldaia vecchia")
    d = r["draft"]
    assert d["report_type"] == "sal" and d["messages"] == 1 and d["commessa"] is None, r
    assert r["ask"]["kind"] == "commessa" and {o["commessa_id"] for o in r["ask"]["options"]} == {"s1", "s2"}, r["ask"]
    # 2) more messages: kept, nothing generated yet
    r = await chat(draft_id=d["id"], text="montata la nuova caldaia a condensazione, fatta la prova fumi")
    assert r["draft"]["messages"] == 2 and not r["report"] and not REPORTS
    # 3) "quali commesse attive ha Rossi?" / "commesse di manutenzione attive": listed to choose, not written in the report
    r = await chat(draft_id=d["id"], text="quali commesse attive ha Rossi?")
    assert {o["title"] for o in r["ask"]["options"]} == {"Manutenzione caldaia", "Bagno"} and r["draft"]["messages"] == 2
    r = await chat(draft_id=d["id"], text="commesse di manutenzione attive")
    assert {o["title"] for o in r["ask"]["options"]} == {"Manutenzione caldaia", "Manutenzione centrale termica"}, r["ask"]
    # 4) the button: the commessa; then "genera": one report from all the messages, in the commessa's Report folder
    r = await server.report_chat_set(d["id"], server.ReportChatSet(commessa_id="s1"), me)
    assert r["draft"]["commessa"]["title"] == "Manutenzione caldaia"
    REPORTS.clear(); INTERP.clear()
    r = await chat(draft_id=d["id"], text="genera il report")
    rep = r["report"]
    assert rep and rep["commessa_id"] == "s1" and rep["client_name"] == "Mario Rossi" and rep["template_name"] and not rep["commessa_created"], r
    assert "smontata la caldaia vecchia" in INTERP[-1] and "prova fumi" in INTERP[-1], INTERP
    assert REPORTS[-1][1] == "Clienti / Mario Rossi / 2026-001 – Manutenzione caldaia / Report", REPORTS
    assert len(db.collection_items.docs) == n_items   # no client made up
    # a new message after it: a new draft (the app revises the report made, see the chat)
    r = await chat(draft_id=d["id"], text="intervento da Anna Verdi, sostituito il circolatore")
    assert r["draft"]["id"] != d["id"] and r["draft"]["commessa"]["title"] == "Manutenzione centrale termica"

    # 5) no type, no commessa: asked at "genera"; "Nessuna commessa" -> the Report folder, by type
    r = await chat(text="sostituito il termostato al piano terra")
    d2 = r["draft"]
    assert r["ask"]["kind"] == "type" and any(o["key"] == "intervento" for o in r["ask"]["options"]), r["ask"]
    r = await chat(draft_id=d2["id"], generate=True)
    assert r["ask"]["kind"] == "type" and not r["report"]
    r = await server.report_chat_set(d2["id"], server.ReportChatSet(report_type="intervento"), me)
    assert r["ask"]["kind"] == "commessa" and r["ask"]["allow_none"] and not r["report"], r
    REPORTS.clear()
    r = await server.report_chat_set(d2["id"], server.ReportChatSet(no_commessa=True), me)
    rep = r["report"]
    assert rep and not rep["commessa_id"] and not rep["client_name"], r
    assert REPORTS[-1][1] == f"Report / {rep['template_name']}", REPORTS
    assert len(db.collection_items.docs) == n_items
    # no commessa but a client named who is already there: in the client's folder; still nothing added
    r = await chat(text="intervento dal signor Mario Rossi: cambiato il rubinetto del bagno")
    d3 = r["draft"]
    n_subs = len(db.collection_sub_items.docs)
    await server.report_chat_set(d3["id"], server.ReportChatSet(no_commessa=True), me)
    r = await chat(draft_id=d3["id"], text="genera il report")
    rep = r["report"]
    assert rep and not rep["commessa_id"] and rep["client_name"] == "Mario Rossi", r
    assert REPORTS[-1][1] == "Clienti / Mario Rossi", REPORTS
    assert len(db.collection_items.docs) == n_items and len(db.collection_sub_items.docs) == n_subs
    # 6) the commesse asked in other words: "dimmi l'elenco delle commesse", "che lavori ho?", a client said a little wrong
    db.collection_sub_items.docs.append({"id": "s4", "collection_id": cl["id"], "item_id": "c_verdi",
                                         "data": {"titolo": "Tettoia", "stato": "completata", "codice": "2026-004"}})
    all_open = {"Manutenzione caldaia", "Bagno", "Manutenzione centrale termica"}
    for q in ("dimmi l'elenco delle commesse", "dammi la lista delle commesse", "che lavori ho?", "elenco dei cantieri aperti",
              "quali commesse abbiamo attive?"):
        r = await chat(text=q)
        assert {o["title"] for o in r["ask"]["options"]} == all_open and "Non ho trovato" not in r["reply"], (q, r["ask"], r["reply"])
        assert r["draft"]["messages"] == 0, q   # a question, not a line of the report
    r = await chat(text="quali sono le commesse del signor Rosi")       # (dictated: Rossi)
    assert {o["title"] for o in r["ask"]["options"]} == {"Manutenzione caldaia", "Bagno"} and "Mario Rossi" in r["reply"], r
    r = await chat(text="lavori di Verdi?")
    assert {o["title"] for o in r["ask"]["options"]} == {"Manutenzione centrale termica"}, r
    r = await chat(text="commesse chiuse di Anna Verdi")
    assert {o["title"] for o in r["ask"]["options"]} == {"Manutenzione centrale termica", "Tettoia"}, r
    r = await chat(text="mostrami le commesse della piscina")
    assert {o["title"] for o in r["ask"]["options"]} == all_open and "Non ho trovato commesse per «piscina»" in r["reply"], r
    # a long dictation that says "lavori" is a line of the report, not a question
    r = await chat(text="SAL: lavori di rifacimento della centrale termica, che lavori restano li vediamo la settimana prossima con il cliente in cantiere")
    assert r["draft"]["messages"] == 1 and r["draft"]["report_type"] == "sal", r

    # 7) the conversation stays in the Chat's Cronologia: the messages, the buttons; a message sent twice (offline) kept once
    r = await chat(draft_id="rdr_0123456789ab", text="intervento da Anna Verdi, cambiato il vaso di espansione", client_id="m1",
                   written_at="2026-11-20T08:00:00+00:00")
    assert r["draft"]["id"] == "rdr_0123456789ab" and r["conv_id"]   # the app's own id: the messages kept offline join it
    conv = next(c for c in db.conversations.docs if c["conv_id"] == r["conv_id"])
    assert conv["action"] == "work_report" and conv["report_draft_id"] == "rdr_0123456789ab"
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"] and "vaso di espansione" in conv["messages"][0]["content"]
    r2 = await chat(draft_id="rdr_0123456789ab", text="intervento da Anna Verdi, cambiato il vaso di espansione", client_id="m1", conv_id=r["conv_id"])
    assert r2.get("duplicate") and r2["draft"]["messages"] == 1
    d6 = db.report_drafts.docs[-1]
    assert d6["messages"][0]["at"] == "2026-11-20T08:00:00+00:00"
    r = await chat(draft_id="rdr_0123456789ab", text="e ripristinata la pressione", client_id="m2", conv_id=r["conv_id"])
    conv = next(c for c in db.conversations.docs if c["conv_id"] == r["conv_id"])
    assert len(conv["messages"]) == 4 and conv["messages"][-1].get("reportGen") == "rdr_0123456789ab", conv["messages"][-1]
    r = await chat(draft_id="rdr_0123456789ab", generate=True, conv_id=r["conv_id"])
    conv = next(c for c in db.conversations.docs if c["conv_id"] == r["conv_id"])
    assert conv["messages"][-2]["content"] == "Genera report" and not conv["messages"][-3].get("reportGen")
    if r["report"]:
        assert conv["messages"][-1].get("reportId") == r["report"]["id"]
    else:   # (the commessa asked: its buttons are in the conversation)
        assert conv["messages"][-1]["reportAsk"]["kind"] == "commessa" and conv["messages"][-1]["reportAsk"]["draftId"] == "rdr_0123456789ab"
        r = await server.report_chat_set("rdr_0123456789ab", server.ReportChatSet(commessa_id="s3"), me)
        conv = next(c for c in db.conversations.docs if c["conv_id"] == r["conv_id"])
        assert r["report"] and conv["messages"][-2]["content"].startswith("Manutenzione centrale termica")
        assert conv["messages"][-1]["reportId"] == r["report"]["id"] and conv["messages"][-3]["reportAsk"]["done"]
    # after the report a message with that id opens a new draft, never the one made
    r = await chat(draft_id="rdr_0123456789ab", text="sopralluogo da Anna Verdi per la caldaia")
    assert r["draft"]["id"] != "rdr_0123456789ab" and r["draft"]["messages"] == 1
    # nothing to say yet: "genera" asks for the content
    r = await chat(text="genera")
    assert "Prima dimmi cosa scrivere" in r["reply"] and not r["report"]
    print("ALL OK")

asyncio.run(main())
