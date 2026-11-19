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

def said(kind="nota", text=None, hours=None, problems=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web"):
        f.last = {"speaker": speaker, "team": team, "known": known}
        return {"kind": kind, "doubt": "", "date": jl.today_local().isoformat(), "text": text or t,
                "hours": jl.clean_hours(hours or [], speaker), "materials": [], "problems": problems or [], "client": "", "commessa": ""}
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


import weather as wx
from zoneinfo import ZoneInfo
ROME = ZoneInfo("Europe/Rome")


async def deny(coro, code=403):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code in (code if isinstance(code, tuple) else (code,)), (e.status_code, e.detail)
        return e.detail
    raise AssertionError("not denied")


async def rainy(lat, lon, day):
    return {"rain_pct": 80, "wind_kmh": 12, "tmin": 9, "tmax": 15, "code": 61}
wx.provider = rainy
PINS = []
async def fake_pin_send(chat_id, text, kb):
    PINS.append(("send", chat_id, text, kb)); return 1000 + len(PINS)
async def fake_pin_edit(chat_id, mid, text, kb):
    PINS.append(("edit", chat_id, text, kb))
async def fake_pin_unpin(chat_id, mid):
    PINS.append(("unpin", chat_id, None, None))
server._day_pin_send, server._day_pin_edit, server._day_pin_unpin = fake_pin_send, fake_pin_edit, fake_pin_unpin


def at(day, hh, mm=0):
    return datetime.combine(day, datetime.min.time(), tzinfo=ROME).replace(hour=hh, minute=mm).astimezone(timezone.utc)


def to(chat):
    return [(t, kb) for c, t, kb in BOT_SENT if c == chat]


async def main():
    """Pianificazione: Tappe (the contract's main works, in order, date optional, closed with confirmation) and Attività (minor
    things, from anyone's messages, the day asked when missing, assigned within the rules, reminded and followed up)."""
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    MARCO = server.User(**db.users.docs[1])
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "geo": {"lat": 45.07, "lon": 7.68, "source": "manual"},
                                         "data": {"titolo": "Bagno", "stato": "in lavorazione", "indirizzo_cantiere": "Via Garibaldi 5, Torino"}})
    crew = {}
    for first, last, company, chat in (("Gino", "Neri", "Neri Impianti", 900), ("Pino", "Neri", "Neri Impianti", 901), ("Ugo", "Verdi", "Verdi Srl", 902)):
        c = await server.create_collaborator(server.CollaboratorPayload(first_name=first, last_name=last, company=company, commesse=["s_bagno"]), me)
        x = next(y for y in db.collaborators.docs if y["id"] == c["collaborator"]["id"])
        x.update(status="active", telegram_chat_id=chat)
        crew[first] = x
    today = jl.today_local()
    iso = lambda n: (today + timedelta(days=n)).isoformat()

    # 1) tappe: without a date, in the order they are made; moved up and down; the chat knows them
    t1 = await server.create_milestone("s_bagno", server.MilestonePayload(title="Smontaggio caldaia"), me)
    t2 = await server.create_milestone("s_bagno", server.MilestonePayload(title="Impianto elettrico"), me)
    t3 = await server.create_milestone("s_bagno", server.MilestonePayload(title="Collaudo", due_date=iso(20)), me)
    assert t1.get("due_date") is None and t1["status"] == "planned" and [t1["order"], t2["order"], t3["order"]] == [0, 1, 2]
    r = await server.move_milestone(t3["id"], server.MilestoneMovePayload(direction="up"), me)
    assert [m["title"] for m in r["milestones"]] == ["Smontaggio caldaia", "Collaudo", "Impianto elettrico"]
    r = await server.move_milestone(t1["id"], server.MilestoneMovePayload(direction="up"), me)   # already first: nothing
    assert [m["title"] for m in r["milestones"]][0] == "Smontaggio caldaia" and r["summary"]["next"]["title"] == "Smontaggio caldaia"
    r = await server.move_milestone(t3["id"], server.MilestoneMovePayload(direction="down"), me)
    assert [m["title"] for m in r["milestones"]] == ["Smontaggio caldaia", "Impianto elettrico", "Collaudo"]
    x = await server.update_milestone(t3["id"], server.MilestonePatch(due_date=""), me)          # the date taken away
    assert x.get("due_date") is None and x["status"] == "planned"
    await server.ask_job_commessa("s_bagno", server.CommessaAskPayload(question="a che punto siamo?", history=[]), me)
    assert "1. «Smontaggio caldaia»" in ANSWERS[-1]["view"]["milestones_line"] and "senza data" in ANSWERS[-1]["view"]["milestones_line"], ANSWERS[-1]["view"]["milestones_line"]
    assert not await server._milestone_reminders(at(today, 9))                                    # no date, no reminder

    # 2) the administrator: "pianifica … con Marco" without a day - an activity all the same, in its tappa, the day asked
    said_act = {}
    jl.interpret = said()
    async def read_act(text, people, user_id=None, channel="web"):
        return {"description": "", "date": "", "start": "", "end": "", "assignees": [], "items": [], "info": "", **said_act}
    jl.read_activity = read_act
    said_act.update(description="Smontare la caldaia vecchia", assignees=["Marco Bianchi"])
    r = await server._save_job_log(me, "pianifica smontaggio della caldaia vecchia con Marco", commessa_id="s_bagno")
    assert r["status"] == "commessa_update" and r.get("ask_date") and "📅 C'è una data prevista?" in r["message"], r
    assert "per Marco (da Luca)" in r["message"] and "🚩 Nella tappa «Smontaggio caldaia»" in r["message"], r["message"]
    tm = next(x for x in db.job_todos.docs if x["id"] == r["ask_date"]["todo_id"])
    assert tm["milestone_id"] == t1["id"] and tm["assignee_user_id"] == "u2" and tm["created_by_name"] == "Luca" and tm["due_date"] is None
    ev = [x for x in db.job_logs.docs if x.get("kind") == "todo"][-1]["text"]
    assert ev.startswith("📌 Attività: Smontare la caldaia vecchia") and "per Marco (da Luca)" in ev, ev
    #    the answer from the app: "Domani"; Marco only sees what is his or of a commessa he sees
    out = await server.set_todo_when(tm["id"], server.PlanWhenPayload(choice="domani"), me)
    assert out["todo"]["due_date"] == iso(1) and "Te lo ricordo il giorno prima" in out["message"]

    # 3) a collaborator: for himself or the colleagues of his company only
    said_act.update(description="Passare i cavi in cucina", date=iso(2), assignees=["Ugo Verdi"])
    REPLIES.clear()
    assert await send(900, "pianifica dopodomani Ugo passa i cavi in cucina")
    assert "Posso segnare attività solo per te o per i colleghi della tua azienda (Pino)" in REPLIES[-1][0], REPLIES[-1]
    assert not any(a["description"] == "Passare i cavi in cucina" for a in db.job_activities.docs)
    said_act.update(assignees=["Pino Neri"])
    assert await send(900, "pianifica dopodomani Pino passa i cavi in cucina")
    a = next(x for x in db.job_activities.docs if x["description"] == "Passare i cavi in cucina")
    assert [p["name"] for p in a["assignees"]] == ["Pino Neri"] and a["created_by_collab"] == crew["Gino"]["id"] and a["created_by_name"] == "Gino"
    assert a["date"] == iso(2) and a.get("milestone_id") is None
    ev = [x for x in db.job_logs.docs if "Passare i cavi in cucina" in (x.get("text") or "")][-1]["text"]
    assert "per Pino (da Gino)" in ev, ev
    #    nobody named and no day: for himself, the day asked with his own buttons
    said_act.update(description="Ordinare le placche", date="", assignees=[])
    REPLIES.clear()
    assert await send(900, "pianifica ordinare le placche")
    text, kb = REPLIES[-1]
    tg_ = next(x for x in db.job_todos.docs if x["text"] == "Ordinare le placche")
    assert tg_["collaborator_id"] == crew["Gino"]["id"] and "📅 C'è una data prevista?" in text, text
    assert f"cpl:d:dopodomani:{tg_['id']}" in buttons(kb)
    assert await tap(901, f"cpl:d:domani:{tg_['id']}")                                         # Pino: not his
    assert "non è tua" in REPLIES[-1][0] and next(x for x in db.job_todos.docs if x["id"] == tg_["id"])["due_date"] is None
    assert await tap(900, f"cpl:d:dopodomani:{tg_['id']}")
    assert next(x for x in db.job_todos.docs if x["id"] == tg_["id"])["due_date"] == iso(2)

    # 4) a user's activity: reminded the day before (Telegram + app); late, asked whether it was done
    BOT_SENT.clear()
    assert await server._todo_reminders(at(today, 9)) >= 1
    assert any("⏰ Domani va fatta: *Smontare la caldaia vecchia*" in t for t, _ in to(78)), to(78)
    tm = next(x for x in db.job_todos.docs if x["id"] == tm["id"])
    tm["due_date"] = iso(-1)
    BOT_SENT.clear()
    await server._todo_reminders(at(today, 9))
    t_, kb = next((t, k) for t, k in to(78) if "Smontare la caldaia vecchia" in t)
    assert t_.startswith("🔴 Era da fare entro il") and "È stata fatta?" in t_ and f"pl:t:fatta:{tm['id']}" in buttons(kb), t_
    BOT_SENT.clear()
    await server._todo_reminders(at(today, 10))
    assert not any("Smontare la caldaia vecchia" in t for t, _ in to(78))                     # once

    # 5) the tappa's last activity done: whether it is concluded is asked (never closed by itself)
    msg = await server._plan_answer("t", "fatta", tm["id"], {"kind": "user", "id": "u2", "name": "Marco"})
    assert msg.startswith("✅") and next(x for x in db.job_todos.docs if x["id"] == tm["id"])["done"]
    m1 = next(x for x in db.job_milestones.docs if x["id"] == t1["id"])
    assert m1.get("close_proposed") and not m1.get("done")
    t_, kb = next((t, k) for t, k in to(77) if "Smontaggio caldaia" in t)
    assert "La tappa è conclusa?" in t_ and buttons(kb) == [f"tpc:y:{t1['id']}", f"tpc:n:{t1['id']}"]
    det = await server.get_job_commessa("s_bagno", current=me)
    assert next(m for m in det["milestones"] if m["id"] == t1["id"]).get("close_proposed")
    x = await server.update_milestone(t1["id"], server.MilestonePatch(close_proposal=False), me)   # "Non ancora"
    assert not x.get("close_proposed") and x["status"] != "done"
    x = await server.update_milestone(t1["id"], server.MilestonePatch(done=True), me)                # "Sì, conclusa"
    assert x["status"] == "done" and not x.get("close_proposed")
    assert [e for e in db.job_logs.docs if e.get("kind") == "milestone"][-1]["text"].startswith("Tappa «Smontaggio caldaia» conclusa il")
    r = await server.move_milestone(t2["id"], server.MilestoneMovePayload(direction="up"), me)
    assert r["summary"]["next"]["title"] == "Impianto elettrico"

    # 6) an activity on site whose day is gone, not marked: its people asked once (from 9:00), the answer kept
    a = next(x for x in db.job_activities.docs if x["id"] == a["id"])
    a["date"] = iso(-1)
    BOT_SENT.clear()
    assert await server._plan_followups(at(today, 8, 59)) == 0
    assert await server._plan_followups(at(today, 9)) == 1
    t_, kb = to(901)[-1]
    assert "era prevista *Passare i cavi in cucina*" in t_ and "È stata fatta?" in t_ and f"cpl:a:fatta:{a['id']}" in buttons(kb), t_
    assert await server._plan_followups(at(today, 10)) == 0
    assert await tap(902, f"cpl:a:no:{a['id']}") and "non è tua" in REPLIES[-1][0]                 # Ugo: not his
    assert await tap(901, f"cpl:a:domani:{a['id']}")
    a = next(x for x in db.job_activities.docs if x["id"] == a["id"])
    assert a["date"] > today.isoformat() and not a.get("followup")
    assert await tap(901, f"cpl:a:no:{a['id']}")
    assert next(x for x in db.job_activities.docs if x["id"] == a["id"])["status"] == "annullata"
    assert "🗑 Attività tolta: Passare i cavi in cucina" in [e for e in db.job_logs.docs if e.get("kind") == "todo"][-1]["text"]

    # 7) from the app: the tappa chosen; the creator is kept
    x = await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Comprare le canaline", who="Gino Neri", milestone_id=t2["id"]), me)
    assert x["milestone_id"] == t2["id"] and x["created_by_name"] == "Luca" and x["collaborator_id"] == crew["Gino"]["id"]
    assert "per Gino (da Luca)" in [e for e in db.job_logs.docs if e.get("kind") == "todo"][-1]["text"]
    await deny(server.create_job_todo("s_bagno", server.JobTodoPayload(text="x", milestone_id="ms_altro"), me), 400)
    print("ALL OK")

asyncio.run(main())
