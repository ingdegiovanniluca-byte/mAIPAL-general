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




import embeddings as emb
async def zeros(ts): return [None for _ in ts]
emb.embed_texts = zeros
async def no_kb(*a, **k): return []
server.retrieve_kb = no_kb
made = []
class G:
    @staticmethod
    async def get_credentials(db_, uid): return "creds"
    @staticmethod
    async def ensure_maipal_folder(db_, uid, creds): return "root"
    @staticmethod
    def find_or_create_subfolder_sync(creds, parent, name):
        if name == "Lenta":
            import time; time.sleep(3)
        made.append(name); return "fid_" + name
server.gi.get_credentials = G.get_credentials
server.gi.ensure_maipal_folder = G.ensure_maipal_folder
server.gi.find_or_create_subfolder_sync = G.find_or_create_subfolder_sync
db.integrations.docs.append({"user_id": "u1", "provider": "google"})
async def interp(text, ctx="", user_id=None, channel="web"):
    interp.last = text
    return {"name": "Clienti", "fields": [{"label": "Nome", "type": "text"}], "items": []}
server.lu.interpret_list_creation = interp
async def main():
    u = server.User(**U)
    # 1) Salva: new list + its folder
    r = await server._create_list_from_text(u, "crea una lista Clienti e crea la relativa cartella su drive")
    print(r["message"]); print("text read for the list:", interp.last)
    assert r["status"] == "ok" and made == ["Clienti"] and "cartella" not in interp.last.lower()
    coll = db.collections.docs[0]
    assert coll["drive_folders"]["u1"]["links"]["google"] == "https://drive.google.com/drive/folders/fid_Clienti"
    # 2) the API shows only the caller's folder
    g = await server.get_collection(coll["id"], u)
    assert g["drive_folder"]["name"] == "Clienti" and "drive_folders" not in g
    # 3) the button: idempotent
    r2 = await server.create_list_folder(coll["id"], u)
    assert made == ["Clienti"], made
    # 4) existing list, from the list editor
    db.collections.docs.append({"id": "c2", "user_id": "u1", "name": "Spesa", "fields": [{"key": "p", "label": "Prodotto"}]})
    r3 = await server._execute_list_update(u, "crea la cartella su drive per la lista della spesa")
    print(r3["message"]); assert r3["status"] == "ok" and made[-1] == "Spesa"
    # 5) "crea la cartella della lista Clienti" read as a new list -> the existing one gets it (already has one)
    async def interp2(text, ctx="", user_id=None, channel="web"): return {"name": "Clienti", "fields": [{"label": "Nome", "type": "text"}], "items": []}
    server.lu.interpret_list_creation = interp2
    r4 = await server._create_list_from_text(u, "crea la cartella della lista Clienti")
    print(r4["message"]); assert r4["status"] == "ok" and r4.get("folder_only")
    # 6) no storage connected -> clear message, list still created
    db.integrations.docs.clear()
    async def interp3(text, ctx="", user_id=None, channel="web"): return {"name": "Fornitori", "fields": [{"label": "Nome", "type": "text"}], "items": []}
    server.lu.interpret_list_creation = interp3
    r5 = await server._create_list_from_text(u, "crea la lista fornitori con la sua cartella su drive")
    print(r5["message"]); assert r5["status"] == "ok" and "Nessun archivio collegato" in r5["message"]
    # 7) a plain list request makes no folder
    n = len(made)
    server.lu.interpret_list_creation = interp3
    db.collections.docs = [c for c in db.collections.docs if c["name"] != "Fornitori"]
    r6 = await server._create_list_from_text(u, "crea la lista fornitori con nome e telefono")
    assert r6["status"] == "ok" and len(made) == n and "cartella" not in r6["message"]
    # 8) Drive that doesn't answer: the list is made, the reply comes back with the reason
    db.integrations.docs.append({"user_id": "u1", "provider": "google"})
    server.LIST_FOLDER_TIMEOUT = 1
    async def interp4(text, ctx="", user_id=None, channel="web"): return {"name": "Lenta", "fields": [{"label": "Nome", "type": "text"}], "items": []}
    server.lu.interpret_list_creation = interp4
    import time; t0 = time.time()
    r7 = await server._create_list_from_text(u, "crea la lista lenta e la sua cartella su drive")
    print(r7["message"], round(time.time() - t0, 1)); assert r7["status"] == "ok" and "non ha risposto in tempo" in r7["message"] and time.time() - t0 < 2.5
    print("ALL OK")
asyncio.run(main())
