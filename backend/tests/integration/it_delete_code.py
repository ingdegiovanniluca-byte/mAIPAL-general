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

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_items.docs.append({"id": "c_verdi", "collection_id": cl["id"], "data": {"nome": "Anna Verdi"}})
    for i, cid, t in (("s_bagno", "c_rossi", "Bagno"), ("s_cucina", "c_rossi", "Cucina"), ("s_box", "c_verdi", "Box")):
        db.collection_sub_items.docs.append({"id": i, "collection_id": cl["id"], "item_id": cid, "data": {"titolo": t, "stato": "in corso"}})
    jl.interpret = said(hours=[{"who": "io", "hours": 3}])
    await server._save_job_log(me, "3 ore sul bagno", commessa_id="s_bagno")
    await server._save_job_log(me, "altre 3 ore", commessa_id="s_bagno")
    url_args = (cl["id"], "c_rossi", "s_bagno")
    def code_of(msg):
        import re as _re
        return _re.search(r"\*(\d{6})\*", msg).group(1)

    # 1) no code, no deletion
    for bad in (None, "123456"):
        try:
            await server.delete_sub_item(*url_args, code=bad, current=me); assert False
        except server.HTTPException as e:
            assert e.status_code == 403 and "codice" in e.detail.lower()
    assert any(x["id"] == "s_bagno" for x in db.collection_sub_items.docs)

    # 2) the code on Telegram: what goes with it, valid for that commessa only
    r = await server.request_delete_code(server.DeleteCodePayload(collection_id=cl["id"], item_id="c_rossi", sub_id="s_bagno"), me)
    msg = NOTICES[-1][1]
    print(msg)
    assert r["sent"] and r["entries"] == 2 and NOTICES[-1][0] == 77 and "la commessa «Bagno» di Mario Rossi" in msg and "il diario (2 voci)" in msg
    code = code_of(msg)
    try:
        await server.delete_sub_item(cl["id"], "c_rossi", "s_cucina", code=code, current=me); assert False   # another commessa
    except server.HTTPException as e:
        assert e.status_code == 403
    # wrong code: tries counted; the fifth wrong one burns it
    wrong = "000000" if code != "000000" else "111111"
    for left in (4, 3):
        try:
            await server.delete_sub_item(*url_args, code=wrong, current=me); assert False
        except server.HTTPException as e:
            assert f"restano {left} tentativi" in e.detail, e.detail
    # the right one deletes the commessa and its diary, once
    assert (await server.delete_sub_item(*url_args, code=code, current=me))["ok"]
    assert not any(x["id"] == "s_bagno" for x in db.collection_sub_items.docs)
    assert not any(x["commessa_id"] == "s_bagno" for x in db.job_logs.docs)
    try:
        await server.delete_sub_item(cl["id"], "c_rossi", "s_cucina", code=code, current=me); assert False   # used up
    except server.HTTPException as e:
        assert e.status_code == 403

    # 3) five wrong codes: a new one is needed; expired: the same
    await server.request_delete_code(server.DeleteCodePayload(collection_id=cl["id"], item_id="c_rossi", sub_id="s_cucina"), me)
    code = code_of(NOTICES[-1][1]); wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        try:
            await server.delete_sub_item(cl["id"], "c_rossi", "s_cucina", code=wrong, current=me)
        except server.HTTPException as e:
            last = e.detail
    assert "troppe volte" in last
    try:
        await server.delete_sub_item(cl["id"], "c_rossi", "s_cucina", code=code, current=me); assert False
    except server.HTTPException as e:
        assert e.status_code == 403
    await server.request_delete_code(server.DeleteCodePayload(collection_id=cl["id"], item_id="c_rossi", sub_id="s_cucina"), me)
    code = code_of(NOTICES[-1][1])
    db.delete_codes.docs[-1]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    try:
        await server.delete_sub_item(cl["id"], "c_rossi", "s_cucina", code=code, current=me); assert False
    except server.HTTPException as e:
        assert "scaduto" in e.detail

    # 4) a whole client: its commesse and their diaries
    jl.interpret = said(hours=[{"who": "io", "hours": 1}])
    await server._save_job_log(me, "1 ora", commessa_id="s_cucina")
    r = await server.request_delete_code(server.DeleteCodePayload(collection_id=cl["id"], item_id="c_rossi"), me)
    assert "il cliente «Mario Rossi» con la sua commessa" in NOTICES[-1][1] and r["entries"] == 1
    assert (await server.delete_collection_item(cl["id"], "c_rossi", code=code_of(NOTICES[-1][1]), current=me))["ok"]
    assert not any(x["id"] == "c_rossi" for x in db.collection_items.docs) and not any(x.get("commessa_id") == "s_cucina" for x in db.job_logs.docs)
    assert any(x["id"] == "s_box" for x in db.collection_sub_items.docs)

    # 5) Telegram not linked: asked to link it, nothing sent
    nolink = server.User(**{**U, "telegram_chat_id": None})
    n = len(NOTICES)
    try:
        await server.request_delete_code(server.DeleteCodePayload(collection_id=cl["id"], item_id="c_verdi", sub_id="s_box"), nolink); assert False
    except server.HTTPException as e:
        assert e.status_code == 409 and "Collegamenti" in e.detail and len(NOTICES) == n

    # 6) from the chat: clients and commesse are never deleted
    for op, extra in (("delete_sub_item", {"sub_item_query": "Box"}), ("delete_item", {}), ("clear_items", {}), ("clear_sub_items", {})):
        try:
            await server._execute_list_update(me, "elimina", op=op, collection_id=cl["id"], item_query="Anna Verdi", **extra); assert False
        except server.HTTPException as e:
            assert e.status_code == 400 and "codice di conferma su Telegram" in e.detail, (op, e.detail)
        except TypeError as e:
            print("signature", e); raise
    assert any(x["id"] == "s_box" for x in db.collection_sub_items.docs) and any(x["id"] == "c_verdi" for x in db.collection_items.docs)

    # 7) other lists: deleting stays as it was (no code)
    db.collections.docs.append({"id": "l_spesa", "user_id": "u1", "name": "Spesa", "visibility": "private", "fields": [], "sub_item_fields": []})
    db.collection_items.docs.append({"id": "i_latte", "collection_id": "l_spesa", "data": {"nome": "latte"}})
    assert (await server.delete_collection_item("l_spesa", "i_latte", current=me))["ok"]
    print("ALL OK")
asyncio.run(main())
