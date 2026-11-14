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
    smap = cl.get("system_sub_map") or {}
    today = jl.today_local()
    now = at(today, 10, 10)
    def client(cid, name):
        db.collection_items.docs.append({"id": cid, "collection_id": cl["id"], "data": {"nome": name}})
    def job(sid, cid, title, stato="in lavorazione", geo=None):
        db.collection_sub_items.docs.append({"id": sid, "collection_id": cl["id"], "item_id": cid, "data": {"titolo": title, "stato": stato},
                                             **({"geo": {"lat": geo[0], "lon": geo[1], "source": "manual"}} if geo else {})})
    client("c_rossi", "Mario Rossi"); job("s_bagno", "c_rossi", "Bagno", geo=(45.0700, 7.6800))
    client("c_luca", "Luca D"); job("s_all", "c_luca", "Impianto allarme", geo=(45.2000, 7.9000))
    client("c_mart", "Martina S"); job("s_el", "c_mart", "Impianto elettrico")
    client("c_bia", "Bianchi"); job("s_can", "c_bia", "Cancello", geo=(45.0790, 7.6800))      # 1 km from the Rossi
    client("c_ver", "Verdi"); job("s_tet", "c_ver", "Tetto", stato="completata", geo=(45.0710, 7.6800))
    db.collaborators.docs.append({"id": "col_g", "owner_user_id": "u1", "first_name": "Gino", "last_name": "Neri", "company": "Edil G", "status": "active"})
    db.collaborators.docs.append({"id": "col_p", "owner_user_id": "u1", "first_name": "Pietro", "last_name": "Blu", "status": "active"})
    U1 = {"type": "user", "id": "u1", "name": "Luca"}; U2 = {"type": "user", "id": "u2", "name": "Marco"}
    G = {"type": "collaborator", "id": "col_g", "name": "Gino"}; Pi = {"type": "collaborator", "id": "col_p", "name": "Pietro"}
    def act(aid, sid, desc, start, people, status="pianificata"):
        db.job_activities.docs.append({"id": aid, "commessa_id": sid, "date": today.isoformat(), "description": desc, "start_time": start, "end_time": None,
                                       "assignees": [{**p, "confirm": {"status": "in_attesa"}} for p in people], "status": status})
    act("a1", "s_bagno", "Posa piatto doccia", "08:00", [G, U2])
    act("a2", "s_all", "Cablaggio centrale", "09:00", [Pi, U1])
    act("a3", "s_el", "Quadro elettrico", None, [U2])
    act("a4", "s_bagno", "Annullata", "15:00", [G], status="annullata")
    ses = lambda sid, wid, paused=None: db.work_sessions.docs.append({"id": f"ws_{sid}_{wid}", "collaborator_id": wid, "commessa_id": sid,
                                                                     "start_at": at(today, 7, 50).isoformat(), "end_at": None, "paused_at": paused})
    ses("s_bagno", "col_g"); ses("s_bagno", "usr_u2")              # as planned: green
    ses("s_el", "usr_u1"); ses("s_el", "col_p", at(today, 10, 0).isoformat())   # 2 there, 1 planned (another): yellow; one in pause
    ses("s_can", "col_x")                                          # not planned today: yellow
    db.job_logs.docs.append({"id": "L1", "commessa_id": "s_can", "date": today.isoformat(), "problems": ["il motore non parte"], "hours": []})
    db.job_logs.docs.append({"id": "L2", "commessa_id": "s_all", "date": today.isoformat(), "problems": ["manca la sirena"], "hours": []})
    db.job_logs.docs.append({"id": "L3", "commessa_id": "s_el", "date": today.isoformat(), "problems": ["quadro bagnato"], "hours": [],
                             "problem_status": {"0": {"status": "risolta", "at": now.isoformat()}}})
    db.job_todos.docs.append({"id": "m1", "commessa_id": "s_bagno", "kind": "materiale", "done": False, "due_date": today.isoformat(),
                              "text": "Da prendere: 20 m corrugato, 10 scatole 503", "who": "Gino"})
    db.job_todos.docs.append({"id": "m0", "commessa_id": "s_bagno", "kind": "materiale", "done": False, "due_date": (today - timedelta(days=1)).isoformat(), "text": "Da prendere: ieri"})
    db.job_todos.docs.append({"id": "m2", "commessa_id": "s_all", "kind": "materiale", "done": False, "due_date": (today + timedelta(days=1)).isoformat(), "text": "Da prendere: sirena"})
    db.tasks.docs.append({"id": "t1", "user_id": "u1", "title": "Chiamare il fornitore", "due_date": today.isoformat(), "due_time": "10:30", "priority": "media", "duration_minutes": 45})
    db.tasks.docs.append({"id": "t2", "user_id": "u1", "title": "Fattura Rossi", "due_date": today.isoformat(), "due_time": None, "completed": True})
    db.tasks.docs.append({"id": "t3", "user_id": "u1", "title": "Domani", "due_date": (today + timedelta(days=1)).isoformat(), "due_time": "09:00"})
    db.news_items.docs += [{"id": "n1", "user_id": "u1", "date": today.isoformat(), "title": "Bonus casa 2027", "created_at": "2"},
                           {"id": "n2", "user_id": "u1", "date": today.isoformat(), "title": "Rame in calo", "feedback": "up", "created_at": "1"},
                           {"id": "n3", "user_id": "u1", "date": today.isoformat(), "title": "Non mi interessa", "feedback": "down", "created_at": "3"}]

    d = await server._today_dashboard(me, now)
    # the clock: the tasks and activities of today with their time, the done ones marked
    assert [(x["kind"], x["time"], x["label"]) for x in d["clock"]] == [("attivita", "08:00", "Mario Rossi"), ("attivita", "09:00", "Luca D"),
                                                                    ("task", "10:30", "Chiamare il fornitore"), ("task", None, "Fattura Rossi"),
                                                                    ("attivita", None, "Martina S")], d["clock"]
    assert next(x for x in d["clock"] if x["id"] == "t2")["done"]
    # how long each lasts, so the clock draws it from its start: the task's duration, None when not known
    assert next(x for x in d["clock"] if x["id"] == "t1")["minutes"] == 45
    assert next(x for x in d["clock"] if x["id"] == "t2")["minutes"] is None
    assert server._clock_minutes(None, "09:00", "11:30") == 150 and server._clock_minutes(None, "09:00", None) is None
    # on site: 2 employees, 3 collaborators, on 3 sites, 1 in pause
    on = d["on_site"]
    assert (on["total"], on["employees"], on["collaborators"], on["sites"], on["paused"]) == (5, 2, 3, 3, 1), on
    assert {p["name"] for p in on["people"]} >= {"Gino Neri", "Marco Bianchi", "Luca Rossi", "Pietro Blu"}
    # the commesse: red (nobody, 2 planned, a problem), yellow, green
    rows = {c["title"]: c for c in d["commesse"]}
    assert (rows["Bagno"]["status"], rows["Bagno"]["present"], rows["Bagno"]["expected"], rows["Bagno"]["problems"]) == ("green", 2, 2, 0)
    assert (rows["Impianto allarme"]["status"], rows["Impianto allarme"]["present"], rows["Impianto allarme"]["problems"]) == ("red", 0, 1)
    assert (rows["Impianto elettrico"]["status"], rows["Impianto elettrico"]["present"], rows["Impianto elettrico"]["expected"]) == ("yellow", 2, 1)
    assert (rows["Cancello"]["status"], rows["Cancello"]["expected"], rows["Cancello"]["problems"]) == ("yellow", 0, 1)
    assert [c["status"] for c in d["commesse"]][0] == "red" and "Tetto" not in rows
    # the notes: activities (not the cancelled one), materials (today's), news (liked first, not the disliked), tips
    n = d["notes"]
    assert [a["text"] for a in n["activities"]] == ["Posa piatto doccia", "Cablaggio centrale", "Quadro elettrico"]
    assert n["activities"][0]["who"] == ["Gino", "Marco"] and n["activities"][0]["commessa"] == "Mario Rossi · Bagno"
    assert [m["text"] for m in n["materials"]] == ["20 m corrugato, 10 scatole 503"]
    assert [x["title"] for x in n["news"]] == ["Rame in calo", "Bonus casa 2027"]
    tips = " | ".join(t["text"] for t in n["tips"])
    assert "Luca D · Impianto allarme: nessuno in cantiere e 2 persone previste." in tips, tips
    assert "Martina S · Impianto elettrico: risolto «quadro bagnato». Aggiorna il cliente." in tips, tips
    assert "pioggia probabile (70%) oggi" in tips, tips
    assert not any("Vicino a" in t["text"] for t in n["tips"])        # the Cancello (with its problem) is one of today's
    # a site with a problem near today's (not one of today's): told; a closed one never
    db.collection_sub_items.docs.append({"id": "s_far", "collection_id": cl["id"], "item_id": "c_bia", "data": {"titolo": "Cancello 2", "stato": "in lavorazione"},
                                         "geo": {"lat": 45.0750, "lon": 7.6800, "source": "manual"}})
    db.job_logs.docs.append({"id": "L4", "commessa_id": "s_far", "date": today.isoformat(), "problems": ["motore bloccato"], "hours": []})
    db.job_logs.docs.append({"id": "L5", "commessa_id": "s_tet", "date": today.isoformat(), "problems": ["tegola rotta"], "hours": []})
    d = await server._today_dashboard(me, now)
    tips = " | ".join(t["text"] for t in d["notes"]["tips"])
    assert "Vicino a Bianchi · Cancello (445 m) c'è Bianchi · Cancello 2 con un problema aperto (motore bloccato): passaci." in tips, tips
    assert "Tetto" not in tips
    # the endpoint; another vertical: only its tasks
    assert (await server.jobs_today(me))["on_site"]["total"] == 5
    print("ALL OK")

asyncio.run(main())
