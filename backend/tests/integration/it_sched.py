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
        return R(0)
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
sent = []
async def fake_send(chat_id, text):
    sent.append((chat_id, text)); return True
server._send_telegram_text = fake_send

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "telegram_chat_id": 123}
now = datetime.now(timezone.utc).isoformat()
db.users.docs.append(U)
db.collections.docs.append({"id": "c1", "user_id": "u1", "name": "Lezioni Pilates", "fields": [{"key": "lezione", "label": "Lezione"}], "sub_item_fields": [{"key": "nome", "label": "Nome"}], "visibility": "private", "created_at": now})
for i in range(3):
    db.collection_items.docs.append({"id": f"it{i}", "collection_id": "c1", "user_id": "u1", "data": {"lezione": f"Lunedì {9+i}:00"}, "created_at": now})
    for k in range(4):
        db.collection_sub_items.docs.append({"id": f"s{i}{k}", "collection_id": "c1", "item_id": f"it{i}", "user_id": "u1", "data": {"nome": f"Persona {k}"}, "created_at": now})
last_week_note = (datetime.now(timezone.utc) - timedelta(days=(datetime.now().weekday() + 3))).isoformat()
db.kb_chunks.docs.append({"chunk_id": "k1", "user_id": "u1", "text": "oggi ho speso 45,20 euro al supermercato", "source_type": "chat", "created_at": last_week_note, "doc_id": "d1", "chunk_index": 0})

async def fake_interpret(text, catalog, now_local, linked, user_id=None, channel="web"):
    if "pilates" in text:
        return {"supported": True, "title": "Svuota iscritti", "kind": "list_update", "schedule": {"freq": "weekly", "weekdays": [4], "time": "01:00"}, "list_request": "elimina tutti gli elementi di tutti i campi della lista Lezioni Pilates"}
    if "spesa" in text:
        return {"supported": True, "title": "Spesa settimana", "kind": "report", "schedule": {"freq": "weekly", "weekdays": [0], "time": "00:00"}, "report_instruction": "Calcola la spesa totale", "period": "last_week", "delivery": "telegram"}
    if "affitto" in text:
        return {"supported": True, "title": "Affitto", "kind": "create_task", "schedule": {"freq": "monthly", "day_of_month": 1, "time": "09:00"}, "task": {"title": "Pagare affitto", "priority": "alta"}}
    return {"supported": False, "reason": "Non posso inviare email."}
sa.interpret_command = fake_interpret
async def fake_lu(text, catalog, kb_context="", user_id=None, channel="web"):
    return {"op": "clear_all_sub_items", "collection_id": "c1", "item_query": "", "sub_item_query": "", "fields": {}, "sub_items": [], "items": []}
lu.interpret_list_request = fake_lu
captured = {}
async def fake_report(instruction, data_block, now_local, period_label, user_name="", user_id=None):
    captured["data"] = data_block; captured["period"] = period_label
    return sa.fill_totals("Totale: {{T1}} €", [{"key": "T1", "values": ["45,20", 10]}])
sa.write_report = fake_report
async def fake_retrieve(*a, **k): return []
retrieval.retrieve = fake_retrieve

async def main():
    user = server.User(**U)
    d = await server._build_scheduled_draft(user, "ogni venerdì all'una di notte cancella tutti gli elementi della lista lezione di pilates")
    print("DRAFT1:", d["status"], "|", d["preview"])
    assert d["status"] == "confirm" and "12 elementi in 3 campi" in d["preview"]
    a = await server._create_scheduled_action(user, d["draft"])
    print("CREATED:", a["title"], a["schedule_label"], "next:", a["next_run_label"])
    # force due, run loop body once
    db.scheduled_actions.docs[0]["next_run_at"] = server._dt_iso(datetime.now(timezone.utc) - timedelta(hours=30))
    loop_task = asyncio.create_task(server._scheduled_actions_loop())
    await asyncio.sleep(21.5); loop_task.cancel()
    act = db.scheduled_actions.docs[0]
    print("RUN1:", act["last_status"], act["last_result"], "| runs:", act["runs"], "| next:", act["next_run_at"])
    assert act["last_status"] == "ok" and len(db.collection_sub_items.docs) == 0 and len(db.collection_items.docs) == 3
    assert act["runs"][0].get("late_minutes", 0) > 1000
    assert act["next_run_at"] > server._dt_iso(datetime.now(timezone.utc))
    # report
    d2 = await server._build_scheduled_draft(user, "tutte le domeniche a mezzanotte calcola la spesa della settimana passata e mandami un messaggio su telegram")
    print("DRAFT2:", d2["preview"])
    a2 = await server._create_scheduled_action(user, d2["draft"])
    doc2 = next(x for x in db.scheduled_actions.docs if x["id"] == a2["id"])
    await server._execute_scheduled_action(doc2, manual=True)
    doc2 = next(x for x in db.scheduled_actions.docs if x["id"] == a2["id"])
    print("RUN2:", doc2["last_status"], doc2["last_result"], "| period:", captured["period"], "| sent:", sent[-1])
    print("DATA:", captured["data"][:300])
    assert "55,20" in doc2["last_result"] and sent and "supermercato" in captured["data"]
    # create task
    d3 = await server._build_scheduled_draft(user, "il primo di ogni mese crea il task pagare l'affitto")
    a3 = await server._create_scheduled_action(user, d3["draft"])
    await server._execute_scheduled_action(next(x for x in db.scheduled_actions.docs if x["id"] == a3["id"]), manual=True)
    print("TASKS:", [(t["title"], t["due_date"], t["priority"]) for t in db.tasks.docs])
    # unsupported
    d4 = await server._build_scheduled_draft(user, "ogni giorno manda una email a Mario")
    print("DRAFT4:", d4)
    # toggle / delete endpoints
    r = await server.update_scheduled_action(a["id"], server.ScheduledPatchPayload(enabled=False), user)
    print("PAUSED:", r["enabled"], r["next_run_at"], r["next_run_label"])
    r = await server.update_scheduled_action(a["id"], server.ScheduledPatchPayload(enabled=True), user)
    print("RESUMED:", r["enabled"], r["next_run_label"])
    lst = await server.list_scheduled_actions(user)
    print("LIST:", [(x["title"], x["enabled"]) for x in lst])
    await server.delete_scheduled_action(a3["id"], user)
    print("AFTER DELETE:", len(db.scheduled_actions.docs))
    # chat list update with new op, confirm flow
    db.collection_sub_items.docs.append({"id": "z", "collection_id": "c1", "item_id": "it0", "user_id": "u1", "data": {"nome": "X"}, "created_at": now})
    r1 = await server._execute_list_update(user, "svuota tutte le lezioni", op="clear_all_sub_items", collection_id="c1")
    r2 = await server._execute_list_update(user, "svuota tutte le lezioni", op="clear_all_sub_items", collection_id="c1", confirm=True)
    print("CHAT CLEAR:", r1["status"], r1["candidates"][0]["label"], "|", r2["message"])
    print("ALL OK")
asyncio.run(main())
