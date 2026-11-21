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
    async def no_model(*a, **k): return None          # offline: the context and the rules decide, else the fallback
    server.chat_router.by_model = no_model
    server.ROUTER_SHADOW = True

    async def done():
        for _ in range(40):
            await asyncio.sleep(0.01)

    # 1) the app: a message sent to Cerca that is a reminder - the router would send it to Task (kept, not done)
    r = await server.router_shadow(server.RouterShadowPayload(action="info_request", text="Ricordami di chiamare Rossi domani alle 9"), me)
    assert r == {"ok": True}
    await done()
    x = db.router_shadow.docs[-1]
    assert (x["chosen"], x["intent"], x["level"], x["agree"], x["channel"], x["vertical"]) == ("info_request", "task_todo", "rules", False, "web", "artigiano"), x
    assert x["text"].startswith("Ricordami") and x["at_dt"] and x["ms"] >= 0

    # 2) a short answer inside the conversation going on: the same agent, agreed
    await server.router_shadow(server.RouterShadowPayload(action="task_todo", text="alle 19", current_action="task_todo",
                                                          history=[{"role": "user", "content": "ricordami di chiamare Rossi"},
                                                                   {"role": "assistant", "content": "A che ora?"}]), me)
    await done()
    x = db.router_shadow.docs[-1]
    assert x["agree"] and x["follow_up"] and x["level"] == "context", x
    # all it saw is kept (to decide again later with a corrected router) and which version decided
    assert x["ctx"]["current_action"] == "task_todo" and x["ctx"]["history"][-1]["content"] == "A che ora?"
    assert x["router_version"] == server.chat_router.VERSION and len(x["router_version"]) == 8

    # 3) Telegram: next to its own classifier; its "journal" is the artigiano's diary
    tg._shadow({"user_id": "u1", "business_vertical": "artigiano"}, "Oggi 4 ore dai Rossi, posato il corrugato", "journal", None)
    await done()
    x = db.router_shadow.docs[-1]
    assert (x["channel"], x["chosen"], x["intent"], x["agree"]) == ("telegram", "job_log", "job_log", True), x

    # 3b) Telegram inside a conversation: the router sees its last messages (mAIPAL's question too), like the app
    db.conversations.docs.append({"conv_id": "cv_tg", "user_id": "u1", "messages": [
        {"role": "user", "content": "ricordami di chiamare Rossi"}, {"role": "assistant", "content": "A che ora te lo ricordo?"}]})
    tg._shadow({"user_id": "u1", "business_vertical": "artigiano"}, "alle 19", "task_todo",
               {"current_action": "task_todo", "current_conv_id": "cv_tg", "last_user_message": "ricordami di chiamare Rossi"})
    await done()
    x = db.router_shadow.docs[-1]
    assert x["channel"] == "telegram" and x["agree"] and x["level"] == "context" and x["ctx"].get("awaiting"), x
    assert [m["content"] for m in x["ctx"]["history"]] == ["ricordami di chiamare Rossi", "A che ora te lo ricordo?"] and "conv_id" not in x["ctx"]

    # 4) not recorded: empty, an agent the trade doesn't have, the shadow off
    n = len(db.router_shadow.docs)
    server.shadow_route("u1", "artigiano", "   ", "info_request")
    server.shadow_route("u1", "artigiano", "Ho visitato Fester", "vet_report")
    server.ROUTER_SHADOW = False
    server.shadow_route("u1", "artigiano", "Quante ore ha fatto Gino?", "info_request")
    await done()
    assert len(db.router_shadow.docs) == n
    server.ROUTER_SHADOW = True

    # 5) a router that breaks never breaks the chat: nothing kept, no error to the app
    async def boom(*a, **k): raise RuntimeError("down")
    real = server.chat_router.route
    server.chat_router.route = boom
    assert await server.router_shadow(server.RouterShadowPayload(action="info_request", text="Chi è in cantiere?"), me) == {"ok": True}
    await done()
    assert len(db.router_shadow.docs) == n
    server.chat_router.route = real
    print("ALL OK")


asyncio.run(main())
