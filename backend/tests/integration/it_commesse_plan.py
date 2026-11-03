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
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    MARCO = server.User(**db.users.docs[1])
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "geo": {"lat": 45.07, "lon": 7.68, "source": "manual"},
                                         "data": {"titolo": "Bagno", "stato": "in lavorazione"}})
    c = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Neri", commesse=["s_bagno"]), me)
    gino = next(x for x in db.collaborators.docs if x["id"] == c["collaborator"]["id"])
    gino.update(status="active", telegram_chat_id=900)
    today = jl.today_local()
    tomorrow = today + timedelta(days=1)

    # 1) planning: the administrator only; the site's address first (needed for weather and reminders)
    payload = server.ActivityPayload(description="Smontaggio sanitari", date=tomorrow.isoformat(), start_time="8:00", end_time="12:00",
                                     assignees=[server.ActivityAssignee(type="user", id="u2"), server.ActivityAssignee(type="collab", id=gino["id"])],
                                     items=[server.ActivityItem(category="attrezzi", text="flex")], info="chiavi dal portiere")
    assert "indirizzo del cantiere" in await deny(server.create_activity("s_bagno", payload, me), 400)
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == "s_bagno")
    sub["data"]["indirizzo_cantiere"] = "Via Garibaldi 5, Torino"
    await deny(server.create_activity("s_bagno", payload, MARCO), (403, 404))
    BOT_SENT.clear()
    a = await server.create_activity("s_bagno", payload, me)
    assert a["start_time"] == "08:00" and [p["confirm"]["status"] for p in a["assignees"]] == ["in_attesa", "in_attesa"]
    assert any("Nuova attività per te" in t for t, _ in to(78)) and any("Nuova attività per te" in t for t, _ in to(900))
    people = await server.plan_people("s_bagno", me)
    assert {(p["type"], p["name"]) for p in people} >= {("user", "Marco Bianchi"), ("collab", "Gino Neri")}

    # 2) the day before at 18:00: to each assignee - activity, start, what to bring by category, info, open problems, weather
    db.job_logs.docs.append({"id": "lp", "commessa_id": "s_bagno", "date": today.isoformat(), "problems": ["manca il sifone"], "hours": [], "materials": []})
    BOT_SENT.clear()
    assert await server._activity_notifications(at(today, 17, 59)) == 0
    assert await server._activity_notifications(at(today, 18, 0)) == 2
    g1, kb = to(900)[-1]
    assert "Smontaggio sanitari · inizio 08:00 – fine 12:00" in g1 and "*Attrezzi*:\n• flex" in g1 and "chiavi dal portiere" in g1, g1
    assert "Problemi aperti: manca il sifone" in g1 and "pioggia 80%" in g1 and "potrebbe impedire i lavori" in g1
    assert buttons(kb) == [f"acf:{a['id']}", f"acn:{a['id']}", f"aca:{a['id']}"]
    assert await server._activity_notifications(at(today, 18, 30)) == 0          # once
    # Gino adds something to remember (AUT-G1-03), Marco confirms, Gino can't (the administrator told at once)
    assert await tap(900, f"aca:{a['id']}")
    assert await send(900, "porto anche i flessibili da 30 cm")
    act = next(x for x in db.job_activities.docs if x["id"] == a["id"])
    assert [(i["category"], i["text"], i["added_by"]) for i in act["items"]][-1] == ("materiali", "porto anche i flessibili da 30 cm", "Gino Neri")
    assert (await server.confirm_activity(a["id"], server.ActivityConfirmPayload(status="confermato"), MARCO))["message"].startswith("👍")
    NOTICES.clear()
    assert await tap(900, f"acn:{a['id']}")
    assert await send(900, "ho la febbre")
    assert any("Gino Neri* non può esserci per «Smontaggio sanitari»" in t and "ho la febbre" in t for _c, t in NOTICES), NOTICES
    # one who does not answer: asked again at 21:00, the administrator told at 7:00 (AUT-G1-02)
    b = await server.create_activity("s_bagno", server.ActivityPayload(description="Tracce elettriche", date=tomorrow.isoformat(), start_time="13:00",
                                     assignees=[server.ActivityAssignee(type="user", id="u2")]), me)
    await server._activity_notifications(at(today, 18, 5))
    BOT_SENT.clear()
    assert await server._activity_notifications(at(today, 21, 0)) == 1 and "Confermi che ci sei?" in to(78)[-1][0]
    NOTICES.clear()
    await server._activity_notifications(at(tomorrow, 7, 0))
    assert any("Non hanno confermato «Tracce elettriche»" in t and "Marco Bianchi" in t for _c, t in NOTICES), NOTICES

    # 3) the message of the day: 7:00 or an hour before the first start (here 7:00), pinned, with the activity and what to bring
    PINS.clear()
    assert await server._collab_day_briefs(at(tomorrow, 6, 59)) == 0
    assert await server._collab_day_briefs(at(tomorrow, 7, 0)) == 1
    op, chat, text, kb = PINS[-1]
    assert op == "send" and chat == 900 and "Smontaggio sanitari · ore 08:00" in text and "Materiali: porto anche i flessibili da 30 cm (Gino Neri)" in text, text
    assert f"cldone:a:{a['id']}" in buttons(kb)
    assert await server._user_day_briefs(at(tomorrow, 7, 0)) == 1
    assert PINS[-1][1] == 78 and "Tracce elettriche · ore 13:00" in PINS[-1][2] and f"udone:a:{b['id']}" in buttons(PINS[-1][3])

    # 4) missed arrival (AUT-DAY-02): no check-in by start + 30 min -> the administrator told, the operator asked
    BOT_SENT.clear(); NOTICES.clear()
    assert await server._activity_notifications(at(tomorrow, 8, 29)) == 0
    await server._activity_notifications(at(tomorrow, 8, 31))
    assert any("Non risulti ancora arrivato su «Bagno» (inizio previsto 08:00)" in t for t, _ in to(78))
    assert not to(900)                                                            # (Gino said he can't)
    assert any("*Marco Bianchi* non ha segnato l'arrivo su «Bagno»" in t for _c, t in NOTICES)
    # "arrivato alle 8:10": a declared check-in; the activity in progress
    owner = server.User(**db.users.docs[0])
    view = server._commessa_view(sub, db.collection_items.docs[0], cl)
    await server._presence_start(server._user_worker(db.users.docs[1], "u1"), owner, view, at(tomorrow, 8, 10), None)
    ws = db.work_sessions.docs[-1]
    assert ws["origin"] == "dichiarata" and next(x for x in db.job_activities.docs if x["id"] == a["id"])["status"] == "in_corso"
    # missed exit (AUT-DAY-03): the activity's end (12:00) + 30 min
    assert await server._presence_late_check(at(tomorrow, 12, 25)) == 0
    assert await server._presence_late_check(at(tomorrow, 12, 35)) == 1

    # 5) a note says it was done: the activity done (AUT-SVO-01)
    async def interp(t, speaker, team, known=None, user_id=None, channel="web", photos=0):
        return {"kind": "nota", "doubt": "", "date": tomorrow.isoformat() if tomorrow <= jl.today_local() else jl.today_local().isoformat(), "text": t,
                "hours": [], "materials": [], "problems": [], "client": "", "commessa": ""}
    jl.interpret = interp
    db.job_activities.docs[0]["date"] = jl.today_local().isoformat()
    r = await server._save_job_log(me, "smontati tutti i sanitari del bagno", commessa_id="s_bagno")
    assert "✅ Attività svolta: Smontaggio sanitari" in r["message"], r["message"]
    assert next(x for x in db.job_activities.docs if x["id"] == a["id"])["status"] == "svolta"
    db.job_activities.docs[0]["date"] = tomorrow.isoformat()

    # 6) the evening summary to the administrator, by site (AUT-DAY-05), once
    BOT_SENT.clear()
    db.job_logs.docs.append({"id": "lx", "commessa_id": "s_bagno", "date": tomorrow.isoformat(), "problems": ["perdita dal tubo"], "hours": [{"who": "Marco", "hours": 4}],
                             "materials": [], "expenses": [{"label": "nastro", "amount": 8}], "author_name": "Marco"})
    assert await server._daily_site_summary(at(tomorrow, 19, 59)) == 0
    assert await server._daily_site_summary(at(tomorrow, 20, 0)) == 1
    summ = to(77)[-1][0]
    assert "Riepilogo di oggi" in summ and "*Bagno* — Mario Rossi" in summ and "Marco Bianchi 08:10–…" in summ, summ
    assert "Nuovi problemi: perdita dal tubo" in summ and "nastro € 8" in summ and "Marco Bianchi senza uscita segnata" in summ
    assert "Pianificate non ancora svolte: Tracce elettriche" in summ
    assert await server._daily_site_summary(at(tomorrow, 20, 30)) == 0

    # 7) planned from the chat: "pianifica … con Marco"
    async def read_act(text, people, user_id=None, channel="web"):
        return {"description": "Posa piastrelle", "date": (today + timedelta(days=5)).isoformat(), "start": "08:30", "end": "",
                "assignees": ["Marco Bianchi"], "items": ["colla per piastrelle", "casco"], "info": ""}
    jl.read_activity = read_act
    r = await server._save_job_log(me, "pianifica posa piastrelle tra 5 giorni alle 8:30 con Marco, portare colla e casco", commessa_id="s_bagno")
    assert r["status"] == "commessa_update" and "Posa piastrelle" in r["message"] and "Marco Bianchi" in r["message"] and "DPI: casco" in r["message"], r
    d = await server.get_job_commessa("s_bagno", current=me)
    assert [x["description"] for x in d["activities"]][-1] == "Posa piastrelle" and d["activities"][0]["status"] in ("svolta",)
    print("ALL OK")

asyncio.run(main())
