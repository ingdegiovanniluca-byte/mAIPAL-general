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

class FakeChat:
    REPLY = ""
    SEEN = []
    def __init__(self, *a, **k): FakeChat.SEEN.append(k.get("system_message") or "")
    def with_model(self, *a): return self
    async def send_message(self, m):
        FakeChat.SEEN.append(m.text)
        return FakeChat.REPLY
server.LlmChat = FakeChat


async def main():
    me = server.User(**U)
    marco = server.User(**db.users.docs[1])
    todo = await server.create_todo(server.TodoUpsert(title="Vacanza", notes="mare, metà agosto"), me)
    tid = todo["id"]

    # 1) steps added one after the other, one after a given step, several at once
    t = await server.add_todo_steps(tid, server.TodoStepNew(text="Contattare l'agenzia"), me)
    t = await server.add_todo_steps(tid, server.TodoStepNew(text="  Vedere il preventivo "), me)
    a, b = [x["id"] for x in t["steps"]]
    t = await server.add_todo_steps(tid, server.TodoStepNew(text="Richiedere il preventivo", after=a), me)
    assert [x["text"] for x in t["steps"]] == ["Contattare l'agenzia", "Richiedere il preventivo", "Vedere il preventivo"]
    assert t["completion_percent"] == 0 and t["status"] == "da_fare" and not t["ask_done"]
    t = await server.add_todo_steps(tid, server.TodoStepNew(texts=["Prenotare i voli", "", "Assicurazione viaggio"]), me)
    assert len(t["steps"]) == 5
    await deny(server.add_todo_steps(tid, server.TodoStepNew(text="   "), me), 400)
    await deny(server.add_todo_steps(tid, server.TodoStepNew(text="x"), marco), 404)            # not theirs
    ids = {x["text"]: x["id"] for x in t["steps"]}

    # 2) ticked: progress from the steps; the first one -> "in corso"
    t = await server.update_todo_step(tid, ids["Contattare l'agenzia"], server.TodoStepPatch(done=True), me)
    assert t["completion_percent"] == 20 and t["status"] == "in_corso" and t["steps"][0]["done_at"]
    # main, due date (also in the future), reminder, note, text
    t = await server.update_todo_step(tid, ids["Prenotare i voli"], server.TodoStepPatch(main=True, due_date="2030-05-20", reminder=True, note="bagaglio da stiva"), me)
    st = next(x for x in t["steps"] if x["id"] == ids["Prenotare i voli"])
    assert st["main"] and st["due_date"] == "2030-05-20" and st["reminder"] and st["note"] == "bagaglio da stiva"
    t = await server.update_todo_step(tid, ids["Prenotare i voli"], server.TodoStepPatch(text="Prenotare i voli Milano → Olbia"), me)
    await deny(server.update_todo_step(tid, ids["Prenotare i voli"], server.TodoStepPatch(text=" "), me), 400)
    await deny(server.update_todo_step(tid, ids["Prenotare i voli"], server.TodoStepPatch(due_date="31/02"), me), 400)
    t = await server.update_todo_step(tid, ids["Assicurazione viaggio"], server.TodoStepPatch(due_date=""), me)
    assert not next(x for x in t["steps"] if x["id"] == ids["Assicurazione viaggio"])["reminder"]

    # 3) reordered (an unknown id ignored, none lost); deleted
    order = [ids["Vedere il preventivo"], ids["Richiedere il preventivo"], "st_nope", ids["Contattare l'agenzia"]]
    t = await server.order_todo_steps(tid, server.TodoStepsOrder(ids=order), me)
    assert [x["id"] for x in t["steps"]][:3] == [ids["Vedere il preventivo"], ids["Richiedere il preventivo"], ids["Contattare l'agenzia"]] and len(t["steps"]) == 5
    t = await server.delete_todo_step(tid, ids["Assicurazione viaggio"], me)
    assert len(t["steps"]) == 4 and t["completion_percent"] == 25
    await deny(server.delete_todo_step(tid, ids["Assicurazione viaggio"], me), 404)
    # the to do's own changes keep the steps
    t = await server.update_todo(tid, {"title": "Vacanza 2027", "steps": []}, me)
    assert len(t["steps"]) == 4 and t["title"] == "Vacanza 2027"

    # 4) the last one done: the app asks whether the to do is done (not set by itself)
    for sid in [x["id"] for x in t["steps"] if not x["done"]][:-1]:
        t = await server.update_todo_step(tid, sid, server.TodoStepPatch(done=True), me)
        assert not t["ask_done"]
    last = next(x["id"] for x in t["steps"] if not x["done"])
    t = await server.update_todo_step(tid, last, server.TodoStepPatch(done=True), me)
    assert t["ask_done"] and t["completion_percent"] == 100 and t["status"] == "in_corso"
    t = await server.update_todo_step(tid, last, server.TodoStepPatch(done=False), me)
    assert not t["ask_done"] and t["completion_percent"] == 75

    # 5) ✨ suggested steps: proposals only, not the ones already there, never saved by themselves
    FakeChat.REPLY = '{"steps": ["Scegliere destinazione e date", "Contattare l\'agenzia", "Confrontare i preventivi", "  "]}'
    out = await server.suggest_todo_steps(tid, me)
    assert out["steps"] == ["Scegliere destinazione e date", "Confrontare i preventivi"], out
    assert len((await server._todo_of(me, tid))["steps"]) == 4
    FakeChat.REPLY = "non ho capito"
    assert (await server.suggest_todo_steps(tid, me))["steps"] == []

    # 6) the to do's chat: steps added with the user's words (an invented one dropped), ticked, main
    vedere = next(x["id"] for x in t["steps"] if x["text"] == "Vedere il preventivo")
    FakeChat.REPLY = ('Fatto! <<<META>>>{"steps_add": [{"text": "Prenotare il ristorante", "after": "%s"}, {"text": "Comprare la crema solare", "after": null}],'
                      ' "steps_done": ["%s"], "steps_main": ["%s"], "completion_percent": 3}<<<END>>>') % (vedere, last, vedere)
    r = await server.todo_chat(tid, server.ContextChatRequest(message="aggiungi prenotare il ristorante dopo vedere il preventivo e segna fatto l'ultimo"), me)
    texts = [x["text"] for x in r["todo"]["steps"]]
    assert "Prenotare il ristorante" in texts and "Comprare la crema solare" not in texts, texts
    assert texts.index("Prenotare il ristorante") == texts.index("Vedere il preventivo") + 1
    assert next(x for x in r["todo"]["steps"] if x["id"] == vedere)["main"] and next(x for x in r["todo"]["steps"] if x["id"] == last)["done"]
    assert r["todo"]["completion_percent"] == 80 and r["answer"] == "Fatto!"
    assert "id %s: Vedere il preventivo" % vedere in FakeChat.SEEN[-2]

    # 7) the reminders: on the due day, from 9:00, once (the step's and the to do's own)
    today = jl.today_local().isoformat()
    rist = next(x["id"] for x in r["todo"]["steps"] if x["text"] == "Prenotare il ristorante")
    await server.update_todo_step(tid, rist, server.TodoStepPatch(due_date=today, reminder=True, main=True), me)
    await server.update_todo_step(tid, vedere, server.TodoStepPatch(due_date=today, reminder=True), me)   # done: not reminded
    await server.update_todo(tid, {"due_date": today, "reminder": True}, me)
    NOTICES.clear()
    assert await server._todo_step_reminders(at(jl.today_local(), 8, 0)) == 0
    assert await server._todo_step_reminders(at(jl.today_local(), 9, 30)) == 1
    txt = NOTICES[-1][1]
    assert NOTICES[-1][0] == 77 and "🔔 To do «Vacanza 2027» scade oggi." in txt and "• Prenotare il ristorante ★" in txt and "Vedere il preventivo" not in txt, txt
    assert await server._todo_step_reminders(at(jl.today_local(), 11, 0)) == 0
    # done to dos: nothing
    await server.update_todo(tid, {"status": "fatto", "due_date": today}, me)
    assert await server._todo_step_reminders(at(jl.today_local(), 12, 0)) == 0
    print("ALL OK")

asyncio.run(main())
