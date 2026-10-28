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

import push_notify as pn
PUSHED = []
def fake_send_one(sub, payload, private_pem, claims_sub):
    import json as _j
    assert private_pem.startswith("-----BEGIN") and claims_sub.startswith("mailto:")
    PUSHED.append((sub["endpoint"], _j.loads(payload)))
pn._send_one = fake_send_one
SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "BPk", "auth": "xyz"}}

async def pushed_more_than(n, wait=3.0):
    """the push runs in a thread: wait for it (or for nothing to come)"""
    for _ in range(int(wait / 0.05)):
        if len(PUSHED) > n:
            return True
        await asyncio.sleep(0.05)
    return False

class Req:
    headers = {"user-agent": "Mozilla/5.0 (iPhone)"}

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})

    # 1) the device: key, subscribe, status, unsubscribe
    k = await server.push_public_key(me)
    assert len(k["public_key"]) > 80 and (await server.push_public_key(me))["public_key"] == k["public_key"]
    try:
        await server.push_subscribe(server.PushSubscribePayload(subscription={"endpoint": "x"}), Req(), me); assert False
    except server.HTTPException as e:
        assert e.status_code == 400
    r = await server.push_subscribe(server.PushSubscribePayload(subscription=SUB), Req(), me)
    assert r["devices"] == 1
    assert (await server.push_status(server.PushEndpointPayload(endpoint=SUB["endpoint"]), me))["subscribed"]
    await server.push_subscribe(server.PushSubscribePayload(subscription=SUB), Req(), me)   # again: still one device
    assert len(db.push_subscriptions.docs) == 1
    assert (await server.push_test(me))["sent"] == 1 and PUSHED[-1][1]["title"] == "🔔 mAIPAL"

    # 2) a collaborator writes in the diary -> the owner's device; the owner's own entries don't
    n = len(PUSHED)
    jl.interpret = said(hours=[{"who": "io", "hours": 3}], problems=["manca il miscelatore"])
    await server._save_job_log(me, "io 3 ore", commessa_id="s_bagno")
    assert not await pushed_more_than(n, wait=1.0)
    author = {"id": "k1", "first_name": "Gino", "name": "Gino Neri", "company": ""}
    r = await server._save_job_log(me, "montato il lavabo, 3 ore, manca il miscelatore", commessa_id="s_bagno", channel="telegram", author=author)
    assert await pushed_more_than(n)
    ep, msg = PUSHED[-1]
    print(msg)
    assert len(PUSHED) == n + 1 and ep == SUB["endpoint"] and msg["title"] == "📒 Gino Neri · Bagno"
    assert "🕒 Gino 3 h da approvare" in msg["body"] and "manca il miscelatore" in msg["body"] and msg["url"] == "/dashboard/journal?commessa=s_bagno"
    # the outcome is kept, for Impostazioni > Notifiche
    for _ in range(40):
        last = (await server.push_status(server.PushEndpointPayload(endpoint=SUB["endpoint"]), me))["last"]
        if last and last["title"] == "📒 Gino Neri · Bagno":
            break
        await asyncio.sleep(0.05)
    assert last["title"] == "📒 Gino Neri · Bagno" and last["devices"] == 1 and last["sent"] == 1 and not last["errors"], last

    # 3) a task's reminder: on the device, once (a Telegram retry doesn't repeat it)
    now = datetime.now(timezone.utc)
    due = (now + timedelta(minutes=10)).astimezone(ZoneInfo("Europe/Rome"))
    db.tasks.docs.append({"id": "t1", "user_id": "u1", "title": "Chiamare il cliente", "notes": "per il preventivo", "reminder_enabled": True,
                          "reminder_msg_sent": False, "reminder_offset_minutes": 15, "due_date": due.date().isoformat(), "due_time": due.strftime("%H:%M")})
    n = len(PUSHED)
    await server._exact_reminders_tick(now)
    t = next(x for x in db.tasks.docs if x["id"] == "t1")
    assert len(PUSHED) == n + 1 and PUSHED[-1][1]["title"] == "🔔 Chiamare il cliente" and PUSHED[-1][1]["url"] == "/dashboard/tasks", PUSHED[-1]
    assert "Tra 10 minuti" in PUSHED[-1][1]["body"] or "Tra 9 minuti" in PUSHED[-1][1]["body"]
    if not t.get("reminder_msg_sent"):   # the fake bot token can't reach Telegram: retried next minute, no second push
        await server._exact_reminders_tick(now + timedelta(minutes=1))
        assert len(PUSHED) == n + 1
    # without Telegram: the push alone, and the reminder is done
    db.users.docs[0]["telegram_chat_id"] = None
    db.tasks.docs.append({"id": "t2", "user_id": "u1", "title": "Ritirare il materiale", "reminder_enabled": True, "reminder_msg_sent": False,
                          "due_date": due.date().isoformat(), "due_time": due.strftime("%H:%M")})
    await server._exact_reminders_tick(now)
    assert PUSHED[-1][1]["title"] == "🔔 Ritirare il materiale" and next(x for x in db.tasks.docs if x["id"] == "t2")["reminder_msg_sent"]
    # not yet due: nothing
    db.tasks.docs.append({"id": "t3", "user_id": "u1", "title": "Più tardi", "reminder_enabled": True, "reminder_msg_sent": False,
                          "due_date": due.date().isoformat(), "due_time": (due + timedelta(hours=2)).strftime("%H:%M") if due.hour < 21 else due.strftime("%H:%M"),
                          "reminder_offset_minutes": 15 if due.hour < 21 else 0})
    n = len(PUSHED)
    if due.hour < 21:
        await server._exact_reminders_tick(now)
        assert len(PUSHED) == n

    # a device the push service refuses: said; one that is gone: removed and said
    class Gone(Exception):
        def __init__(s, code, text):
            super().__init__(text); s.response = type("R", (), {"status_code": code, "text": text})()
    def refusing(sub, payload, private_pem, claims_sub):
        raise Gone(403, "BadJwtToken")
    pn._send_one = refusing
    try:
        await server.push_test(me); assert False
    except server.HTTPException as e:
        assert e.status_code == 400 and "403" in e.detail and "BadJwtToken" in e.detail, e.detail
    def gone(sub, payload, private_pem, claims_sub):
        raise Gone(410, "expired")
    pn._send_one = gone
    try:
        await server.push_test(me); assert False
    except server.HTTPException as e:
        assert "non è più iscritto" in e.detail, e.detail
    assert not db.push_subscriptions.docs
    st = await server.push_status(server.PushEndpointPayload(endpoint=SUB["endpoint"]), me)
    assert not st["subscribed"] and st["last"]["sent"] == 0
    await server.push_subscribe(server.PushSubscribePayload(subscription=SUB), Req(), me)
    pn._send_one = fake_send_one

    # 4) the device turned off: nothing more
    await server.push_unsubscribe(server.PushEndpointPayload(endpoint=SUB["endpoint"]), me)
    assert not db.push_subscriptions.docs
    try:
        await server.push_test(me); assert False
    except server.HTTPException as e:
        assert e.status_code == 400
    print("ALL OK")
asyncio.run(main())
