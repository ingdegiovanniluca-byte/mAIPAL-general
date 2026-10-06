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




import httpx, json
import embeddings as emb
async def zeros(ts): return [None for _ in ts]
emb.embed_texts = zeros
async def no_kb(*a, **k): return []
server.retrieve_kb = no_kb
async def no_topics(*a, **k): return None
server._ensure_conv_topics = no_topics
async def no_cmd(*a, **k): return None
server._execute_task_command = no_cmd
today = datetime.now(server.LOCAL_TZ).date().isoformat()
REPLY = {"text": ""}
class FakeChat:
    def __init__(self, *a, **k): pass
    def with_model(self, *a): return self
    async def stream_message(self, msg):
        for i in range(0, len(REPLY["text"]), 7):
            yield server.TextDelta(content=REPLY["text"][i:i+7])
        yield server.StreamDone()
server.LlmChat = FakeChat
async def main():
    tr = httpx.ASGITransport(app=server.app)
    db.user_sessions.docs.append({"user_id": "u1", "session_token": "t", "expires_at": datetime.now(timezone.utc) + timedelta(days=1)})
    H = {"Authorization": "Bearer t"}
    async with httpx.AsyncClient(transport=tr, base_url="http://t") as c:
        REPLY["text"] = 'Perfetto, ho creato il to-do «Modifiche progetto mAIPAL».<<<META>>>{"title": "Modifiche progetto mAIPAL", "due_date": "%s"}<<<END>>>' % today
        r = await c.post("/api/chat/stream", json={"action": "task_todo", "content": 'crea un to-do chiamato "modifiche progetto maipal"'}, headers=H)
        evs = [json.loads(l) for l in r.text.splitlines() if l.strip()]
        shown = "".join(e["content"] for e in evs if e["type"] == "delta")
        conv = next(e["conv_id"] for e in evs if e["type"] == "done")
        print(repr(shown)); print([e for e in evs if e["type"] != "delta"])
        assert "Perfetto, ho creato" in shown and "✅ Salvato nei To-Do: «Modifiche progetto mAIPAL»" in shown and "META" not in shown
        assert len(db.todos.docs) == 1 and not db.tasks.docs
        stored = next(d for d in db.conversations.docs if d["conv_id"] == conv)["messages"][-1]["content"]
        assert "Salvato nei To-Do" in stored
        REPLY["text"] = "Ho ricreato il to-do, ora dovresti vederlo."
        r = await c.post("/api/chat/stream", json={"action": "task_todo", "content": "non lo vedo, ricrealo", "conv_id": conv}, headers=H)
        shown = "".join(json.loads(l)["content"] for l in r.text.splitlines() if l.strip() and json.loads(l)["type"] == "delta")
        print(shown); assert len(db.todos.docs) == 1 and "È salvato nei To-Do" in shown
    print("ALL OK")
asyncio.run(main())
