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
            d = {k: v for k, v in q.items() if not isinstance(v, dict)}; d.update(u.get("$set", {})); d.update(u.get("$inc", {})); s.docs.append(d)
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




async def main():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=6)).isoformat(); new = (now - timedelta(days=2)).isoformat()
    db.news_items.docs += [
        {"id": "a", "user_id": "u1", "source": "Ansa", "created_at": old, "feedback": None},
        {"id": "b", "user_id": "u1", "source": "Ansa", "created_at": old, "feedback": "like"},
        {"id": "c", "user_id": "u1", "source": "Clickbait", "created_at": old, "feedback": "dislike"},
        {"id": "d", "user_id": "u1", "source": "Clickbait", "created_at": old, "feedback": "dislike"},
        {"id": "e", "user_id": "u1", "source": "Ansa", "created_at": new, "feedback": None},
        {"id": "f", "user_id": "u1", "source": "Clickbait", "created_at": new, "feedback": "dislike"},
    ]
    n = await server._cleanup_old_news()
    left = sorted(d["id"] for d in db.news_items.docs)
    print(n, left, db.news_source_feedback.docs)
    assert n == 3 and left == ["b", "e", "f"]
    assert db.news_source_feedback.docs == [{"user_id": "u1", "source": "Clickbait", "dislikes": 2}]
    class Agg:
        def __init__(s, rows): s.rows = rows
        def __aiter__(s): s.i = iter(s.rows); return s
        async def __anext__(s):
            try: return next(s.i)
            except StopIteration: raise StopAsyncIteration
    db.news_items.aggregate = lambda pipe: Agg([{"_id": {"source": "Clickbait", "feedback": "dislike"}, "n": 1},
                                                {"_id": {"source": "Ansa", "feedback": "like"}, "n": 1}])
    prefs = await server._news_source_preferences("u1")
    print(prefs)
    assert prefs == {"liked_sources": ["Ansa"], "disliked_sources": ["Clickbait"]}
    # a second run doesn't count the same dislikes twice (they're gone)
    await server._cleanup_old_news()
    assert db.news_source_feedback.docs[0]["dislikes"] == 2
    print("ALL OK")
asyncio.run(main())
