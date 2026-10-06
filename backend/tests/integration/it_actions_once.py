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




import scheduled_actions as sa
P = {}
async def fake_interpret(text, catalog, now_local, linked, user_id=None, channel="web"):
    return P["parsed"]
server.sa.interpret_command = fake_interpret
async def no_tg(*a, **k): return False
server._send_telegram_text = no_tg
now = datetime.now(timezone.utc)
async def main():
    u = server.User(**U)
    db.collections.docs += [{"id": "c1", "user_id": "u1", "name": "Invitati", "fields": [{"key": "n", "label": "Nome"}]},
                            {"id": "c2", "user_id": "u2", "org_id": "o", "visibility": "org", "name": "Team", "fields": []}]
    db.collection_items.docs += [{"id": "i1", "collection_id": "c1", "data": {"n": "Mario"}}, {"id": "i2", "collection_id": "c1", "data": {"n": "Anna"}}]
    db.collection_sub_items.docs.append({"id": "s1", "collection_id": "c1", "item_id": "i1", "data": {}})
    # 2) delete a list, from chat, after a yes
    P["parsed"] = {"supported": True, "kind": "list_delete", "list_name": "invitati", "schedule": {"freq": "now"}, "title": "x"}
    d = await server._build_scheduled_draft(u, "elimina la lista invitati")
    print(d["preview"]); assert d["status"] == "confirm" and "con i suoi 2 campi" in d["preview"] and "non resta salvata" in d["preview"]
    assert len(db.collections.docs) == 2   # nothing deleted before the yes
    r = await server._create_scheduled_action(u, d["draft"])
    print(r); assert r["ran"] and r["status"] == "ok" and "Eliminata la lista «Invitati» (2 campi)" in r["result"]
    assert not [c for c in db.collections.docs if c["id"] == "c1"] and not db.collection_items.docs and not db.collection_sub_items.docs
    assert not db.scheduled_actions.docs   # una tantum: not saved
    # no schedule from the model -> still a now-action
    P["parsed"] = {"supported": True, "kind": "list_delete", "list_name": "team", "schedule": None}
    d = await server._build_scheduled_draft(server.User(**{**U, "org_id": "o"}), "elimina la lista team")
    print(d["message"]); assert d["status"] == "unsupported" and "solo chi l'ha creata" in d["message"]
    P["parsed"] = {"supported": True, "kind": "list_delete", "list_name": "boh", "schedule": {"freq": "now"}}
    d = await server._build_scheduled_draft(u, "elimina la lista boh"); assert d["status"] == "unsupported"
    # 3) news: a recurring cleanup, and a one-off
    db.news_items.docs += [
        {"id": "n1", "user_id": "u1", "created_at": (now - timedelta(days=5)).isoformat(), "feedback": None, "source": "A"},
        {"id": "n2", "user_id": "u1", "created_at": (now - timedelta(days=5)).isoformat(), "feedback": "like", "source": "A"},
        {"id": "n3", "user_id": "u1", "created_at": (now - timedelta(days=1)).isoformat(), "feedback": None, "source": "A"},
        {"id": "n4", "user_id": "u1", "created_at": (now - timedelta(days=4)).isoformat(), "feedback": "dislike", "source": "Spam"},
        {"id": "n5", "user_id": "u2", "created_at": (now - timedelta(days=9)).isoformat(), "feedback": None, "source": "A"},
    ]
    P["parsed"] = {"supported": True, "kind": "news_delete", "news": {"older_than_days": 3, "keep_liked": True}, "schedule": {"freq": "daily", "time": "07:00"}, "title": "Pulizia news"}
    d = await server._build_scheduled_draft(u, "ogni giorno alle 7 elimina le news più vecchie di 3 giorni")
    print(d["preview"]); assert "news più vecchie di 3 giorni (tranne quelle col pollice in su)" in d["preview"]
    a = await server._create_scheduled_action(u, d["draft"]); assert db.scheduled_actions.docs and a["kind"] == "news_delete"
    run = await server._execute_scheduled_action(db.scheduled_actions.docs[0], manual=True)
    print(run["result"]); assert sorted(x["id"] for x in db.news_items.docs) == ["n2", "n3", "n5"]
    assert db.news_source_feedback.docs and db.news_source_feedback.docs[0]["source"] == "Spam"
    P["parsed"] = {"supported": True, "kind": "news_delete", "news": {"older_than_days": None, "keep_liked": True}, "schedule": {"freq": "now"}}
    d = await server._build_scheduled_draft(u, "elimina adesso tutte le news")
    r = await server._create_scheduled_action(u, d["draft"]); print(r["result"])
    assert r["ran"] and sorted(x["id"] for x in db.news_items.docs) == ["n2", "n5"] and len(db.scheduled_actions.docs) == 1
    # 1) a one-off report: run, not saved
    async def fake_report(*a, **k): return "Spese: 10 €"
    server.sa.write_report = fake_report
    async def no_ret(*a, **k): return []
    server.retrieval.retrieve = no_ret
    P["parsed"] = {"supported": True, "kind": "report", "report_instruction": "riepilogo spese", "period": "this_month", "schedule": {"freq": "now"}}
    d = await server._build_scheduled_draft(u, "fammi subito il riepilogo delle spese del mese")
    r = await server._create_scheduled_action(u, d["draft"]); print(r)
    assert r["ran"] and r["result"] == "Spese: 10 €" and len(db.scheduled_actions.docs) == 1
    print("ALL OK")
asyncio.run(main())
