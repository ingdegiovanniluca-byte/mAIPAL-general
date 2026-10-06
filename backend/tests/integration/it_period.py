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




import retrieval, embeddings as emb
from datetime import date
async def no_q(q): raise RuntimeError("no model")
async def zeros(ts): return [None for _ in ts]
emb.embed_query = no_q; emb.embed_texts = zeros
TODAY = date(2026, 10, 8)   # a Thursday
def note(i, text, when):
    db.kb_chunks.docs.append({"chunk_id": f"k{i}", "user_id": "u1", "text": text, "created_at": when})
note(1, "ogni mese spendo 30 € al mese per internet", "2026-09-20T10:00:00+00:00")
note(2, "ho speso 45 euro al supermercato", "2026-10-02T09:00:00+00:00")
note(3, "benzina 60 €", "2026-10-05T18:00:00+00:00")
note(4, "pagato il dentista 120 euro", "2026-10-07T08:00:00+00:00")
note(5, "cena da Mario 35 euro", "2026-09-28T20:00:00+00:00")
note(6, "il codice del wifi è 1234", "2026-10-03T08:00:00+00:00")
note(7, "spesa veterinario 80 euro", "2026-10-07T22:30:00+00:00")   # 00:30 of the 8th in Rome
def ids(res): return sorted(c["meta"]["chunk_id"] for c in res if c.get("source") == "kb")
async def main():
    w = retrieval.time_window("le spese del mese di ottobre", TODAY); print(w)
    assert w[0] == date(2026, 10, 1) and w[1] == date(2026, 10, 31)
    r = await retrieval.retrieve(db, "u1", "dimmi le spese del mese di ottobre", scope="kb", today=TODAY)
    print("ottobre:", ids(r))
    assert {"k1", "k2", "k3", "k4", "k7"} <= set(ids(r)) and "k6" not in ids(r)
    k1 = next(c for c in r if c["meta"]["chunk_id"] == "k1"); print(k1["display"]); assert k1["display"].startswith("[Ricorrente] [Nota salvata")
    k5 = [c for c in r if c["meta"]["chunk_id"] == "k5"]; assert not k5 or not k5[0]["display"].startswith("[Ricorrente")
    r = await retrieval.retrieve(db, "u1", "le spese di questa settimana", scope="kb", today=TODAY)
    print("settimana:", ids(r))
    assert {"k3", "k4", "k7"} <= set(ids(r))
    r = await retrieval.retrieve(db, "u1", "quanto ho speso oggi?", scope="kb", today=TODAY)
    print("oggi:", ids(r)); assert "k7" in ids(r)
    r = await retrieval.retrieve(db, "u1", "spese del mese scorso", scope="kb", today=TODAY)
    print("mese scorso:", ids(r)); assert {"k1", "k5"} <= set(ids(r))
    assert retrieval.time_window("quando scade la patente?", TODAY) is None
    assert retrieval.time_window("cosa devo fare a dicembre", TODAY)[2] == "dicembre 2026"
    assert retrieval.time_window("spese di marzo", TODAY)[2] == "marzo 2026"
    assert retrieval.time_window("negli ultimi 10 giorni", TODAY)[0] == date(2026, 9, 29)
    assert retrieval.time_window("la settimana scorsa", TODAY)[:2] == (date(2026, 9, 28), date(2026, 10, 4))
    print(retrieval.period_hint("spese di ottobre", TODAY))
    assert retrieval.is_recurring("abbonamento palestra 40 euro al mese") and retrieval.is_recurring("ogni lunedì 10 € di pizza")
    assert not retrieval.is_recurring("ho speso 45 euro al supermercato") and not retrieval.is_recurring("benzina 60 €")
    print("ALL OK")
asyncio.run(main())
