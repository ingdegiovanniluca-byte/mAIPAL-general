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



import httpx
async def fake_process(db_, user_doc, action, content, conv_id, images=None, channel="telegram"):
    assert channel == "watch"
    return f"risposta {action}: {content}", conv_id or "conv_watch_1"
server.tg._process_action = fake_process
async def fake_cmd(user_id, text, channel="web"): return None
server._execute_task_command = fake_cmd
async def fake_cls(text, names, user_id=None, channel="web"): return "info_upload"
server.lu.classify_save_intent = fake_cls

async def main():
    tr = httpx.ASGITransport(app=server.app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t") as c:
        db.user_sessions.docs.append({"user_id": "u1", "session_token": "phone", "expires_at": datetime.now(timezone.utc) + timedelta(days=1)})
        r = (await c.post("/api/watch/pair/start")).json(); print(r)
        assert len(r["code"]) == 6
        s = (await c.get("/api/watch/pair/status", params={"pair_id": r["pair_id"]})).json(); assert s["status"] == "pending", s
        bad = await c.post("/api/watch/pair/confirm", json={"code": "000000" if r["code"] != "000000" else "111111"}, headers={"Authorization": "Bearer phone"})
        assert bad.status_code == 404, bad.text
        noauth = await c.post("/api/watch/pair/confirm", json={"code": r["code"]}); assert noauth.status_code == 401
        ok = await c.post("/api/watch/pair/confirm", json={"code": r["code"][:3] + " " + r["code"][3:]}, headers={"Authorization": "Bearer phone"})
        assert ok.status_code == 200, ok.text
        s = (await c.get("/api/watch/pair/status", params={"pair_id": r["pair_id"]})).json(); print(s)
        assert s["status"] == "linked" and s["token"] and s["name"] == "Luca"
        again = (await c.get("/api/watch/pair/status", params={"pair_id": r["pair_id"]})).json(); assert again["status"] == "expired"
        W = {"Authorization": "Bearer " + s["token"]}
        me = (await c.get("/api/watch/me", headers=W)).json(); assert me["name"] == "Luca"
        devs = (await c.get("/api/watch/devices", headers={"Authorization": "Bearer phone"})).json(); assert len(devs) == 1 and devs[0]["last_seen"]
        # data
        from datetime import date
        today = datetime.now(server.LOCAL_TZ).date()
        for i, (d, done) in enumerate([(today - timedelta(days=1), False), (today, False), (today, True), (today + timedelta(days=3), False), (today + timedelta(days=30), False)]):
            db.tasks.docs.append({"id": f"task_{i}", "user_id": "u1", "title": f"T{i}", "due_date": d.isoformat(), "due_time": "10:00" if i == 1 else None, "completed": done, "created_at": str(i)})
        t = (await c.get("/api/watch/tasks", headers=W)).json(); print(t)
        assert [x["status"] for x in t["tasks"]] == ["late", "today", "done", "upcoming"], t
        assert (await c.post("/api/watch/tasks/task_1/done", headers=W)).status_code == 200
        assert db.tasks.docs[1]["completed"] is True
        db.todos.docs += [{"id": "todo_1", "user_id": "u1", "title": "Comprare", "status": "da_fare", "created_at": "1"},
                          {"id": "todo_2", "user_id": "u1", "title": "Fatto già", "status": "fatto", "created_at": "2"}]
        td = (await c.get("/api/watch/todos", headers=W)).json(); assert [x["id"] for x in td] == ["todo_1"], td
        assert (await c.post("/api/watch/todos/todo_1/done", headers=W)).status_code == 200
        assert db.todos.docs[0]["status"] == "fatto"
        db.collections.docs.append({"id": "c1", "user_id": "u1", "name": "Spesa", "sort_order": 0, "created_at": "1",
                                    "fields": [{"key": "prodotto", "label": "Prodotto"}, {"key": "qta", "label": "Quantità"}]})
        db.collection_items.docs += [{"id": "i1", "collection_id": "c1", "data": {"prodotto": "Latte", "qta": 2}, "sort_order": 0, "created_at": "1"},
                                     {"id": "i2", "collection_id": "c1", "data": {"prodotto": "Pane"}, "sort_order": 1, "created_at": "2"}]
        server.db.collection_items.aggregate = None
        class Agg:
            def __init__(s, out): s.out = out
            async def to_list(s, n): return s.out
        db.collection_items.aggregate = lambda pipe: Agg([{"_id": "c1", "n": 2}])
        db.collection_sub_items.aggregate = lambda pipe: Agg([])
        async def no_sharing(colls, current): return None
        server._add_sharing_info = no_sharing
        ls = (await c.get("/api/watch/lists", headers=W)).json(); print(ls); assert ls == [{"id": "c1", "name": "Spesa", "count": 2}]
        li = (await c.get("/api/watch/lists/c1", headers=W)).json(); print(li)
        assert li["items"][0] == {"id": "i1", "label": "Latte", "detail": "2"} and li["items"][1]["label"] == "Pane"
        # ask
        a = (await c.post("/api/watch/ask", json={"agent": "info_request", "text": "che tempo fa"}, headers=W)).json(); print(a)
        assert a["kind"] == "answer" and a["conv_id"] == "conv_watch_1"
        # someone else's conv id is dropped
        db.conversations.docs.append({"conv_id": "other", "user_id": "u2", "action": "info_request"})
        seen = {}
        async def spy(db_, user_doc, action, content, conv_id, images=None, channel="telegram"):
            seen["conv"] = conv_id; return "ok", conv_id or "new"
        server.tg._process_action = spy
        await c.post("/api/watch/ask", json={"agent": "info_request", "text": "x", "conv_id": "other"}, headers=W)
        assert seen["conv"] is None
        db.conversations.docs.append({"conv_id": "mine", "user_id": "u1", "action": "info_request"})
        await c.post("/api/watch/ask", json={"agent": "info_request", "text": "x", "conv_id": "mine"}, headers=W)
        assert seen["conv"] == "mine"
        # Salva routed to a list
        async def cls_upd(text, names, user_id=None, channel="web"): return "list_update"
        server.lu.classify_save_intent = cls_upd
        async def fake_lu(current, text, channel="web", **k): return {"status": "ok", "message": "Aggiunto Latte a Spesa"}
        server._execute_list_update = fake_lu
        a = (await c.post("/api/watch/ask", json={"agent": "info_upload", "text": "aggiungi latte alla lista spesa"}, headers=W)).json()
        assert a == {"kind": "message", "reply": "Aggiunto Latte a Spesa"}, a
        # unlink: the watch token stops working
        assert (await c.delete(f"/api/watch/devices/{devs[0]['device_id']}", headers={"Authorization": "Bearer phone"})).status_code == 200
        assert (await c.get("/api/watch/me", headers=W)).status_code == 401
        # brute force guard
        for _ in range(5):
            await c.post("/api/watch/pair/confirm", json={"code": "999999"}, headers={"Authorization": "Bearer phone"})
        r429 = await c.post("/api/watch/pair/confirm", json={"code": "999999"}, headers={"Authorization": "Bearer phone"})
        assert r429.status_code == 429, r429.status_code
    print("ALL OK")
asyncio.run(main())
