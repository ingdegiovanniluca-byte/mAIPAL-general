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

import list_updates as lu
CATALOGS = []
def interp_add_commessa(title, client):
    async def f(text, catalog, kb_context="", user_id=None, channel="web"):
        CATALOGS.append([c["name"] for c in catalog])
        cid = next(c["id"] for c in catalog if c["name"] == "Clienti")
        return {"op": "add_sub_item", "collection_id": cid, "item_query": client, "sub_item_query": "",
                "fields": {"titolo": title}, "sub_items": [], "items": []}
    return f

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collections.docs.append({"id": "l_spesa", "user_id": "u1", "name": "Spesa", "visibility": "private", "fields": [{"key": "nome", "label": "Nome"}], "sub_item_fields": []})
    names = [c["name"] for c in db.collections.docs]

    # 1) "crea una commessa..." is an edit of Clienti, decided without asking the model
    import openai as _oa
    class Boom:
        def __init__(self, *a, **k): raise AssertionError("the model must not be asked")
    real = _oa.AsyncOpenAI; _oa.AsyncOpenAI = Boom
    for t in ("Crea una commessa nuova Bagno per il cliente Mario Rossi", "nuovo cantiere dai Rossi: rifacimento tetto"):
        assert await lu.classify_save_intent(t, names) == "list_update", t
    _oa.AsyncOpenAI = real
    assert not lu.about_jobs("crea una commessa", ["Spesa"])            # no Clienti list: nothing special
    assert not lu.about_jobs("crea una lista della spesa", names)

    # 2) the list editor only sees Clienti, the commessa goes under the client, in corso from today
    lu.interpret_list_request = interp_add_commessa("Bagno", "Mario Rossi")
    n_colls = len(db.collections.docs)
    r = await server._execute_list_update(me, "Crea una commessa nuova Bagno per il cliente Mario Rossi")
    assert r["status"] == "ok" and CATALOGS[-1] == ["Clienti"], (r, CATALOGS)
    sub = next(x for x in db.collection_sub_items.docs if x["item_id"] == "c_rossi")
    assert sub["data"]["titolo"] == "Bagno" and sub["data"]["stato"] == "in corso" and sub["data"]["data_inizio"] == jl.today_local().isoformat()
    assert len(db.collections.docs) == n_colls

    # 3) even if it reaches "create a list" (Telegram, an old app): no new list, the commessa under the client
    lu.interpret_list_request = interp_add_commessa("Cucina", "Mario Rossi")
    r = await server._create_list_from_text(me, "crea una nuova commessa Cucina per Mario Rossi")
    assert r["status"] == "ok" and len(db.collections.docs) == n_colls
    assert any(x["data"].get("titolo") == "Cucina" and x["item_id"] == "c_rossi" for x in db.collection_sub_items.docs)
    # a state said stays
    lu.interpret_list_request = interp_add_commessa("Tetto", "Mario Rossi")
    async def with_state(text, catalog, kb_context="", user_id=None, channel="web"):
        return {"op": "add_sub_item", "collection_id": cl["id"], "item_query": "Mario Rossi", "sub_item_query": "",
                "fields": {"titolo": "Tetto", "stato": "preventivo"}, "sub_items": [], "items": []}
    lu.interpret_list_request = with_state
    await server._execute_list_update(me, "aggiungi la commessa Tetto in preventivo ai Rossi")
    assert next(x for x in db.collection_sub_items.docs if x["data"].get("titolo") == "Tetto")["data"]["stato"] == "preventivo"
    # other lists: as before
    assert not lu.about_jobs("aggiungi il latte alla spesa", names)
    print("ALL OK")
asyncio.run(main())
