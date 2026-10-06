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
    async def insert_many(s, ds): s.docs.extend(copy.deepcopy(d) for d in ds)
    async def update_many(s, q, u):
        n = 0
        for d in s.docs:
            if _match(d, q): d.update(u.get("$set", {})); n += 1
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
import json as J
U = {"user_id": "u1", "email": "a@b.it", "name": "Luca"}
db.users.docs.append(U)




from fastapi import HTTPException
async def no_sharing(colls, current): return colls
server._add_sharing_info = no_sharing
class Agg:
    def __init__(s, out): s.out = out
    async def to_list(s, n): return s.out
db.collection_items.aggregate = lambda pipe: Agg([])

async def main():
    u = server.User(**U)
    # 1) turning the vertical on: a team (owner) and the Clienti list with Commesse
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), u)
    assert me.org_id and me.org_role == "owner" and len(db.organizations.docs) == 1
    cl = [c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti"]
    assert len(cl) == 1 and cl[0]["name"] == "Clienti" and cl[0]["visibility"] == "org" and cl[0]["org_id"] == me.org_id
    assert [f["key"] for f in cl[0]["fields"]][:2] == ["nome", "telefono"]
    sub = {f["key"]: f for f in cl[0]["sub_item_fields"]}
    assert sub["stato"]["options"] == ["preventivo", "in corso", "sospesa", "chiusa"] and "titolo" in sub
    # idempotent
    await server._apply_vertical(me, "artigiano")
    assert len([c for c in db.collections.docs if c.get("system_key")]) == 1 and len(db.organizations.docs) == 1
    # 2) protections
    try:
        await server.delete_collection(cl[0]["id"], me); assert False
    except HTTPException as he:
        print(he.detail); assert he.status_code == 400
    fields = [server.CollectionFieldDef(**f) for f in cl[0]["fields"] if f["key"] != "telefono"]
    try:
        await server.update_collection(cl[0]["id"], server.CollectionUpdatePayload(fields=fields), me); assert False
    except HTTPException as he:
        print(he.detail); assert "Telefono" in he.detail
    more = [server.CollectionFieldDef(**f) for f in cl[0]["fields"]] + [server.CollectionFieldDef(key="", label="Partita IVA", type="text")]
    out = await server.update_collection(cl[0]["id"], server.CollectionUpdatePayload(fields=more), me)
    assert any(f["label"] == "Partita IVA" and f["key"] == "partita_iva" for f in out["fields"])
    async def fake_interpret(text, catalog, now_local, linked, user_id=None, channel="web"):
        return {"supported": True, "kind": "list_delete", "list_name": "Clienti", "schedule": {"freq": "now"}}
    server.sa.interpret_command = fake_interpret
    d = await server._build_scheduled_draft(me, "elimina la lista clienti")
    print(d["message"]); assert d["status"] == "unsupported"

    # 3) another user who already had a "Clienti" list: adopted, nothing lost
    U2 = {"user_id": "u2", "email": "b@b.it", "name": "Gino Bianchi"}
    db.users.docs.append(U2)
    db.collections.docs.append({"id": "old", "user_id": "u2", "name": "clienti", "visibility": "private",
        "fields": [{"key": "cliente", "label": "Cliente", "type": "text"}, {"key": "tel", "label": "telefono", "type": "text"}],
        "sub_item_fields": [{"key": "d", "label": "Descrizione", "type": "text"}, {"key": "data_inizio", "label": "Data inizio", "type": "date"}]})
    db.collection_items.docs.append({"id": "it1", "collection_id": "old", "data": {"cliente": "Rossi", "tel": "333"}})
    u2 = server.User(**U2)
    await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), u2)
    old = next(c for c in db.collections.docs if c["id"] == "old")
    print([(f["label"], f["key"]) for f in old["fields"]]); print([(f["label"], f["key"]) for f in old["sub_item_fields"]])
    assert old["system_key"] == "artigiano_clienti" and old["system_map"]["nome"] == "cliente" and old["system_map"]["telefono"] == "tel"
    assert old["system_sub_map"]["titolo"] == "d" and old["system_sub_map"]["data_inizio"] == "data_inizio"
    assert {"Email", "Indirizzo", "Note"} <= {f["label"] for f in old["fields"]}
    assert {"Stato", "Data fine", "Indirizzo cantiere"} <= {f["label"] for f in old["sub_item_fields"]}
    assert db.collection_items.docs[-1]["data"] == {"cliente": "Rossi", "tel": "333"}
    assert len([c for c in db.collections.docs if c.get("user_id") == "u2"]) == 1

    # 4) already on the vertical but without the list (set before this version): made on the next lists load
    U3 = {"user_id": "u3", "email": "c@b.it", "name": "Ugo", "business_vertical": "artigiano"}
    db.users.docs.append(U3)
    await server.list_collections(server.User(**U3))
    assert any(c.get("system_key") and c["user_id"] == "u3" for c in db.collections.docs)
    # 5) the other verticals / no vertical: no Clienti list, no team
    U4 = {"user_id": "u4", "email": "d@b.it", "name": "Ada"}
    db.users.docs.append(U4)
    await server.update_profile(server.ProfilePatch(business_vertical="fitness"), server.User(**U4))
    assert not any(c.get("user_id") == "u4" for c in db.collections.docs) and len(db.organizations.docs) == 3
    print("ALL OK")
asyncio.run(main())
