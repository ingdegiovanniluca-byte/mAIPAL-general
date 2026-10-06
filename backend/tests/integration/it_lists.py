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
                if op == "$in" and val not in arg: return False
                if op == "$nin" and val in arg: return False
                if op == "$ne" and val == arg: return False
                if op == "$gte" and (val is None or val < arg): return False
                if op == "$gt" and (val is None or val <= arg): return False
                if op == "$lte" and (val is None or val > arg): return False
                if op == "$lt" and (val is None or val >= arg): return False
                if op == "$exists" and ((k in doc) != arg): return False
        elif isinstance(val, list) and not isinstance(v, list):
            if v not in val: return False
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
                for k, v in u.get("$inc", {}).items(): d[k] = (d.get(k) or 0) + v
                for k, v in u.get("$addToSet", {}).items():
                    arr = d.setdefault(k, [])
                    for x in (v["$each"] if isinstance(v, dict) and "$each" in v else [v]):
                        if x not in arr: arr.append(x)
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
    def aggregate(s, pipe):
        m = pipe[0]["$match"]; g = pipe[1]["$group"]["_id"].lstrip("$")
        out = {}
        for d in s.docs:
            if _match(d, m): out[d.get(g)] = out.get(d.get(g), 0) + 1
        return Cur([{"_id": k, "n": n} for k, n in out.items()])
    async def bulk_write(s, ops):
        for o in ops: await s.update_one(o._filter, o._doc)
    async def insert_many(s, ds): s.docs.extend(copy.deepcopy(d) for d in ds)
    async def update_many(s, q, u):
        n = 0
        for d in s.docs:
            if _match(d, q):
                d.update(u.get("$set", {})); n += 1
                for k, v in u.get("$addToSet", {}).items():
                    arr = d.setdefault(k, [])
                    for x in (v["$each"] if isinstance(v, dict) and "$each" in v else [v]):
                        if x not in arr: arr.append(x)
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
import json as J
from fastapi import HTTPException
users = [{"user_id": "u1", "email": "l@x.it", "name": "Luca Bianchi", "org_id": "o1"},
         {"user_id": "u2", "email": "m@x.it", "name": "Mario Rossi", "org_id": "o1", "telegram_chat_id": 222},
         {"user_id": "u3", "email": "g@x.it", "name": "Giulia Verdi", "org_id": "o1"},
         {"user_id": "u4", "email": "x@x.it", "name": "Esterno", "org_id": "o2"}]
db.users.docs += [dict(u) for u in users]
sent = []
async def fake_send(chat_id, text): sent.append((chat_id, text)); return True
server._send_telegram_text = fake_send
U = {u["user_id"]: server.User(**u) for u in users}
F = [server.CollectionFieldDef(key="nome", label="Nome")]

async def names(uid):
    return [(c["name"], c["is_owner"], c["owner"]["name"], [x["name"] for x in c["shared_with_users"]], c["visibility"]) for c in await server.list_collections(U[uid])]

async def expect_err(coro, code):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == code, (e.status_code, e.detail); return e.detail
    raise AssertionError("no error")

async def main():
    spesa = await server.create_collection(server.CollectionCreatePayload(name="Spesa", fields=F, shared_with=["u2", "u4", "u1"]), U["u1"])
    print("create shared_with (u4 other team and self dropped):", spesa["shared_with"], "| telegram:", sent)
    priv = await server.create_collection(server.CollectionCreatePayload(name="Privata", fields=F), U["u1"])
    print("u1:", await names("u1")); print("u2:", await names("u2")); print("u3:", await names("u3")); print("u4:", await names("u4"))
    # u2 edits content and structure
    it = await server.create_collection_item(spesa["id"], server.CollectionItemPayload(data={"nome": "Latte"}), U["u2"])
    await server.update_collection_item(spesa["id"], it["id"], server.CollectionItemPayload(data={"nome": "Latte intero"}), U["u2"])
    await server.update_collection(spesa["id"], server.CollectionUpdatePayload(name="Spesa casa"), U["u2"])
    print("u1 sees items:", [i["data"] for i in await server.list_collection_items(spesa["id"], U["u1"])], "| owner still:", (await server.get_collection(spesa["id"], U["u2"]))["owner"])
    # u2 cannot delete / reshare; u3 cannot see
    print("u2 delete ->", await expect_err(server.delete_collection(spesa["id"], U["u2"]), 403))
    print("u2 sharing ->", await expect_err(server.set_collection_sharing(spesa["id"], server.CollectionSharingPayload(visibility="org"), U["u2"]), 403))
    print("u2 visibility ->", await expect_err(server.update_collection(spesa["id"], server.CollectionUpdatePayload(visibility="org"), U["u2"]), 403))
    await expect_err(server.list_collection_items(spesa["id"], U["u3"]), 404)
    await expect_err(server.list_collection_items(priv["id"], U["u2"]), 404)
    # owner shares with whole team
    sent.clear()
    r = await server.set_collection_sharing(priv["id"], server.CollectionSharingPayload(visibility="org"), U["u1"])
    print("team share:", r["visibility"], "| u3 lists:", await names("u3"), "| tg:", len(sent))
    # per-user order: u2 reorders, u1 unaffected
    await server.reorder_collections(server.CollectionReorderPayload(ordered_ids=[priv["id"], spesa["id"]]), U["u2"])
    print("u2 order:", [c[0] for c in await names("u2")], "| u1 order:", [c[0] for c in await names("u1")])
    # u3 leaves team -> loses access
    db.users.docs[[u["user_id"] for u in db.users.docs].index("u2")]["org_id"] = None
    U["u2"] = server.User(**{**users[1], "org_id": None})
    print("u2 after leaving team:", await names("u2"))
    # list update via chat by a team-mate sees shared list
    print("search lists for u3:", [c["name"] for c in await db.collections.find(server._lists_query(U["u3"]), {"_id": 0}).to_list(50)])
    # owner unshares
    await server.set_collection_sharing(spesa["id"], server.CollectionSharingPayload(visibility="private", user_ids=[]), U["u1"])
    print("u1 after unshare:", await names("u1"))
    await server.delete_collection(spesa["id"], U["u1"])
    print("ALL OK")
asyncio.run(main())
