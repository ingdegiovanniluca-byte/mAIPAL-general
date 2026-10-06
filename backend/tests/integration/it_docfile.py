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

prompts = []
class FakeChat:
    def __init__(self, *a, **k): pass
    def with_model(self, *a): return self
    async def stream_message(self, msg):
        prompts.append(("primary", msg.text))
        yield TextDelta(content="Ho memorizzato il documento del matrimonio.")
        yield TextDelta(content='<<<META>>>{"title": "Matrimonio", "summary": "lista cose da fare"}<<<END>>>')
        yield StreamDone()
    async def send_message(self, msg):
        prompts.append(("send", msg.text))
        if "RICHIESTA PER IL TASK" in msg.text and "Contatti SIAE" in msg.text:
            return 'Ecco i task. <<<META>>>{"tasks": [{"title": "Chiedere alla location la filodiffusione", "due_date": "2026-10-04"}, {"title": "Contatti SIAE", "due_date": "2026-10-04"}]}<<<END>>>'
        if "RICHIESTA PER IL TASK" in msg.text:
            return "Non ho accesso diretto ai tuoi documenti."
        return '{"category": "altro", "keywords": []}'
server.LlmChat = FakeChat
async def fake_embed(texts): return [None] * len(texts)
server.emb.embed_texts = fake_embed
async def fake_classify(*a, **k): return {"category": "altro", "keywords": []}
server._classify_document = fake_classify
async def fake_retrieve(*a, **k): return []
server.retrieve_kb = fake_retrieve
async def run(payload):
    resp = await server.chat_stream(payload, server.User(**U))
    out = []
    async for chunk in resp.body_iterator:
        for line in chunk.strip().split("\n"):
            if line: out.append(J.loads(line))
    return out
from fastapi import UploadFile
import io
async def main():
    data = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "programma_tabella.docx"), "rb").read()
    up = await server.kb_upload(UploadFile(file=io.BytesIO(data), filename="Luca_MArtina_10_ottobre.docx"), server.User(**U))
    chunk = db.kb_chunks.docs[0]["text"]
    print("CHUNK:", chunk.replace("\n", " / "))
    assert "Perfect - Ed Sheeran" in chunk and "Contatti SIAE" in chunk
    disp = "salva\n📎 Luca_MArtina_10_ottobre.docx"
    ev = await run(server.ChatRequest(action="info_upload", content="salva\n\nAllegati caricati nella knowledge base personale:\n📎 Luca_MArtina_10_ottobre.docx · 1 chunk", display_content=disp, attachment_doc_ids=[up["doc_id"]]))
    conv = db.conversations.docs[0]
    print("conv attachment ids:", conv.get("attachment_doc_ids"))
    ev = await run(server.ChatRequest(action="info_upload", conv_id=conv["conv_id"], content="@task e aggiungi per domani le cose che sono indicate come da fare nel file"))
    print("EVENTS:", [(e["type"], e.get("agent"), e.get("status"), (e.get("message") or "")[:120]) for e in ev])
    print("TASKS:", [(t["title"], t["due_date"]) for t in db.tasks.docs])
    assert len(db.tasks.docs) == 2
    # older conversation (no attachment_doc_ids stored): found from the 📎 line
    conv = db.conversations.docs[0]; conv.pop("attachment_doc_ids")
    ev = await run(server.ChatRequest(action="info_upload", conv_id=conv["conv_id"], content="@task aggiungi per domani le cose da fare nel file"))
    print("LEGACY:", [(e.get("agent"), e.get("status")) for e in ev], len(db.tasks.docs))
    assert len(db.tasks.docs) == 4
    # follow-up question in a Cerca conversation with the file
    db.conversations.docs.append({"conv_id": "c_req", "user_id": "u1", "action": "info_request", "messages": [{"role": "user", "content": "cosa c'è\n📎 Luca_MArtina_10_ottobre.docx"}], "attachment_doc_ids": [up["doc_id"]], "filters": {}})
    prompts.clear()
    ev = await run(server.ChatRequest(action="info_request", conv_id="c_req", content="quali canzoni ho scelto?"))
    print("REQ prompt has songs:", "Ed Sheeran" in prompts[0][1])
    assert "Ed Sheeran" in prompts[0][1]
    print("ALL OK")
asyncio.run(main())
