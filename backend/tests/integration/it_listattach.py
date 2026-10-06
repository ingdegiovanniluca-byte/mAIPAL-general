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


async def fake_retrieve(*a, **k): return []
server.retrieve_kb = fake_retrieve
async def fake_interp(text, ctx="", user_id=None, channel="web"):
    return {"name": "Spesa", "fields": [{"label": "Prodotto", "type": "text"}, {"label": "Quantità", "type": "number"}],
            "items": [{"Prodotto": "Latte", "Quantità": 2}, {"Prodotto": "Pane"}, {"prodotto": "latte"}, {"Quantità": 3}]}
server.lu.interpret_list_creation = fake_interp

async def main():
    u = server.User(**U)
    db.collections.docs.append({"id": "cs", "user_id": "u1", "name": "Spesa", "fields": [{"key": "prodotto", "label": "Prodotto", "type": "text"}], "sub_item_fields": [], "visibility": "private"})
    db.kb_chunks.docs.append({"chunk_id": "k1", "user_id": "u1", "doc_id": "dimg", "chunk_index": 0, "title": "scontrino.jpg", "text": "SACCHI PICCOLI\nSPAZZOLE\nBURRO CACAO\nYOGURT"})
    seen = {}
    async def fake_interpret(text, catalog, kb_context="", user_id=None, channel="web"):
        seen["ctx"] = kb_context
        return {"op": "bulk_add_items", "collection_id": "cs", "item_query": "", "sub_item_query": "", "fields": {}, "sub_items": [],
                "items": [{"prodotto": x} for x in ["Sacchi piccoli", "Spazzole", "Burro cacao", "Yogurt"]]}
    server.lu.interpret_list_request = fake_interpret
    res = await server._execute_list_update(u, "Aggiungi questi campi alla lista della spesa", attachment_doc_ids=["dimg"])
    print("ctx has receipt:", "BURRO CACAO" in seen["ctx"], "| status:", res.get("status"), res.get("message", "")[:120])
    if str(res.get("status", "")).startswith("confirm"):
        res = await server._execute_list_update(u, "Aggiungi questi campi alla lista della spesa", op=res["op"], collection_id=res["collection_id"], new_items=res["items"], confirm=True)
        print("after confirm:", res.get("status"), res.get("message", "")[:120])
    print("items:", [i["data"] for i in db.collection_items.docs])
    assert "BURRO CACAO" in seen["ctx"] and len(db.collection_items.docs) == 4
    # follow-up message in the same chat, no attachment: the conversation's photo is the context
    db.conversations.docs.append({"conv_id": "cv1", "user_id": "u1", "action": "info_upload", "messages": [{"role": "user", "content": "Salva\n📎 scontrino.jpg"}], "attachment_doc_ids": ["dimg"]})
    seen.clear()
    await server._execute_list_update(u, "Aggiungili alla lista della spesa", conv_id="cv1")
    print("conv ctx has receipt:", "BURRO CACAO" in seen.get("ctx", ""))
    assert "BURRO CACAO" in seen["ctx"]
    kind = await server.lu.classify_save_intent("Salva questi campi nella lista della spesa", ["Spesa"])
    print("classified:", kind); assert kind == "list_update"
    print("ALL OK")
asyncio.run(main())
