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
U = {"user_id": "u1", "email": "a@b.it", "name": "Luca"}
db.users.docs.append(U)
seen_prompts = []
class FakeChat:
    def __init__(self, *a, **k): pass
    def with_model(self, *a): return self
    async def stream_message(self, msg):
        seen_prompts.append(msg.text)
        yield TextDelta(content="Ho salvato lo scontrino come spesa del gatto: totale 43,40 €.")
        yield StreamDone()
    async def send_message(self, msg): return '{"topics": {}}'
server.LlmChat = FakeChat
RECEIPT = "FARMACIA VETERINARIA SAN ROCCO\n25/09/2026 17:40\nANTIPARASSITARIO SPOT-ON 18,90\nCROCCHETTE STERILIZED 2KG 24,50\nTOTALE EURO 43,40"
async def fake_ocr(contents, filename, user_id=None, channel="web"): return RECEIPT
async def fake_classify(text, user_id=None, channel="web"): return {"category": "ricevute", "keywords": ["farmacia"]}
server._ocr_image_bytes = fake_ocr
server._classify_document = fake_classify
server.retrieval.retrieve = __import__("retrieval").retrieve  # real retrieval (it_sugg stubbed nothing here)
# some unrelated notes so the pool is realistic
for i, t in enumerate(["Il codice del wifi è XYZ", "Martina ha fatto pilates", "Spesa al supermercato 32 euro", "Il gatto ha fatto il vaccino il 3 marzo"]):
    db.kb_chunks.docs.append({"chunk_id": f"n{i}", "user_id": "u1", "text": t, "doc_id": f"nd{i}", "source_type": "chat", "chunk_index": 0, "created_at": "2026-09-20T10:00:00+00:00"})
async def main():
    user = server.User(**U)
    up = await server._ocr_and_save_image_to_kb("u1", "scontrino.jpg", b"img")
    before = await server.retrieval.retrieve(db, "u1", "dimmi le spese del gatto", limit=8, scope="all")
    print("BEFORE link, receipt found:", any("43,40" in (c.get("display") or c.get("text") or "") for c in before[:4]))
    payload = server.ChatRequest(action="info_upload", content="salva le spese come spese gatto\n\nAllegati caricati nella knowledge base personale:\n📎 scontrino.jpg · 1 chunk", display_content="salva le spese come spese gatto\n📎 scontrino.jpg", attachment_doc_ids=[up["doc_id"]])
    resp = await server.chat_stream(payload, user)
    async for _ in resp.body_iterator: pass
    print("MODEL SAW RECEIPT:", "TOTALE EURO 43,40" in seen_prompts[0])
    after = await server.retrieval.retrieve(db, "u1", "dimmi le spese del gatto", limit=8, scope="all")
    top = [(c.get("display") or c.get("text"))[:90].replace("\n", " | ") for c in after[:4]]
    print("AFTER top 4:"); [print("   ", t) for t in top]
    assert any("43,40" in (c.get("display") or c.get("text") or "") for c in after[:3])
    ch = next(c for c in db.kb_chunks.docs if c.get("doc_id") == up["doc_id"])
    print("chunk text starts:", ch["text"][:60].replace("\n", " | "), "| embedding:", ch["embedding"] is not None)
    print("ALL OK")
asyncio.run(main())
