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
                if op == "$in" and not (any(x in arg for x in val) if isinstance(val, list) else val in arg): return False
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
                for k in u.get("$unset", {}): d.pop(k, None)
                for k, v in u.get("$addToSet", {}).items():
                    arr = d.setdefault(k, [])
                    if v not in arr: arr.append(v)
                for k, v in u.get("$pull", {}).items():
                    out = v.get("$in") if isinstance(v, dict) else [v]
                    d[k] = [x for x in d.get(k, []) if x not in out]
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
            if _match(d, q):
                d.update(u.get("$set", {})); n += 1
                for k, v in u.get("$pull", {}).items():
                    out = v.get("$in") if isinstance(v, dict) else [v]
                    d[k] = [x for x in d.get(k, []) if x not in out]
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
import job_logs as jl, telegram_bot as tg, retrieval, embeddings as emb
import scheduled_actions as sa
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77}
db.users.docs.append(dict(U))
tg.bot_token = lambda: "123:abc"
NOTICES = []
async def fake_send(chat_id, text):
    NOTICES.append((chat_id, text)); return True
server._send_telegram_text = fake_send
TOLD = []
async def fake_tell(c, text, done_data=None):   # a collaborator's message (with the "Fatto" button)
    if c.get("status") != "active" or not c.get("telegram_chat_id"):
        return False
    NOTICES.append((c["telegram_chat_id"], text)); TOLD.append((c["id"], text, done_data)); return True
server._tell_collaborator = fake_tell
async def no_emb(q): raise RuntimeError("offline")
emb.embed_query = no_emb
def said(hours=None, materials=None, problems=None, date=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web"):
        return {"kind": "nota", "doubt": "", "date": date or jl.today_local().isoformat(), "text": t,
                "hours": jl.clean_hours(hours or [], speaker), "materials": jl.clean_materials(materials or []),
                "problems": problems or [], "client": "", "commessa": ""}
    return f
ANSWERS = []
async def fake_answer(commessa, logs, reports, question, history, user_id=None, channel="web"):
    ANSWERS.append(commessa); return {"answer": "ok", "is_entry": False}
jl.answer = fake_answer

async def settle():
    for _ in range(5):
        await asyncio.sleep(0)

import collab_telegram as ct

server.tg.bot_token = lambda: "test-token"
PINS = []      # (op, chat, message_id, text, keyboard)
MID = [100]
async def fake_send(chat_id, text, kb):
    MID[0] += 1; PINS.append(("send", chat_id, MID[0], text, kb)); return MID[0]
async def fake_edit(chat_id, mid, text, kb):
    PINS.append(("edit", chat_id, mid, text, kb))
async def fake_unpin(chat_id, mid):
    PINS.append(("unpin", chat_id, mid, None, None))
server._day_pin_send, server._day_pin_edit, server._day_pin_unpin = fake_send, fake_edit, fake_unpin

class FakeMsg:
    def __init__(s, mid=None): s.replies = []; s.message_id = mid
    async def reply_text(s, text, **kw): s.replies.append(text)
class FakeQuery:
    def __init__(s, data, mid): s.data = data; s.message = FakeMsg(mid); s.cleared = False
    async def answer(s): pass
    async def edit_message_reply_markup(s, reply_markup=None): s.cleared = True
class FakeUpdate:
    def __init__(s, data, mid): s.message = None; s.callback_query = FakeQuery(data, mid)

async def settle():
    for _ in range(30):
        await asyncio.sleep(0.01)

def buttons(kb):
    return [row[0].callback_data for row in kb.inline_keyboard] if kb else []

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    smap = cl.get("system_sub_map") or {}
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi",
                                         "data": {"titolo": "Bagno", "stato": "in corso", smap.get("indirizzo_cantiere", "indirizzo_cantiere"): "Via Roma 5, Torino"}})
    db.collection_sub_items.docs.append({"id": "s_tetto", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Tetto", "stato": "in corso"}})
    db.collaborators.docs += [
        {"id": "k1", "owner_user_id": "u1", "first_name": "Gino", "last_name": "Neri", "status": "active", "telegram_chat_id": 900, "commesse": ["s_bagno", "s_tetto"]},
        {"id": "k2", "owner_user_id": "u1", "first_name": "Pino", "last_name": "Verdi", "status": "active", "telegram_chat_id": 901, "commesse": ["s_bagno"]},
    ]
    today = jl.today_local()
    d = lambda n: (today + timedelta(days=n)).isoformat()
    at = lambda day_off, hm: datetime.combine(today + timedelta(days=day_off), datetime.strptime(hm, "%H:%M").time(), tzinfo=server.LOCAL_TZ).astimezone(timezone.utc)

    # things for Gino today (and one tomorrow, one for Pino): made before 6, nothing is sent yet
    t1 = await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Montare i sanitari", collaborator_id="k1", due_date=d(0)), me)
    await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Tracce cucina", collaborator_id="k1", due_date=d(1)), me)
    m1 = await server.create_milestone("s_tetto", server.MilestonePayload(title="Guaina posata", collaborator_id="k1", due_date=d(0)), me)
    db.job_todos.docs.append({"id": "jtm1", "commessa_id": "s_bagno", "kind": "materiale", "text": "Da prendere: 10 pz scatole 503",
                              "collaborator_id": "k1", "who": "Gino Neri", "due_date": d(0), "done": False, "reminded": {}})
    await settle()
    # (made now, after 6 for real: their message went out at once - start the day again from scratch)
    for c in db.collaborators.docs:
        c.pop("day_pin", None)
    PINS.clear()
    assert await server._collab_day_briefs(at(0, "05:59")) == 0 and not PINS

    # 1) 6:00: Gino's message of the day, pinned; Pino has nothing: none
    assert await server._collab_day_briefs(at(0, "06:00")) == 1
    op, chat, mid, text, kb = PINS[-1]
    print(text)
    assert op == "send" and chat == 900 and len(PINS) == 1
    assert "📋 <b>Oggi," in text and "🏗️ <b>Bagno</b> — Mario Rossi" in text and "maps/search/?api=1&amp;query=Via%20Roma%205%2C%20Torino" in text
    assert "• Montare i sanitari" in text and "• 🧰 Da portare:\n   ◦ 10 pz scatole 503" in text and "🏗️ <b>Tetto</b>" in text and "• 🚩 Guaina posata (milestone)" in text
    assert "Tracce cucina" not in text   # tomorrow's
    assert text.index("Montare i sanitari") < text.index("Da portare")
    assert buttons(kb) == [f"cldone:t:{t1['id']}", "cldone:t:jtm1", f"cldone:m:{m1['id']}"]
    gino = next(c for c in db.collaborators.docs if c["id"] == "k1")
    assert gino["day_pin"]["message_id"] == mid and gino["day_pin"]["date"] == d(0)
    assert await server._collab_day_briefs(at(0, "06:05")) == 0     # once a day
    # the 7:00 reminder of the materials: already in the pinned message
    n = len(TOLD)
    await server._material_reminders(at(0, "07:01"))
    assert len(TOLD) == n

    # 2) ✅ on the pinned message: done, the message edited (struck through), its other buttons kept
    u = FakeUpdate(f"cldone:t:{t1['id']}", mid)
    await ct.handle_callback(u, None, [gino])
    await settle()
    assert u.callback_query.message.replies[-1].startswith("✅ Fatto!") and not u.callback_query.cleared
    op, chat, emid, text, kb = PINS[-1]
    assert op == "edit" and emid == mid and "✅ <s>Montare i sanitari</s>" in text and buttons(kb) == ["cldone:t:jtm1", f"cldone:m:{m1['id']}"]

    # 3) something added for today during the day: in the same message
    t3 = await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Chiudere le tracce", collaborator_id="k1", due_date=d(0)), me)
    await settle()
    assert PINS[-1][0] == "edit" and "• Chiudere le tracce" in PINS[-1][3]
    # unchanged: not edited again
    k = len(PINS)
    assert await server._day_pin_refresh("k1", at(0, "10:00")) == "same" and len(PINS) == k
    # all done: "Tutto fatto", no buttons
    for kind, iid in (("t", "jtm1"), ("m", m1["id"]), ("t", t3["id"])):
        await server._collab_mark_done(gino, kind, iid)
    await settle()
    assert "🎉 Tutto fatto per oggi!" in PINS[-1][3] and PINS[-1][4] is None

    # 4) Pino gets his first thing of the day at 11: sent and pinned then
    await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Portare la scala", collaborator_id="k2", due_date=d(0)), me)
    await settle()
    sends = [p for p in PINS if p[0] == "send" and p[1] == 901]
    assert len(sends) == 1 and "• Portare la scala" in sends[0][3]

    # 5) the next day: yesterday's unpinned, today's sent
    PINS.clear()
    assert await server._collab_day_briefs(at(1, "06:00")) == 1
    assert ("unpin", 900, mid) in [(p[0], p[1], p[2]) for p in PINS]
    assert [p for p in PINS if p[0] == "send" and p[1] == 900] and "• Tracce cucina" in [p for p in PINS if p[0] == "send"][0][3]
    # Pino has nothing: his old one unpinned, no new one
    assert ("unpin", 901) in [(p[0], p[1]) for p in PINS] and not [p for p in PINS if p[0] == "send" and p[1] == 901]
    print("ALL OK")
asyncio.run(main())
