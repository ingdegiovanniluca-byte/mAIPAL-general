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
FAIL = {"on": False}
CALLS = []
class FakeCompletions:
    async def create(self, **k):
        CALLS.append(k["messages"][1]["content"])
        if FAIL["on"]:
            raise RuntimeError("model down")
        msg = types.SimpleNamespace(content=_json.dumps(MODEL_EXTRAS))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None, model="x", id="r1")
class FakeOpenAI:
    def __init__(self, *a, **k): self.chat = types.SimpleNamespace(completions=FakeCompletions())
jl.openai.AsyncOpenAI = FakeOpenAI



def lg(cid, day, hours, who="Luca"):
    db.job_logs.docs.append({"id": f"l_{cid}_{day}", "commessa_id": cid, "date": day, "text": "lavori", "hours": [{"who": who, "hours": hours}],
                             "materials": [], "problems": []})


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    MARCO = server.User(**db.users.docs[1])
    cl["costs"] = {"default_rate": 30}
    for cid, name in (("c_b", "Bianchi"), ("c_v", "Verdi"), ("c_n", "Neri"), ("c_g", "Gialli"), ("c_r", "Rossi")):
        db.collection_items.docs.append({"id": cid, "collection_id": cl["id"], "data": {"nome": name}})
    def job(i, item, title, stato, desc="", **data):
        db.collection_sub_items.docs.append({"id": i, "collection_id": cl["id"], "item_id": item,
                                             "data": {"titolo": title, "stato": stato, "descrizione": desc, **data}})
    # the history: two bathrooms done (with what they really cost), an electrical system, a bathroom lost for the price
    job("h1", "c_b", "Rifacimento bagno", "completata", "demolizione, piastrelle, sanitari sospesi, doccia")
    job("h2", "c_v", "Rifacimento bagno padronale", "completata", "piastrelle e sanitari nuovi, piatto doccia")
    job("h3", "c_n", "Impianto elettrico appartamento", "completata", "quadro, prese, linee")
    job("h4", "c_g", "Bagno nuovo", "persa", "piastrelle e sanitari", )
    next(x for x in db.collection_sub_items.docs if x["id"] == "h4")["lost_reason"] = {"category": "prezzo", "text": ""}
    db.job_quotes.docs.append({"id": "qh4", "commessa_id": "h4", "status": "confirmed", "version": 1, "data": {"total": 9000.0, "taxable": None}})
    for d, h in (("2026-09-01", 50), ("2026-09-12", 50)):
        lg("h1", d, h)
    for d, h in (("2026-10-01", 60), ("2026-10-15", 60)):
        lg("h2", d, h)
    lg("h3", "2026-08-01", 30)
    db.job_economics.docs += [{"commessa_id": "h1", "budget": 5000.0, "extras": [{"label": "smaltimento", "amount": 1000.0}]},
                              {"commessa_id": "h2", "budget": 6000.0, "extras": [{"label": "ponteggio", "amount": 1400.0}]},
                              {"commessa_id": "h3", "budget": 3000.0, "extras": []}]
    today = jl.today_local()
    job("s1", "c_r", "Rifacimento bagno", "sopralluogo", "bagno al primo piano: piastrelle, sanitari sospesi, doccia",
        data_inizio=(today - timedelta(days=10)).isoformat(), data_fine=(today + timedelta(days=5)).isoformat())
    sub = lambda: next(x for x in db.collection_sub_items.docs if x["id"] == "s1")

    # 1) the estimate: the similar ones chosen by the model among the organization's own (an id it made up: ignored)
    MODEL_EXTRAS.clear(); MODEL_EXTRAS.update({"ids": ["h1", "h2", "h4", "nope"]})
    CALLS.clear()
    est = await server.get_history_estimate("s1", current=me)
    assert est["status"] == "ok" and est["method"] == "ai" and est["n"] == 2 and [x["id"] for x in est["similar"]] == ["h1", "h2"], est
    assert "Rifacimento bagno padronale" in CALLS[-1] and "Impianto elettrico" in CALLS[-1] and "h1:" in CALLS[-1]
    assert est["cost"] == {"median": 4500.0, "min": 4000.0, "max": 5000.0} and est["hours"]["median"] == 110.0     # 100 h x 30 + 1000; 120 h x 30 + 1400
    assert est["margin_pct_median"] == 18.35 and est["suggested_value"] == 5510.0 and est["days"]["median"] == 13.5
    assert est["lost_for_price"] == [{"title": "Bagno nuovo", "value": 9000.0}]
    # kept a week: no new call; refresh: again
    CALLS.clear()
    await server.get_history_estimate("s1", current=me)
    assert not CALLS
    await server.get_history_estimate("s1", refresh=True, current=me)
    assert CALLS
    # the model down: by words
    FAIL["on"] = True
    est = await server.get_history_estimate("s1", refresh=True, current=me)
    FAIL["on"] = False
    assert est["method"] == "parole" and {x["id"] for x in est["similar"]} >= {"h1", "h2"} and "h3" not in {x["id"] for x in est["similar"]}, est
    MODEL_EXTRAS.clear(); MODEL_EXTRAS.update({"ids": ["h1", "h2", "h4"]})
    await server.get_history_estimate("s1", refresh=True, current=me)
    # only who sees the costs
    await deny(server.get_history_estimate("s1", current=MARCO), (403, 404))
    # nothing to compare with
    assert jl.forecast(None, 100, 0.5) is None and jl.similar_by_words("", []) == []

    # 2) the quote being uploaded: checked against the history (5.000: margin 10%, under the usual 18%)
    QUOTE.clear(); QUOTE.update(total=5000.0, taxable=None, vat=None, items=[{"description": "Piastrelle", "amount": 2000.0}], start="", end="", validity="",
                                payments=[], activities=["Posa piastrelle"], materials=[], description="")
    READ_DOC.update(kind="preventivo")
    up = await server._ingest_commessa_document(me, "s1", "prev.txt", b"PREVENTIVO Totale 5.000,00", "text/plain", hint="preventivo")
    assert up["history_check"].startswith("⚠️ Nei tuoi 2 lavori simili il costo è stato € 4.500: con € 5.000 il margine atteso è 10% (di solito 18%): sotto il tuo solito"), up["history_check"]
    assert up["history_check"] in up["message"]
    est = await server.get_history_estimate("s1", current=me)
    assert est["value_check"] == "" or est["value"] is None

    # 3) the forecast while the works go on: from the planned activities done (2 of 4), the expected end and the delay
    sub()["data"]["stato"] = "in lavorazione"
    db.job_economics.docs.append({"commessa_id": "s1", "budget": 8000.0, "extras": []})
    for i, st in enumerate(("svolta", "svolta", "pianificata", "pianificata")):
        db.job_activities.docs.append({"id": f"a{i}", "commessa_id": "s1", "description": f"fase {i}", "date": today.isoformat(), "status": st, "assignees": []})
    lg("s1", (today - timedelta(days=9)).isoformat(), 50)
    lg("s1", (today - timedelta(days=2)).isoformat(), 50)
    e = await server.get_commessa_economics("s1", current=me)
    f = e["forecast"]
    assert f["basis"] == "andamento" and f["progress_pct"] == 50 and f["progress_source"] == "attività pianificate svolte" and f["cost_now"] == 3000.0, f
    assert f["cost"] == 6000.0 and f["margin"] == 2000.0 and f["margin_pct"] == 25.0 and f["confidence"] == "media" and f["hist_margin_pct"] == 18.35
    assert f["expected_end"] == (today - timedelta(days=10) + timedelta(days=20)).isoformat() and f["delay_days"] == 5
    # going worse: alerted once when the forecast is a loss
    NOTICES.clear()
    lg("s1", (today - timedelta(days=1)).isoformat(), 60)
    await server._check_budget_alert(cl, "s1")
    assert any("📉 Al ritmo attuale chiudi in perdita su «Rifacimento bagno»" in t and "margine -€ 1.600" in t.replace("−", "-") for _c, t in NOTICES), NOTICES
    n = len(NOTICES)
    await server._check_budget_alert(cl, "s1")
    assert len(NOTICES) == n                                                             # once
    # too early to say (a quarter not reached): from the history, never less than spent; no alert
    for a in db.job_activities.docs:
        a["status"] = "pianificata"
    f = (await server.get_commessa_economics("s1", current=me))["forecast"]
    assert f["basis"] == "storico" and f["cost"] == 4800.0 and f["confidence"] == "bassa", f        # spent 4.800 > the history's 4.500
    # in the Friday report
    rep = await server._job_weekly_summary(me, datetime.combine(today + timedelta(days=max(0, 4 - today.weekday())), datetime.min.time(), tzinfo=ROME).replace(hour=18))
    assert "📈 A fine lavori: costi € 4.800" in rep, rep
    print("ALL OK")

asyncio.run(main())
