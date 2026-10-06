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
X = {"meta": None}
async def fake_extract(text, user_id, channel="web"): return X["meta"]
server._extract_task_meta = fake_extract
today = datetime.now(server.LOCAL_TZ).date().isoformat()
async def main():
    A = server._apply_task_todo_turn
    # a) "crea un to-do" but the model put a date -> still a to-do
    line = await A("u1", 'crea un to-do chiamato "modifiche progetto maipal"', {"title": "Modifiche progetto mAIPAL", "due_date": today}, "c1", "Fatto, l'ho creato.")
    print("a:", line); assert line.startswith("✅ Salvato nei To-Do") and len(db.todos.docs) == 1 and not db.tasks.docs
    # c) "non lo vedo, ricrealo" -> no duplicate, says where it is
    line = await A("u1", "non lo vedo, ricrealo", {"title": "Modifiche progetto mAIPAL"}, "c1", "L'ho ricreato.")
    print("c:", line); assert "È salvato nei To-Do" in line and len(db.todos.docs) == 1
    # e) another one in the same chat
    line = await A("u1", "crea anche un to-do chiamato comprare toner", {"title": "Comprare toner"}, "c1", "Fatto.")
    print("e:", line); assert len(db.todos.docs) == 2
    # b) the model forgot META: read from the request
    X["meta"] = {"title": "Chiamare il commercialista"}
    line = await A("u1", "crea un to-do: chiamare il commercialista", None, "c2", "Ho creato il to-do.")
    print("b:", line); assert "Chiamare il commercialista" in line and len(db.todos.docs) == 3
    # f) nothing understood, the model claims -> it says so
    X["meta"] = None
    line = await A("u1", "crealo", None, "c3", "Fatto, l'ho creato!")
    print("f:", line); assert line.startswith("⚠️")
    # g) a plain question: no META, no claim -> nothing appended
    assert await A("u1", "come funziona?", None, "c4", "Puoi dirmi cosa salvare.") == ""
    # d) saved earlier as a task by mistake, then "ricrea il to-do" -> moved
    await server._create_task_or_todo("u1", {"title": "Revisione sito", "due_date": today}, "c5")
    line = await A("u1", "ricrea il to-do revisione sito", {"title": "Revisione sito"}, "c5", "Ricreato.")
    print("d:", line); assert line.startswith("✅ Spostato nei To-Do") and not db.tasks.docs
    # h) a task with a date stays a task
    line = await A("u1", "ricordami di chiamare Marco domani alle 10", {"title": "Chiamare Marco", "due_date": today, "due_time": "10:00"}, "c6", "Ok.")
    print("h:", line); assert line.startswith("📌 Salvato nei Task")
    # i) "crea un task" without a date -> to-do, and says why
    line = await A("u1", "crea un task: ordinare la carta", {"title": "Ordinare la carta"}, "c7", "Fatto.")
    print("i:", line); assert "Senza una data" in line
    print("ALL OK")
asyncio.run(main())
