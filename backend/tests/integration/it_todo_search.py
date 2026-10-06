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




import retrieval, time
from datetime import date
db.todos.docs += [
    {"id": "td1", "user_id": "u1", "title": "Modifiche progetto mAIPAL", "status": "da_fare", "created_at": "2026-10-05T10:00:00+00:00"},
    {"id": "td2", "user_id": "u1", "title": "Comprare toner", "status": "da_fare", "created_at": "2026-10-04T10:00:00+00:00"},
    {"id": "td3", "user_id": "u1", "title": "Preparare presentazione", "status": "in_corso", "completion_percent": 40, "created_at": "2026-10-03T10:00:00+00:00"},
    {"id": "td4", "user_id": "u1", "title": "Vecchia cosa", "status": "fatto", "created_at": "2026-09-01T10:00:00+00:00"},
]
db.tasks.docs += [
    {"id": "t1", "user_id": "u1", "title": "Fare lo zaino", "due_date": "2026-09-25", "completed": True, "created_at": "1"},
    {"id": "t2", "user_id": "u1", "title": "Dentista", "due_date": "2026-10-09", "due_time": "09:00", "completed": False, "created_at": "2"},
    {"id": "t3", "user_id": "u1", "title": "Bollo auto", "due_date": "2026-10-01", "completed": False, "created_at": "3"},
]
for i in range(30):
    db.kb_chunks.docs.append({"chunk_id": f"k{i}", "user_id": "u1", "text": f"nota numero {i} sul progetto", "created_at": "2026-10-01T10:00:00+00:00"})
TODAY = date(2026, 10, 5)
def disp(r): return [c["display"] for c in r if c.get("source") in ("todo", "task", "summary")]
async def main():
    t0 = time.time()
    r = await retrieval.retrieve(db, "u1", "Dimmi l'elenco dei to-do", scope="all", today=TODAY)
    print("\n".join(disp(r)), f"\n({time.time() - t0:.2f}s)")
    d = "\n".join(disp(r))
    assert "Modifiche progetto mAIPAL — da fare" in d and "Comprare toner" in d and "Preparare presentazione — in corso (40%)" in d
    assert "Vecchia cosa" not in d and "To-Do aperti: 3" in d
    r = await retrieval.retrieve(db, "u1", "quali task ho?", scope="all", today=TODAY)
    d = "\n".join(disp(r)); print(d)
    assert "Dentista" in d and "Bollo auto" in d and "SCADUTO" in d and "Task non completati: 2" in d
    for q in ["cosa devo fare?", "quali sono i miei todo", "ho dei to do aperti?", "elenca le cose da fare"]:
        r = await retrieval.retrieve(db, "u1", q, scope="all", today=TODAY)
        assert "To-Do aperti: 3" in "\n".join(disp(r)), q
    # unrelated question: nothing injected
    r = await retrieval.retrieve(db, "u1", "quando scade la patente?", scope="all", today=TODAY)
    assert not [c for c in r if c.get("source") == "summary"]
    for n in range(2):
        t0 = time.time(); await retrieval.retrieve(db, "u1", "Dimmi l'elenco dei to-do", scope="all", today=TODAY); print(f"warm {n}: {time.time() - t0:.2f}s")
    for i in range(30, 1500):
        db.kb_chunks.docs.append({"chunk_id": f"k{i}", "user_id": "u1", "text": f"nota {i} su clienti spese lezioni pilates progetto", "created_at": "2026-10-01T10:00:00+00:00"})
    t0 = time.time(); await retrieval.retrieve(db, "u1", "spese di ottobre", scope="all", today=TODAY); print(f"1500 notes, first (embeds them once): {time.time() - t0:.2f}s")
    t0 = time.time(); await retrieval.retrieve(db, "u1", "spese di ottobre", scope="all", today=TODAY); print(f"1500 notes, warm: {time.time() - t0:.2f}s")
    print("ALL OK")
asyncio.run(main())
