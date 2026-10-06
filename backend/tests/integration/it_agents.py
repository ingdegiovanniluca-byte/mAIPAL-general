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
from llm_integrations import TextDelta, StreamDone
import json as J
U = {"user_id": "u1", "email": "a@b.it", "name": "Luca"}
db.users.docs.append(U)
prompts = []
class FakeChat:
    def __init__(self, *a, **k): self.sys = k.get("system_message", "")
    def with_model(self, *a): return self
    async def stream_message(self, msg):
        prompts.append(("primary", msg.text))
        yield TextDelta(content="Ho salvato le informazioni sulla visita di Fester.")
        yield TextDelta(content='<<<META>>>{"title": "Visita Fester", "summary": "controllo ok"}<<<END>>>')
        yield StreamDone()
    async def send_message(self, msg):
        prompts.append(("send", msg.text))
        if "RICHIESTA PER IL TASK" in msg.text:
            return 'Perfetto, ti ricorderò di richiamare la sig.ra Bianchi giovedì. <<<META>>>{"title": "Richiamare la sig.ra Bianchi per Fester", "due_date": "2026-10-01", "due_time": null, "priority": "media", "notes": "Visita del 29/09: controllo ecografico ok, antibiotico 7 giorni."}<<<END>>>'
        return '{"topics": {}}'
server.LlmChat = FakeChat
async def fake_interpret(text, catalog, kb_context="", user_id=None, channel="web"):
    return {"op": "clear_all_sub_items", "collection_id": "c1", "item_query": "", "sub_item_query": "", "fields": {}, "sub_items": [], "items": []}
server.lu.interpret_list_request = fake_interpret
db.collections.docs.append({"id": "c1", "user_id": "u1", "name": "Lezioni Pilates", "fields": [{"key": "l", "label": "L"}], "sub_item_fields": [{"key": "n", "label": "N"}], "visibility": "private"})
db.collection_items.docs.append({"id": "i1", "collection_id": "c1", "user_id": "u1", "data": {"l": "Lun 9"}})
db.collection_sub_items.docs.append({"id": "s1", "collection_id": "c1", "item_id": "i1", "user_id": "u1", "data": {"n": "Anna"}})
async def run(payload):
    resp = await server.chat_stream(payload, server.User(**U))
    out = []
    async for chunk in resp.body_iterator:
        for line in chunk.strip().split("\n"):
            if line: out.append(J.loads(line))
    return out
async def main():
    text = "Visitato Fester, gatto della sig.ra Bianchi: controllo ecografico ok, antibiotico 7 giorni. @task richiamare la padrona giovedì per sapere come sta"
    ev = await run(server.ChatRequest(action="info_upload", content=text))
    print("EVENTS:", [(e["type"], e.get("agent"), e.get("status"), (e.get("message") or e.get("content") or "")[:80]) for e in ev])
    primary = next(p for k, p in prompts if k == "primary")
    print("primary got tag?", "@task" in primary, "| task prompt has context?", any("Bianchi" in p and "RICHIESTA PER IL TASK" in p for k, p in prompts if k == "send"))
    note = [c for c in db.kb_chunks.docs if c.get("source_type") == "chat"][0]
    print("NOTE:", note["text"])
    task = db.tasks.docs[0]
    print("TASK:", task["title"], task["due_date"], "| notes:", task.get("notes"), "| source:", task.get("source", {}).get("type"), task.get("source", {}).get("label"))
    doc = db.kb_documents.docs[0]
    print("NOTE linked:", doc.get("linked"))
    conv = db.conversations.docs[0]
    print("CONV messages:", [(m["role"], m.get("agent"), m["content"][:50]) for m in conv["messages"]])
    assert "@task" not in note["text"] and task.get("source", {}).get("doc_id") == doc["doc_id"]
    # only tags, destructive list op -> pending confirmation, nothing deleted
    ev = await run(server.ChatRequest(action="info_upload", content="@lista svuota tutte le lezioni pilates @task comprare cibo gatto"))
    print("EVENTS2:", [(e["type"], e.get("agent"), e.get("status"), (e.get("message") or "")[:60], bool(e.get("list_result"))) for e in ev])
    assert len(db.collection_sub_items.docs) == 1
    print("ALL OK")
asyncio.run(main())
