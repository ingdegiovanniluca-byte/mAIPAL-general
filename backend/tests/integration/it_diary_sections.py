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
    def __init__(s, n): s.modified_count = n; s.deleted_count = n

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
"""The commessa diary's sections: a note changed only by who wrote it (each change kept), the hours' distance alert out of
the text (over 200 m), problems that stay open vs of one day, their corrective action, closed by a note only once confirmed,
tools apart from materials, materials for the whole team, reminders left behind asked about two days later."""
import job_logs as jl, telegram_bot as tg, embeddings as emb, collab_telegram as ct, milestone_templates as mtpl
import json as _json, telegram
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")
U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77, "tenant_id": "ten_1"}
db.users.docs.append(dict(U))
db.users.docs.append({"user_id": "u9", "email": "z@b.it", "name": "Zeno Altri", "role": "user", "telegram_chat_id": 99, "tenant_id": "ten_9"})
tg.bot_token = lambda: "123:abc"
async def _bot_name(): return "maipal_bot"
tg.bot_username = _bot_name
NOTICES, TOLD, BOT_SENT, PUSHED, PINNED = [], [], [], [], []
async def fake_send(chat_id, text):
    NOTICES.append((chat_id, text)); return True
server._send_telegram_text = fake_send
async def fake_tell(c, text, done_data=None, kb=None):
    if c.get("status") != "active" or not c.get("telegram_chat_id"):
        return False
    TOLD.append((c["id"], text, kb)); return True
server._tell_collaborator = fake_tell
class FakeBot:
    def __init__(self, token=None): pass
    async def send_message(self, chat_id=None, text=None, reply_markup=None, **k): BOT_SENT.append((chat_id, text, reply_markup))
telegram.Bot = FakeBot
server.push.fire_and_forget = lambda db_, uid, title, body, url="/", tag=None, kind=None: PUSHED.append((uid, title, body, kind))
server._day_pin_touch = lambda *ids: PINNED.append({x for x in ids if x})
async def no_emb(q): raise RuntimeError("offline")
emb.embed_query = no_emb

# the model is faked: the diary's reading (MODEL_SAYS) and the extras check (EXTRAS); jl's own checks run for real
MODEL_SAYS, EXTRAS, EXTRA_CALLS = {}, {"extras": []}, []
class _Resp:
    def __init__(s, content): s.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]; s.usage = None
class _Completions:
    async def create(s, **kw):
        if "PREVENTIVO" in kw["messages"][1]["content"]:
            EXTRA_CALLS.append(kw["messages"][0]["content"])   # (the works done: none; the work to do: EXTRAS)
            return _Resp(_json.dumps(EXTRAS if "LAVORI DA FARE" in kw["messages"][0]["content"] else {"extras": []}))
        return _Resp(_json.dumps(MODEL_SAYS))
class _Client:
    def __init__(s, **kw): s.chat = type("Ch", (), {"completions": _Completions()})()
jl.openai.AsyncOpenAI = _Client
jl._track = lambda *a, **k: None
def model(text="", problems=None, details=None, materials=None, tools=None, hours=None):
    MODEL_SAYS.clear(); MODEL_SAYS.update({"kind": "nota", "doubt": "", "date": "", "text": text, "hours": hours or [], "materials": materials or [],
                                           "problems": problems or [], "problem_details": details or [], "tools": tools or [], "waiting": None,
                                           "client": "", "commessa": ""})

class Msg:
    def __init__(s, text): s.text = text; s.location = None; s.voice = None; s.photo = None; s.caption = None; s.contact = None; s.replies = []
    async def reply_text(s, text, **kw): s.replies.append((text, kw.get("reply_markup")))
class Chat:
    def __init__(s, i=900): s.id = i
class Bot:
    async def send_chat_action(s, **kw): pass
    async def send_message(s, chat_id=None, text=None, reply_markup=None, **k): BOT_SENT.append((chat_id, text, reply_markup))
class Ctx:
    bot = Bot()
class Upd:
    def __init__(s, msg, chat=900): s.message = msg; s.callback_query = None; s.effective_chat = Chat(chat)
class Q:
    def __init__(s, data): s.data = data; s.message = Msg(""); s.cleared = False
    async def answer(s): pass
    async def edit_message_reply_markup(s, reply_markup=None): s.cleared = True
class CbUpd:
    def __init__(s, data, chat=900): s.message = None; s.callback_query = Q(data); s.effective_chat = Chat(chat)
def recs(chat=900):
    return [c for c in db.collaborators.docs if c.get("telegram_chat_id") == chat]
async def say(text, chat=900):
    m = Msg(text)
    await ct.handle_message(Upd(m, chat), Ctx(), recs(chat))
    return m.replies
async def tap(data, chat=900):
    u = CbUpd(data, chat)
    await ct.handle_callback(u, None, recs(chat))
    return u.callback_query.message.replies
def buttons(markup):
    return [b.callback_data for row in (markup.inline_keyboard if markup else []) for b in row]
def at(day, hh, mm=0):
    return datetime.combine(day, datetime.min.time(), tzinfo=ROME).replace(hour=hh, minute=mm).astimezone(timezone.utc)
async def settle():
    for _ in range(20):
        await asyncio.sleep(0)

db.tenants.docs.append({"id": "ten_1", "name": "Impresa Rossi", "owner_user_id": "u1", "owner_email": "a@b.it",
                       "plan": {"max_users": 5, "max_collaborators": 5, "max_admins": 2}, "sharing": {"users_share": True, "collab_contacts": False}})
NOTE = "Controllo caldaia, ventilatore danneggiato, si attende il via libera per la sostituzione dal proprietario"
PROBLEM = "Ventilatore danneggiato, si attende il via libera per la sostituzione dal proprietario"


import site_presence as sp


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    db.users.docs.append({"user_id": "u2", "email": "m@b.it", "name": "Marco Bianchi", "role": "user", "tenant_id": "ten_1", "org_id": me.org_id,
                          "telegram_chat_id": 88})
    MARCO = server.User(**db.users.docs[-1])
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_b", "collection_id": cl["id"], "data": {"nome": "Bianchi"}})
    db.collection_sub_items.docs.append({"id": "s1", "collection_id": cl["id"], "item_id": "c_b", "shared_with": ["u2"],
                                         "data": {"titolo": "Impianto", "stato": "in lavorazione"}})
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Avanzino", last_name="Neri", phone="333 1234567", role="Elettricista",
                                                                    company="Idro", commesse=["s1"]), me)
    ava = r["collaborator"]
    next(c for c in db.collaborators.docs if c["id"] == ava["id"]).update(status="active", telegram_chat_id=900)
    today = jl.today_local()

    # 1) a note is changed only by who wrote it; each change is kept (who, when, what it was); the message as sent too
    model(text="Posati 20 m di cavo")
    r = await server._save_job_log(me, "posati 20 m di cavo", commessa_id="s1")
    lid = r["log"]["id"]
    assert (await server.get_job_log(lid, me))["mine"] is True
    assert (await server.get_job_log(lid, MARCO))["mine"] is False
    msg = await deny(server.update_job_log(lid, server.JobLogPatch(text="Posati 30 m di cavo"), MARCO))
    assert "solo chi l'ha scritta" in msg
    out = await server.update_job_log(lid, server.JobLogPatch(text="Posati 25 m di cavo"), me)
    assert out["text"] == "Posati 25 m di cavo" and out["raw_text"] == "posati 20 m di cavo"
    e = out["edits"][-1]
    assert e["by"] == "Luca" and e["before"] == {"text": "Posati 20 m di cavo"} and e["at"]
    # the message as it was sent: never changed, not even by who wrote it
    assert "non si modifica" in await deny(server.update_job_log(lid, server.JobLogPatch(raw_text="altro"), me), 400)
    # the phase and the hours worked: an administrator may correct them on someone else's note (the change written on it);
    # the rest of the note never
    model(text="Marco 4 ore", hours=[{"who": "Marco", "hours": 4}])
    rm = await server._save_job_log(MARCO, "io 4 ore", commessa_id="s1")
    out = await server.update_job_log(rm["log"]["id"], server.JobLogPatch(phase="sopralluogo"), me)
    assert out["phase"] == "sopralluogo"
    out = await server.update_job_log(rm["log"]["id"], server.JobLogPatch(hours=[{"who": "Marco", "hours": 3.5}]), me)
    c = out["hours_changes"][-1]
    assert out["hours"] == [{"who": "Marco", "hours": 3.5}] and c["by"] == "Luca" and c["admin"] is True
    assert c["before"] == [{"who": "Marco", "hours": 4.0}] and c["after"] == [{"who": "Marco", "hours": 3.5}]
    await deny(server.update_job_log(rm["log"]["id"], server.JobLogPatch(text="x"), me))
    await deny(server.update_job_log(lid, server.JobLogPatch(hours=[{"who": "Luca", "hours": 9}]), MARCO))   # (a user: not others' hours)
    # a collaborator's note: nobody changes it in the app
    model(text="Fatte le tracce")
    await say("fatte le tracce")
    clog = next(lg for lg in db.job_logs.docs if lg.get("collaborator_id") == ava["id"])
    await deny(server.update_job_log(clog["id"], server.JobLogPatch(text="x"), me))

    # 2) the hours of a presence: the distance is not in the text (it is on the line under it); alert over 200 m
    assert sp.ON_SITE_METERS == 200 and sp.far(250) and not sp.far(150)
    view = server._commessa_view(next(x for x in db.collection_sub_items.docs if x["id"] == "s1"), db.collection_items.docs[0], cl)
    start = datetime.now(timezone.utc) - timedelta(hours=8)
    plog = server._presence_log(next(c for c in db.collaborators.docs if c["id"] == ava["id"]), me, view,
                                {"id": "ws1", "start_at": start.isoformat(), "start_m": 1200, "start_loc": {"lat": 45, "lon": 9}},
                                datetime.now(timezone.utc), 480, 30, {"lat": 45, "lon": 9}, 40)
    assert "dal cantiere" not in plog["text"] and "⚠️" not in plog["text"] and plog["presence"]["start_m"] == 1200
    # the presence's text is the app's: never changed; the administrator corrects the pause (the hours follow) and the hours
    await db.job_logs.insert_one(plog)
    assert plog["hours"][0]["hours"] == 7.5
    assert "registrato l'app" in await deny(server.update_job_log(plog["id"], server.JobLogPatch(text="In cantiere tutto il giorno"), me), 400)
    out = await server.update_job_log(plog["id"], server.JobLogPatch(pause_min=60), me)
    c = out["hours_changes"][-1]
    assert out["presence"]["pause_min"] == 60 and out["hours"][0]["hours"] == 7.0 and out["text"] == plog["text"]
    assert (c["pause_before"], c["pause_after"], c["before"][0]["hours"], c["after"][0]["hours"]) == (30, 60, 7.5, 7.0)
    assert out["edits"][-1]["before"]["pause_min"] == 30
    await deny(server.update_job_log(plog["id"], server.JobLogPatch(pause_min=0), MARCO))

    # 3) problems: one that stays open (with its corrective action), one of that day only; read with the page
    P1 = "Non è stato possibile montare gli interruttori perché non è arrivata la fornitura del materiale"
    P2 = "Gino non è venuto perché non stava bene"
    NOTE = ("Oggi non è stato possibile montare gli interruttori perché non è arrivata la fornitura del materiale, ho chiamato il fornitore, "
            "arriva giovedì. Gino non è venuto perché non stava bene")
    model(text=NOTE, problems=[P1, P2], details=[{"text": P1, "lasting": True, "action": "Ho chiamato il fornitore, arriva giovedì"},
                                                 {"text": P2, "lasting": True, "action": "Ha chiamato il medico"}])   # (a wrong reading: the words win)
    r = await server._save_job_log(me, NOTE, commessa_id="s1")
    info = r["log"]["problem_info"]
    assert info["0"] == {"lasting": True, "action": "Ho chiamato il fornitore, arriva giovedì"}, info
    assert info["1"]["lasting"] is False and info["1"]["action"] == ""       # the words win; an action not written is not kept
    pid = r["log"]["id"]
    t = (await server.get_job_commessa("s1", current=me))["totals"]["problems"]
    p1, p2 = next(p for p in t if p["text"] == P1), next(p for p in t if p["text"] == P2)
    assert p1["status"] == "aperta" and p1["action"].startswith("Ho chiamato") and p2["status"] == "del_giorno"
    # that day's only: open on its day, gone from the open ones the day after
    assert [x[2] for x in await server._open_problems("s1")] == [P1, P2]
    with jl.as_of(today + timedelta(days=1)):
        assert [x[2] for x in await server._open_problems("s1")] == [P1]
    assert not jl.problem_lasting(P2) and jl.problem_lasting(P1) and not jl.problem_lasting("Pioggia forte, lavori sospesi")
    # the circle in Problemi closes it, and the page reads it back (it used to stay "aperta")
    await server.patch_job_problem(pid, 0, server.ProblemPatch(resolved=True), me)
    assert next(p for p in (await server.get_job_commessa("s1", current=me))["totals"]["problems"] if p["text"] == P1)["status"] == "risolta"
    await server.patch_job_problem(pid, 0, server.ProblemPatch(resolved=False), me)

    # 4) a note that solves it: proposed, never closed by itself; on Telegram the collaborator confirms with the button
    model(text="È arrivato il materiale per procedere con l'installazione degli interruttori")
    replies = await say("è arrivato il materiale per procedere con l'installazione degli interruttori")
    q = [(t, kb) for t, kb in replies if t.startswith("❓")]
    assert q and P1 in q[0][0] and buttons(q[0][1]) == [f"cpx:y:{pid}:0", f"cpx:n:{pid}:0"], replies
    p1 = next(p for p in (await server.get_job_commessa("s1", current=me))["totals"]["problems"] if p["text"] == P1)
    assert p1["status"] == "aperta" and p1["proposed"]["by"] == "Avanzino"
    NOTICES.clear()
    out = await tap(f"cpx:y:{pid}:0")
    assert out[0][0] == f"✅ Chiuso: «{P1}»."
    assert next(p for p in (await server.get_job_commessa("s1", current=me))["totals"]["problems"] if p["text"] == P1)["status"] == "risolta"
    assert any(c == 77 and "ha chiuso il problema" in t for c, t in NOTICES)
    assert jl.problems_maybe_resolved("è arrivato il materiale per procedere con l'installazione degli interruttori", [P1, "Manca la colla"]) == [0]

    # 5) tools apart from the materials; "tutto il team": every collaborator of the commessa and the team's users
    day = today + timedelta(days=3)   # (a day ahead: its reminders still to come, whatever the time the test runs)
    tomorrow = day.isoformat()
    model(text="", materials=[{"name": "scatole 503", "qty": 10, "unit": "pz", "status": "da_prendere", "for_date": tomorrow}],
          tools=[{"name": "trapano a percussione", "for_date": tomorrow, "who": "tutto il team"}])
    TOLD.clear(); PUSHED.clear()
    r = await server._save_job_log(me, f"il {day.day}/{day.month} 10 scatole 503 e tutto il team porta il trapano a percussione", commessa_id="s1")
    assert r["status"] == "planned", r
    tool = next(t for t in db.job_todos.docs if t.get("category") == "attrezzi")
    assert tool["text"] == "Da portare: trapano a percussione" and tool["who"] == "Tutto il team"
    assert tool["shared_with"] == [ava["id"]] and tool["assignee_user_ids"] == ["u2"], tool
    assert any(c == ava["id"] and "da portare" in t for c, t, _k in TOLD) and any(p[0] == "u2" for p in PUSHED)
    assert "Da portare (attrezzi) " in r["message"] and "Lo ricordo a tutti" in r["message"], r["message"]
    mat = next(t for t in db.job_todos.docs if t.get("kind") == "materiale" and t.get("category") == "materiali")
    assert mat["text"] == "Da prendere: 10 pz scatole 503"
    # reminders: the users of the group too
    PUSHED.clear()
    eve, _m = server._mat_reminder_times(tomorrow)
    await server._material_reminders(eve.astimezone(timezone.utc) + timedelta(minutes=1))
    assert any(p[0] == "u2" and "Domani da portare" in p[1] for p in PUSHED), PUSHED

    # 6) left behind: two days after its day, the people are asked (once): used, delete, move
    TOLD.clear(); BOT_SENT.clear()
    later = datetime.combine(day + timedelta(days=3), datetime.min.time(), tzinfo=ROME).replace(hour=9, minute=30)
    n = await server._material_expired(later.astimezone(timezone.utc))
    assert n >= 2, n
    told = [(t, kb) for c, t, kb in TOLD if c == ava["id"]]
    assert any("Promemoria scaduto" in t and buttons(kb) == [f"cmx:usato:{tool['id']}", f"cmx:elimina:{tool['id']}", f"cmx:domani:{tool['id']}",
                                                            f"cmx:settimana:{tool['id']}"] for t, kb in told), told
    assert any(c == 77 and "Promemoria scaduto" in t and f"mx:usato:{mat['id']}" in buttons(kb) for c, t, kb in BOT_SENT), BOT_SENT
    assert await server._material_expired(later.astimezone(timezone.utc)) == 0                      # once
    # used: done, and the materials go in the diary as used by who said it
    out = await server._material_expired_answer(mat["id"], "usato", {"kind": "user", "id": "u1", "name": "Luca"})
    assert out.startswith("✅ Segnati come usati") and next(t for t in db.job_todos.docs if t["id"] == mat["id"])["done"]
    used = next(lg for lg in db.job_logs.docs if lg.get("from_todo_id") == mat["id"])
    assert used["materials"] == [{"name": "scatole 503", "qty": 10.0, "unit": "pz"}] and used["author_name"] == "Luca"
    # moved a week on (the collaborator, with the button): asked again only after that
    out = (await tap(f"cmx:settimana:{tool['id']}"))[0][0]
    t2 = next(t for t in db.job_todos.docs if t["id"] == tool["id"])
    assert out.startswith("📅 Spostato") and t2["due_date"] == (today + timedelta(days=7)).isoformat() and t2["reminded"] == {}
    assert "non è tuo" in await server._material_expired_answer(tool["id"], "elimina", {"kind": "collab", "id": "nobody", "name": "X"})

    # 7) the materials used in a period: the same material written differently is one line
    tot = jl.totals([{"materials": [{"name": "scatole 503", "qty": 10, "unit": "pz"}, {"name": "Scatola 503", "qty": 2, "unit": "pz"},
                                    {"name": "tubo 16", "qty": 1, "unit": "m"}, {"name": "tubo 20", "qty": 1, "unit": "m"}]}])
    assert [(m["name"], m["qty"]) for m in tot["materials"]] == [("scatole 503", 12.0), ("tubo 16", 1.0), ("tubo 20", 1.0)]
    print("ALL OK")


async def deny(coro, code=403):
    try:
        await coro
    except server.HTTPException as e:
        assert e.status_code == code, (e.status_code, e.detail)
        return e.detail
    raise AssertionError("not denied")

from datetime import date
asyncio.run(main())
