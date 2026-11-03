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


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    MARCO = server.User(**db.users.docs[1])
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s1", "collection_id": cl["id"], "item_id": "c_rossi",
                                         "data": {"titolo": "Bagno", "stato": "in lavorazione", "codice": "2026-001",
                                                  "descrizione": "Rifacimento del bagno:\n- demolizione del pavimento\n- impianto idraulico"}})
    db.collection_sub_items.docs.append({"id": "s2", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Cancello", "stato": "in lavorazione"}})
    db.job_quotes.docs.append({"id": "q1", "commessa_id": "s1", "status": "confirmed", "version": 2,
                               "data": {"items": [{"description": "Posa gres 60x60", "amount": 2000.0}, {"description": "Sanitari sospesi", "amount": 1500.0}],
                                        "activities": ["Smontaggio sanitari", "Posa piatto doccia"]}})
    db.job_economics.docs.append({"commessa_id": "s1", "budget": 8000.0, "extras": []})
    cl["costs"] = {"default_rate": 30}
    base = "Clienti / Mario Rossi / 2026-001 – Bagno"
    NOTE = ("oggi spostato lo scarico della doccia di 40 cm perché il cliente vuole il piatto più grande, posato anche il gres; "
            "Marco 4 ore, usati 2 m di tubo multistrato")

    # 1) the interpreter: only works in the note, never one the quote has
    assert jl.covered_by("posato il gres 60x60", ["Posa gres 60x60"]) and not jl.covered_by("spostato lo scarico della doccia", ["Posa gres 60x60"])
    assert not jl.extra_candidate("fatto") and not jl.extra_candidate("cosa abbiamo fatto oggi dai Rossi?")
    MODEL_EXTRAS["extras"] = [{"work": "spostato lo scarico della doccia di 40 cm", "why": "Lo spostamento dello scarico non è nel preventivo."},
                              {"work": "posa gres 60x60", "why": "x"},                                   # in the quote: dropped
                              {"work": "montato un lampadario di cristallo", "why": "x"}]                # not in the note: dropped
    found = await jl.find_extras(NOTE, ["Posa gres 60x60", "Smontaggio sanitari"], {"title": "Bagno"})
    assert [f["work"] for f in found] == ["Spostato lo scarico della doccia di 40 cm"], found
    assert await jl.find_extras(NOTE, [], {"title": "Bagno"}) == []                                     # nothing to compare: no call

    # 2) a diary note: checked in the background against quote and description; the administrator asked on Telegram
    jl.interpret = said(hours=[{"who": "Marco", "hours": 4}], materials=[{"name": "tubo multistrato", "qty": 2, "unit": "m"}])
    BOT_SENT.clear(); CALLS.clear()
    r = await server._save_job_log(me, NOTE, commessa_id="s1")
    await settle()
    assert CALLS and "Posa gres 60x60" in CALLS[-1] and "demolizione del pavimento" in CALLS[-1] and "Smontaggio sanitari" in CALLS[-1]
    xs = db.job_extra_works.docs
    assert len(xs) == 1 and xs[0]["status"] == "da_valutare" and xs[0]["hours"] == 4 and xs[0]["quote_version"] == 2 and xs[0]["log_ids"] == [r["log"]["id"]]
    xid = xs[0]["id"]
    txt, kb = to(77)[-1]
    assert "Possibile lavoro extra" in txt and "«Spostato lo scarico della doccia di 40 cm»" in txt and "Nella stessa nota: 4 h · 2 m tubo multistrato" in txt
    assert "preventivo v2" in txt and buttons(kb) == [f"xw:extra:{xid}", f"xw:compreso:{xid}", f"xw:scartato:{xid}"]
    assert next(x for x in db.job_logs.docs if x["id"] == r["log"]["id"])["extras_checked"]
    # the same work said again: not proposed twice
    await server._save_job_log(me, "finito di spostare lo scarico della doccia di 40 cm, 2 ore", commessa_id="s1")
    await settle()
    assert len(db.job_extra_works.docs) == 1
    # a commessa without quote nor description: nothing to compare, the model not even asked
    CALLS.clear()
    await server._save_job_log(me, "montato il motore del cancello e regolato i finecorsa", commessa_id="s2")
    await settle()
    assert not CALLS

    # 3) the administrator decides (Telegram button); a user cannot
    await deny(server.patch_extra_work(xid, server.ExtraWorkPatch(action="extra"), MARCO), (403, 404))
    BOT_SENT.clear()
    await tg._on_callback(Upd(77, data=f"xw:extra:{xid}"), Ctx())
    assert next(x for x in db.job_extra_works.docs if x["id"] == xid)["status"] == "extra" and "da far approvare" in to(77)[-1][0]
    out = await server.patch_extra_work(xid, server.ExtraWorkPatch(action="update", amount=350), me)
    row = next(x for x in out["extra_works"] if x["id"] == xid)
    assert row["amount"] == 350 and row["note_cost"] == 120.0 and row["status_label"] == "da far approvare"   # 4 h x 30 (the tube has no price)
    d = await server.get_job_commessa("s1", current=me)
    assert [x["id"] for x in d["extra_works"]] == [xid]

    # 4) in the Friday report; in the closure check
    today = jl.today_local()
    fri = today + timedelta(days=max(0, 4 - today.weekday()))          # this week's report (Monday to that day)
    rep = await server._job_weekly_summary(me, at(fri, 18, 0).astimezone(ROME))
    assert "💡 Lavori extra: 1 da far approvare (€ 350)" in rep, rep
    chk = await server._close_check("s1")
    assert chk["extras"] == ["Spostato lo scarico della doccia di 40 cm (da far approvare)"]

    # 5) the variant for the client: a document with the signatures, only what is written, in Preventivi
    await server.add_extra_work("s1", server.ExtraWorkNew(work="Presa in più in bagno"), me)
    REPORTS.clear()
    v = await server.make_variant("s1", server.VariantPayload(), me)
    wr = next(w for w in db.work_reports.docs if w["id"] == v["report"]["id"])
    assert wr["report_type"] == "variante" and REPORTS[-1][1] == f"{base} / Preventivi" and REPORTS[-1][0].startswith("preventivo_") \
        and REPORTS[-1][0].endswith("_variante_v1.docx"), REPORTS
    f = wr["sections"][1]["fields"]
    assert "- Spostato lo scarico della doccia di 40 cm" in f["Descrizione dei lavori"] and "Presa in più in bagno: da definire" in f["Importi"]
    assert f["Totale lavori extra"] == "€ 350 (più le voci da definire)", f

    # 6) approved by the client: its amount on the commessa's value, in the diary and the history; then it counts as in the quote
    await deny(server.patch_extra_work(next(x["id"] for x in db.job_extra_works.docs if x["work"] == "Presa in più in bagno"),
                                       server.ExtraWorkPatch(action="approvato"), me), 400)          # no amount: asked
    out = await server.patch_extra_work(xid, server.ExtraWorkPatch(action="approvato"), me)
    assert "€ 350 aggiunti al valore della commessa (ora € 8.350)" in out["message"], out["message"]
    assert next(e for e in db.job_economics.docs if e["commessa_id"] == "s1")["budget"] == 8350.0
    assert any(lg.get("kind") == "extra" and "approvato dal cliente" in lg["text"] for lg in db.job_logs.docs)
    assert any(h.get("field") == "Valore" for h in db.commessa_history.docs)
    scope, _v = await server._extras_scope("s1", next(x for x in db.collection_sub_items.docs if x["id"] == "s1"), cl)
    assert "Spostato lo scarico della doccia di 40 cm" in scope
    await server.patch_extra_work(xid, server.ExtraWorkPatch(action="approvato"), me)                # twice: added once
    assert next(e for e in db.job_economics.docs if e["commessa_id"] == "s1")["budget"] == 8350.0

    # 7) the notes not checked yet (written before): on request, without Telegram messages
    db.job_logs.docs.append({"id": "old1", "commessa_id": "s1", "date": "2026-10-20", "text": "rifatto il massetto del corridoio, 6 ore",
                             "raw_text": "rifatto il massetto del corridoio, 6 ore", "hours": [{"who": "Marco", "hours": 6}], "materials": [], "problems": []})
    MODEL_EXTRAS["extras"] = [{"work": "rifatto il massetto del corridoio", "why": "Il corridoio non è nel preventivo."}]
    BOT_SENT.clear()
    out = await server.scan_extra_works("s1", me)
    assert out["found"] == 1 and any(x["work"] == "Rifatto il massetto del corridoio" for x in out["extra_works"]) and not to(77)
    assert (await server.scan_extra_works("s1", me))["found"] == 0                                      # checked once
    await deny(server.scan_extra_works("s2", me), 400)                                                   # nothing to compare with
    print("ALL OK")

asyncio.run(main())
