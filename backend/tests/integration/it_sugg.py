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
calls = []
class FakeLLM:
    def __init__(self, *a, **k): pass
    def with_model(self, *a): return self
    async def send_message(self, m):
        calls.append(m.text)
        return '{"items": [{"text": "Domani chiami Marco: aspettava il preventivo", "target": {"type": "task", "id": "t2"}}, {"text": "Hai salvato il codice del cancello", "target": {"type": "chat", "action": "info_request", "text": "codice cancello"}}]}'
server.LlmChat = FakeLLM
U = {"user_id": "u1", "email": "a@b.it", "name": "Luca"}
db.users.docs.append(U)
from datetime import date, timedelta
today = server._local_today()
db.tasks.docs += [{"id": "t1", "user_id": "u1", "title": "Vecchio", "due_date": (today - timedelta(days=3)).isoformat()},
                  {"id": "t2", "user_id": "u1", "title": "Chiamare Marco", "due_date": (today + timedelta(days=1)).isoformat(), "due_time": "10:00"}]
db.kb_chunks.docs.append({"chunk_id": "k", "user_id": "u1", "text": "Marco aspetta il preventivo", "created_at": server.datetime.now(server.timezone.utc).isoformat()})
async def main():
    user = server.User(**U)
    r1 = await server.get_suggestions(user)
    print("FIRST:", [(i["id"], i["text"]) for i in r1["items"]])
    await asyncio.sleep(0.2)
    r2 = await server.get_suggestions(user)
    print("SECOND:", [(i["id"], i["text"], i["target"]) for i in r2["items"]])
    r3 = await server.get_suggestions(user)
    print("LLM calls:", len(calls))
    assert any(i["kind"] == "insight" for i in r2["items"]) and len(calls) == 1
    print("ALL OK")
asyncio.run(main())
