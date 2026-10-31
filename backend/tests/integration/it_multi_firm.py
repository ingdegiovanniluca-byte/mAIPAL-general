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
from llm_integrations import TextDelta, StreamDone
import job_logs as jl, collab_telegram as ct, telegram_bot as tg
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from telegram.ext import ApplicationHandlerStop
import telegram

# two firms: Impresa Rossi (Luca) and Edil Beta (Bea), each with its own administrator
U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77, "tenant_id": "ten_1"}
UB = {"user_id": "u3", "email": "bea@beta.it", "name": "Bea Neri", "role": "admin", "telegram_chat_id": 88, "tenant_id": "ten_2"}
db.users.docs += [dict(U), dict(UB)]
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

for tid, uid, em, name in (("ten_1", "u1", "a@b.it", "Impresa Rossi"), ("ten_2", "u3", "bea@beta.it", "Edil Beta")):
    db.tenants.docs.append({"id": tid, "name": name, "owner_user_id": uid, "owner_email": em,
                            "plan": {"max_users": 5, "max_collaborators": 5, "max_admins": 1}, "sharing": {"users_share": True, "collab_contacts": False}})

GINO = 900   # the electrician's Telegram chat


async def firm(u, client_id, client_name, comm_id, title):
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**u))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti" and c.get("user_id") == u["user_id"])
    db.collection_items.docs.append({"id": client_id, "collection_id": cl["id"], "data": {"nome": client_name, "telefono": "", "email": ""}})
    db.collection_sub_items.docs.append({"id": comm_id, "collection_id": cl["id"], "item_id": client_id, "data": {"titolo": title, "stato": "in corso"}})
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Volta", role="elettricista",
                                                                    company="Volta Impianti", commesse=[comm_id]), me)
    return me, r["collaborator"]["id"], r["invite"]["code"]


def rec(cid):
    return next(c for c in db.collaborators.docs if c["id"] == cid)


def log_of(text):
    return next(lg for lg in db.job_logs.docs if text in (lg.get("text") or ""))


async def main():
    me_a, ca, code_a = await firm(U, "c_rossi", "Mario Rossi", "s_bagno", "Bagno")
    me_b, cb, code_b = await firm(UB, "c_verdi", "Anna Verdi", "s_tetto", "Tetto")
    assert rec(ca)["tenant_id"] == "ten_1" and rec(cb)["tenant_id"] == "ten_2"

    # 1) the same Telegram account linked by both firms: two records, one chat
    assert await send(GINO, f"/start {code_a}")
    assert "collaboratore di Impresa Rossi" in REPLIES[-1][0] and "più imprese" not in REPLIES[-1][0]
    assert await send(GINO, f"/start {code_b}")
    linked = REPLIES[-1][0]
    assert "collaboratore di Edil Beta" in linked and "più imprese" in linked and "Tetto" in linked and "Bagno" not in linked
    assert rec(ca)["telegram_chat_id"] == rec(cb)["telegram_chat_id"] == GINO
    # each firm sees only its own record
    assert [c["id"] for c in await server.list_collaborators(me_a)] == [ca]
    assert [c["id"] for c in await server.list_collaborators(me_b)] == [cb]

    # 2) a message naming a commessa: in that firm's diary, with that firm's record
    jl.interpret = said(hours=[{"who": "io", "hours": 4}])
    assert await send(GINO, "nel bagno dei Rossi posato il quadro elettrico")
    la = log_of("quadro elettrico")
    assert la["commessa_id"] == "s_bagno" and la["collaborator_id"] == ca, la
    assert rec(ca).get("last_message_at") and not rec(cb).get("last_message_at")       # firm B sees nothing of it
    assert await send(GINO, "sul tetto dei Verdi passati i cavi del fotovoltaico")
    lb = log_of("fotovoltaico")
    assert lb["commessa_id"] == "s_tetto" and lb["collaborator_id"] == cb
    # the next message a few minutes later: the same conversation (firm B's commessa)
    assert await send(GINO, "montate anche le canaline")
    assert log_of("canaline")["collaborator_id"] == cb and log_of("canaline")["commessa_id"] == "s_tetto"

    # 3) nothing to go by: he chooses - the buttons carry the firm's name
    for c in (rec(ca), rec(cb)):
        c["tg_state"] = {"target": c.get("tg_state", {}).get("target"), "at": "2020-01-01T00:00:00+00:00"}
    assert await send(GINO, "fatto il collaudo")
    text, kb = REPLIES[-1]
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "Di quale commessa" in text and buttons(kb) == ["clc:s_bagno", "clc:s_tetto"], text
    assert any("Impresa Rossi" in x for x in labels) and any("Edil Beta" in x for x in labels), labels
    held = [c for c in db.collaborators.docs if (c.get("pending") or {}).get("text")]
    assert len(held) == 1
    assert await tap(GINO, "clc:s_tetto")
    assert log_of("collaudo")["collaborator_id"] == cb and log_of("collaudo")["commessa_id"] == "s_tetto"
    assert not any((c.get("pending") or {}).get("text") for c in db.collaborators.docs)

    # 4) a question: answered on that commessa only, the history kept with that firm's record
    jl.interpret = said(kind="domanda")
    assert await send(GINO, "cosa manca da fare nel bagno dei Rossi?")
    assert ANSWERS[-1]["view"]["id"] == "s_bagno"
    assert rec(ca).get("tg_history") and not rec(cb).get("tg_history")

    # 5) one reminder at 18:00, not one per firm, with the commesse of both
    BOT_SENT.clear()
    tomorrow = jl.today_local() + timedelta(days=1)
    while tomorrow.weekday() >= 5:
        tomorrow += timedelta(days=1)
    at = datetime.combine(tomorrow, datetime.min.time(), tzinfo=server.LOCAL_TZ).replace(hour=18, minute=30)
    assert await server._collab_remind_due(at.astimezone(timezone.utc)) == 1
    to_gino = [m for m in BOT_SENT if m[0] == GINO]
    assert len(to_gino) == 1 and buttons(to_gino[0][2]) == ["clc:s_bagno", "clc:s_tetto"]
    assert await server._collab_remind_due(at.astimezone(timezone.utc)) == 0      # once a day

    # 6) the day's pinned message (one per firm) says which firm it is
    text, _kb = server._day_pin_body(tomorrow.isoformat(), [], "Edil Beta")
    assert "Edil Beta" in text.splitlines()[0]

    # 7) firm A suspends him: firm B's commesse still work, A's are gone
    await server.update_collaborator(ca, server.CollaboratorPatch(status="suspended"), me_a)
    assert rec(ca)["status"] == "suspended" and rec(cb)["status"] == "active"
    n_bagno = sum(1 for lg in db.job_logs.docs if lg["commessa_id"] == "s_bagno")
    jl.interpret = said()
    assert await send(GINO, "oggi tirati i cavi")
    assert log_of("tirati i cavi")["commessa_id"] == "s_tetto" and log_of("tirati i cavi")["collaborator_id"] == cb
    assert sum(1 for lg in db.job_logs.docs if lg["commessa_id"] == "s_bagno") == n_bagno
    # and firm B cannot touch firm A's record
    try:
        await server.update_collaborator(ca, server.CollaboratorPatch(status="active"), me_b); assert False
    except HTTPException as e:
        assert e.status_code == 404
    print("ALL OK")

asyncio.run(main())
