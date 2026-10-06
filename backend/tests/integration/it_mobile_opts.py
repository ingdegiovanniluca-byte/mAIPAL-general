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
            if _match(d, q):
                d.update(u.get("$set", {})); n += 1
                for k, v in u.get("$addToSet", {}).items():
                    arr = d.setdefault(k, [])
                    for x in (v["$each"] if isinstance(v, dict) and "$each" in v else [v]):
                        if x not in arr: arr.append(x)
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
import json as J, os as _os
_os.environ["APP_BASE_URL"] = "https://maipal.it/general"
users = [{"user_id": "u1", "email": "l@x.it", "name": "Luca Bianchi", "org_id": "o1"},
         {"user_id": "u2", "email": "m@x.it", "name": "Mario Rossi", "org_id": "o1", "telegram_chat_id": 222},
         {"user_id": "u3", "email": "g@x.it", "name": "Giulia Verdi", "org_id": "o1"}]
db.users.docs += [dict(u) for u in users]
sent = []
async def fake_send(chat_id, text): sent.append((chat_id, text)); return True
server._send_telegram_text = fake_send
class FakeChat:
    def __init__(self, *a, **k): pass
    def with_model(self, *a): return self
    async def stream_message(self, msg):
        yield TextDelta(content="Salvato.")
        yield TextDelta(content='<<<META>>>{"title": "Codice cancello"}<<<END>>>')
        yield StreamDone()
    async def send_message(self, msg): return '{"topics": {}}'
server.LlmChat = FakeChat
async def fake_classify(text, user_id=None, channel="web"): return {"category": "note", "keywords": []}
server._classify_document = fake_classify
# --- fake Google + Microsoft
import google_integration as gi, microsoft_integration as ms
calls = []
async def g_creds(db_, uid): return object()
async def g_list(db_, uid, c): return [{"id": "gf1", "name": "Fatture"}]
async def g_folder(db_, uid, c, name): calls.append(("g_folder", name)); return "gf"
async def g_root(db_, uid, c): return "groot"
def g_upload(c, fid, p, fn, ct): calls.append(("g_upload", fid, fn)); return {"file_id": "g1", "web_view_link": "https://drive/g1", "name": fn}
async def g_event(c, **kw): calls.append(("g_event", kw.get("recurrence"))); return f"gev{len(calls)}"
async def g_del(c, eid): calls.append(("g_del", eid))
gi.get_credentials, gi.list_subfolders, gi.find_or_create_subfolder, gi.ensure_maipal_folder, gi.upload_file_to_folder, gi.create_calendar_event, gi.delete_calendar_event = g_creds, g_list, g_folder, g_root, g_upload, g_event, g_del
async def m_token(db_, uid): return "tok"
async def m_list(db_, uid, t): return [{"id": "mf1", "name": "fatture"}, {"id": "mf2", "name": "Viaggi"}]
async def m_folder(db_, uid, t, name): calls.append(("m_folder", name)); return "mf"
async def m_upload(t, fid, p, fn, ct): calls.append(("m_upload", fid, fn)); return {"file_id": "m1", "web_view_link": "https://onedrive/m1", "name": fn}
async def m_event(t, **kw): calls.append(("m_event", kw.get("recurrence"))); return f"mev{len(calls)}"
async def m_del(t, eid): calls.append(("m_del", eid))
async def m_exchange(code): return {"access_token": "a", "refresh_token": "r", "expires_at": "2099-01-01T00:00:00+00:00", "scopes": []}
async def m_email(t): return "luca@hotmail.it"
ms.get_token, ms.list_folders, ms.find_or_create_folder, ms.upload_file, ms.create_event, ms.delete_event, ms.exchange_code, ms.get_account_email = m_token, m_list, m_folder, m_upload, m_event, m_del, m_exchange, m_email
_os.environ["MS_CLIENT_ID"] = "x"; _os.environ["MS_CLIENT_SECRET"] = "y"

async def main():
    luca = server.User(**users[0])
    await db.integrations.insert_one({"user_id": "u1", "provider": "google"})
    await db.integrations.insert_one({"user_id": "u1", "provider": "microsoft"})
    async def no_hint(text, names, user_id=None, channel="web"): return None
    server._resolve_drive_folder_hint = no_hint
    calls.clear()
    r = await server._drive_smart_upload_core(luca, b"x", "a.pdf", "application/pdf", "ecco", only=["onedrive"], ask_folder=False)
    print("auto folder, onedrive only:", r["status"], r["folder"], r["saved"], calls)
    assert r["saved"] == ["onedrive"] and r["folder"] == "mAIPAL"
    calls.clear()
    r = await server._drive_smart_upload_core(luca, b"x", "b.pdf", "application/pdf", "ecco", only=["google"], ask_folder=True)
    print("ask folder:", r["status"])
    r2 = await server._drive_resolve_pending_core(luca, r["pending_id"], "Fatture")
    print("resolved:", r2["status"], r2["folder"], r2["where"], calls)
    assert r2["where"] == "Google Drive"
    calls.clear()
    doc = await server._create_task_or_todo("u1", {"title": "Dentista", "due_date": "2026-10-09", "due_time": "10:00"}, "c1", default_reminder_enabled=True, sync_calendar=True)
    print("task:", doc.get("reminder_enabled"), doc.get("calendar_synced"), doc.get("calendar_events"), [c[0] for c in calls])
    assert doc["reminder_enabled"] and doc["calendar_synced"]
    print("ALL OK")
asyncio.run(main())
