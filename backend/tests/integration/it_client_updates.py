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
import job_logs as jl, telegram_bot as tg, retrieval, embeddings as emb
import scheduled_actions as sa
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77}
db.users.docs.append(dict(U))
tg.bot_token = lambda: "123:abc"
NOTICES = []
async def fake_send(chat_id, text):
    NOTICES.append((chat_id, text)); return True
server._send_telegram_text = fake_send
TOLD = []
async def fake_tell(c, text, done_data=None):   # a collaborator's message (with the "Fatto" button)
    if c.get("status") != "active" or not c.get("telegram_chat_id"):
        return False
    NOTICES.append((c["telegram_chat_id"], text)); TOLD.append((c["id"], text, done_data)); return True
server._tell_collaborator = fake_tell
async def no_emb(q): raise RuntimeError("offline")
emb.embed_query = no_emb
def said(hours=None, materials=None, problems=None, date=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web"):
        return {"kind": "nota", "doubt": "", "date": date or jl.today_local().isoformat(), "text": t,
                "hours": jl.clean_hours(hours or [], speaker), "materials": jl.clean_materials(materials or []),
                "problems": problems or [], "client": "", "commessa": ""}
    return f
ANSWERS = []
async def fake_answer(commessa, logs, reports, question, history, user_id=None, channel="web"):
    ANSWERS.append(commessa); return {"answer": "ok", "is_entry": False}
jl.answer = fake_answer

async def settle():
    for _ in range(5):
        await asyncio.sleep(0)

import json as _json
import collab_telegram as ct

# the model's answer is faked; interpret's own checks (materials used / to take) run for real
MODEL_SAYS = {}
class _Resp:
    def __init__(s, content): s.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]; s.usage = None
class _Completions:
    async def create(s, **kw): return _Resp(_json.dumps(MODEL_SAYS))
class _Client:
    def __init__(s, **kw): s.chat = type("Ch", (), {"completions": _Completions()})()
jl.openai.AsyncOpenAI = _Client
jl._track = lambda *a, **k: None
def model(text="", hours=None, materials=None, problems=None):
    MODEL_SAYS.clear(); MODEL_SAYS.update({"kind": "nota", "doubt": "", "date": "", "text": text, "hours": hours or [],
                                           "materials": materials or [], "problems": problems or [], "client": "", "commessa": ""})
PUSHED = []
server.push.fire_and_forget = lambda db_, uid, title, body, url="/", tag=None: PUSHED.append((uid, title, body))

class Msg:
    def __init__(s, text): s.text = text; s.location = None; s.voice = None; s.photo = None; s.caption = None; s.contact = None; s.replies = []
    async def reply_text(s, text, **kw): s.replies.append((text, kw.get("reply_markup")))
class Chat:
    id = 900
class Bot:
    async def send_chat_action(s, **kw): pass
class Ctx:
    bot = Bot()
class Upd:
    def __init__(s, msg): s.message = msg; s.callback_query = None; s.effective_chat = Chat()
class Q:
    def __init__(s, data): s.data = data; s.message = Msg(""); s.cleared = False
    async def answer(s): pass
    async def edit_message_reply_markup(s, reply_markup=None): s.cleared = True
class CbUpd:
    def __init__(s, data): s.message = None; s.callback_query = Q(data); s.effective_chat = Chat()
import client_telegram as ctg, client_updates as cu
from fastapi import HTTPException
async def _bot_name(): return "maipal_bot"
tg.bot_username = _bot_name
SEEN = []
class _Completions3:
    async def create(s, **kw):
        SEEN.append(kw["messages"]); return _Resp(_json.dumps(MODEL_SAYS))
class _Client3:
    def __init__(s, **kw): s.chat = type("Ch", (), {"completions": _Completions3()})()
jl.openai.AsyncOpenAI = _Client3
class CChat:
    id = 950
class CUpd:   # the client's chat
    def __init__(s, text): s.message = Msg(text); s.callback_query = None; s.effective_chat = CChat()
LOC = server.LOCAL_TZ


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi", "telefono": "333 1234567"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    db.collection_sub_items.docs.append({"id": "s_tetto", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Tetto", "stato": "in corso"}})
    today = jl.today_local()
    friday = today + timedelta(days=(4 - today.weekday()) % 7)   # this week's friday (today, if it is)
    day = today.isoformat()
    base = {"user_id": "u1", "commessa_id": "s_bagno", "commessa_title": "Bagno", "client_name": "Mario Rossi", "date": day,
            "materials": [], "problems": [], "photos": [], "created_at": datetime.now(timezone.utc).isoformat()}
    db.job_logs.docs += [
        {**base, "id": "l1", "author_name": "Gino", "text": "Posati i sanitari e il piatto doccia.", "hours": [{"who": "Gino", "hours": 4}]},
        {**base, "id": "l2", "author_name": "Gino", "text": "In cantiere dalle 07:58 alle 12:31 (4 h 33 min)", "hours": [{"who": "Gino", "hours": 4.5}],
         "presence": {"start_at": "x", "end_at": "y"}},
        {**base, "id": "l3", "author_name": "Luca", "text": "Manca il miscelatore, l'idraulico ha sbagliato le quote.", "problems": ["manca il miscelatore"]},
        {**base, "id": "l4", "kind": "stato", "text": "Stato: preventivo → in corso"},
    ]
    db.job_milestones.docs += [
        {"id": "m1", "commessa_id": "s_bagno", "title": "Demolizioni", "due_date": day, "original_due_date": day, "done": True, "done_date": day},
        {"id": "m2", "commessa_id": "s_bagno", "title": "Impianto elettrico", "due_date": (today + timedelta(days=10)).isoformat(),
         "original_due_date": (today + timedelta(days=10)).isoformat(), "done": False},
    ]

    # the text alone: what is private never goes
    src = "Posati i sanitari e il piatto doccia."
    assert cu.safe_lines(["Posati i sanitari e il piatto doccia", "Lavorate 4 ore", "Speso 300 € di sanitari", "Montata la cucina nuova"], src) \
        == ["Posati i sanitari e il piatto doccia"]
    assert cu.safe_lines(["Manca il miscelatore", "Ritardo per colpa del fornitore"], "Manca il miscelatore. Ritardo per colpa del fornitore") == []

    # 1) not linked yet: on for the commessa, friday at 17 by default
    st = await server.get_client_updates("s_bagno", me)
    assert st["status"] == "none" and st["enabled"] and (st["day"], st["at"], st["day_label"]) == (4, "17:00", "venerdì") and st["phone"] == "333 1234567"
    # the invitation: link and code, on WhatsApp to the client
    r = await server.invite_client_updates("s_bagno", server.ClientInvitePayload(), me)
    inv = r["invite"]
    assert r["status"] == "invited" and inv["link"] == f"https://t.me/maipal_bot?start={inv['code']}" and inv["whatsapp_url"].startswith("https://wa.me/393331234567?text=")
    assert "aggiornamento su come avanzano i lavori «Bagno»" in inv["message"]
    # the client opens it on Telegram: linked; the owner told
    NOTICES.clear()
    u = CUpd(f"/start {inv['code']}")
    assert await ctg.try_link(u, inv["code"])
    assert "Da ora riceverà qui ogni settimana" in u.message.replies[-1][0]
    assert any(c == 77 and "Mario Rossi si è collegato" in t for c, t in NOTICES)
    assert (await server.get_client_updates("s_bagno", me))["status"] == "active"
    assert not await ctg.try_link(CUpd("/start NOPE"), "NOPE")
    u = CUpd(f"/start {inv['code']}")                        # used: not a client's any more
    assert not await ctg.try_link(u, inv["code"])

    # 2) what they would get: the works of the week (rewritten, checked), milestones, the next ones
    MODEL_SAYS.clear(); MODEL_SAYS.update({"done": ["Posati i sanitari e il piatto doccia", "Lavorate 4 ore", "Sistemato il problema del miscelatore costato 80 €"]})
    SEEN.clear()
    p = await server.preview_client_update("s_bagno", me)
    print(p["text"])
    t = p["text"]
    assert t.startswith("🏗️ Avanzamento lavori — «Bagno»") and "Questa settimana:\n• Posati i sanitari e il piatto doccia" in t
    assert "✅ Completato: Demolizioni" in t and "Prossimi lavori: Impianto elettrico." in t and t.endswith("Luca Rossi")
    for bad in ("ore", "€", "Gino", "miscelatore", "07:58"):
        assert bad not in t.replace("Avanzamento lavori", "").replace("Prossimi lavori", ""), bad
    given = SEEN[-1][1]["content"]
    assert "Posati i sanitari" in given and "In cantiere dalle" not in given and "Stato:" not in given   # no presences, no events
    assert not [x for x in NOTICES if x[0] == 950]                                                        # nothing sent

    # 3) on friday from 17:00, once
    at = lambda d, hm: datetime.combine(d, datetime.strptime(hm, "%H:%M").time(), tzinfo=LOC).astimezone(timezone.utc)
    if friday == today:
        assert await server._client_weekly_updates(at(friday, "16:59")) == 0
    assert await server._client_weekly_updates(at(friday - timedelta(days=1), "18:00")) == 0   # thursday
    NOTICES.clear()
    n = await server._client_weekly_updates(at(friday, "17:05"))
    assert n == 1, n                                       # the Bagno (the Tetto has nothing this week)
    sent = [t for c, t in NOTICES if c == 950]
    assert len(sent) == 1 and "Posati i sanitari e il piatto doccia" in sent[0]
    assert any(c == 77 and t.startswith("📤 Avanzamento settimanale inviato a Mario Rossi") for c, t in NOTICES)
    assert await server._client_weekly_updates(at(friday, "18:00")) == 0          # not twice
    assert (await server.get_client_updates("s_bagno", me))["last_sent_at"]

    # 4) the client writes: a fixed answer; /stop and /start
    u = CUpd("quante ore avete fatto?")
    assert await ctg.handle(u) and "serve solo a ricevere gli aggiornamenti" in u.message.replies[-1][0] and "Luca Rossi" in u.message.replies[-1][0]
    u = CUpd("/stop")
    assert await ctg.handle(u) and (await server.get_client_updates("s_bagno", me))["status"] == "stopped"
    next_friday = friday + timedelta(days=7)
    for sdoc in db.collection_sub_items.docs:
        (sdoc.get("client_updates") or {}).pop("last_checked", None)
    assert await server._client_weekly_updates(at(next_friday, "17:30")) == 0       # stopped: nothing
    assert await ctg.handle(CUpd("/start")) and (await server.get_client_updates("s_bagno", me))["status"] == "active"
    # turned off for that commessa: nothing for it
    r = await server.patch_client_updates("s_bagno", server.ClientUpdatesPatch(enabled=False), me)
    assert not r["enabled"]
    assert await server._client_weekly_updates(at(next_friday, "17:30")) == 0
    await server.patch_client_updates("s_bagno", server.ClientUpdatesPatch(enabled=True), me)
    # an ordinary chat is not a client's
    assert not await ctg.handle(Upd(Msg("ciao")))

    # 5) the day and hour are the owner's
    me = await server.update_profile(server.ProfilePatch(client_update_day=0, client_update_at="08:30"), me)
    st = await server.get_client_updates("s_bagno", me)
    assert (st["day"], st["at"], st["day_label"]) == (0, "08:30", "lunedì")

    # 6) send now: nothing to tell -> said; then the link removed
    try:
        await server.send_client_update_now("s_tetto", me); assert False
    except HTTPException as e:
        assert e.status_code == 400 and "non ci sono lavori" in e.detail
    NOTICES.clear()
    r = await server.unlink_client_updates("s_bagno", me)
    assert r["status"] == "none" and any(c == 950 for c, _t in NOTICES)
    assert not await ctg.handle(CUpd("ciao"))
    try:
        await server.send_client_update_now("s_bagno", me); assert False
    except HTTPException as e:
        assert e.status_code == 400
    print("ALL OK")

asyncio.run(main())
