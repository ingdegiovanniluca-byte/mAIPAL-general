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
import job_logs as jl, collab_telegram as ct, telegram_bot as tg
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from telegram.ext import ApplicationHandlerStop
import telegram

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77, "tenant_id": "ten_1"}
db.users.docs.append(dict(U))
db.users.docs.append({"user_id": "u2", "email": "x@b.it", "name": "Marco Bianchi", "role": "user", "tenant_id": "ten_1", "org_id": None})
async def uname(): return "maipal_bot"
tg.bot_username = uname
tg.bot_token = lambda: "123:abc"
NOTICES = []
async def fake_send(chat_id, text):
    NOTICES.append((chat_id, text)); return True
server._send_telegram_text = fake_send
BOT_SENT = []
class FakeBot:
    def __init__(self, token=None): pass
    async def send_message(self, chat_id=None, text=None, reply_markup=None, **k): BOT_SENT.append((chat_id, text, reply_markup))
telegram.Bot = FakeBot

def said(kind="nota", text=None, hours=None, problems=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web"):
        f.last = {"speaker": speaker, "team": team, "known": known}
        return {"kind": kind, "doubt": "", "date": jl.today_local().isoformat(), "text": text or t,
                "hours": jl.clean_hours(hours or [], speaker), "materials": [], "problems": problems or [], "client": "", "commessa": ""}
    return f
ANSWERS = []
async def fake_answer(commessa, logs, reports, question, history, user_id=None, channel="web"):
    ANSWERS.append({"view": commessa, "question": question, "history": history})
    return {"answer": "Mancano i sanitari.", "is_entry": False}
jl.answer = fake_answer

# ---- fake Telegram objects ----
REPLIES = []
class Chat:
    def __init__(s, i): s.id = i
class Msg:
    def __init__(s, chat, text=None, contact=None):
        s.chat = Chat(chat); s.text = text; s.contact = contact; s.voice = None; s.photo = None; s.caption = None
    async def reply_text(s, text, reply_markup=None, **k): REPLIES.append((text, reply_markup))
class Upd:
    def __init__(s, chat, text=None, contact=None, uid=500, data=None):
        s.effective_chat = Chat(chat); s.effective_user = type("U", (), {"id": uid})()
        if data:
            s.message = None
            q = type("Q", (), {})(); q.data = data; q.message = Msg(chat)
            async def ans(*a, **k): pass
            async def edit(*a, **k): pass
            q.answer = ans; q.edit_message_reply_markup = edit
            s.callback_query = q
        else:
            s.message = Msg(chat, text, contact); s.callback_query = None
class Bot:
    async def send_chat_action(s, **k): pass
class Ctx: bot = Bot()

async def send(chat, text=None, contact=None, uid=500):
    """-> True when the collaborator gate took the message (the update stopped there)."""
    try:
        await ct.gate(Upd(chat, text, contact, uid), Ctx())
    except ApplicationHandlerStop:
        return True
    return False

async def tap(chat, data):
    try:
        await ct.gate_callback(Upd(chat, data=data), Ctx())
    except ApplicationHandlerStop:
        return True
    return False

def buttons(markup):
    return [b.callback_data for row in (markup.inline_keyboard if markup else []) for b in row]

db.tenants.docs.append({"id": "ten_1", "name": "Impresa Rossi", "owner_user_id": "u1", "owner_email": "a@b.it",
                       "plan": {"max_users": 5, "max_collaborators": 5, "max_admins": 1}, "sharing": {"users_share": True, "collab_contacts": False}})
import verticals as vx, org_settings as osettings


async def deny(coro, code=403):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code in (code if isinstance(code, tuple) else (code,)), (e.status_code, e.detail)
        return e.detail
    raise AssertionError("not denied")


def said2(text=None, problems=None, expenses=None, materials=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web", photos=0):
        return {"kind": "nota", "doubt": "", "date": jl.today_local().isoformat(), "text": text or t, "hours": [],
                "materials": jl.clean_materials(materials or []), "problems": problems or [], "client": "", "commessa": "",
                "expenses": jl.clean_expenses(expenses or [], t)}
    return f


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    MARCO = server.User(**db.users.docs[1])

    # 0) the organization's settings (cap. 7): defaults, a change, a wrong value
    st = await server.get_tenant_settings(me)
    assert st["settings"]["default_start_time"] == "09:00" and st["settings"]["checkin_tolerance_minutes"] == 30
    st = await server.patch_tenant_settings({"daily_summary_time": "20.30", "quote_followup_days": 5, "unknown": 1}, me)
    assert st["settings"]["daily_summary_time"] == "20:30" and st["settings"]["quote_followup_days"] == 5 and "unknown" not in st["settings"]
    assert "Orario" in await deny(server.patch_tenant_settings({"daily_message_time": "25:00"}, me), 400)
    assert (await server._org_settings_for("ten_1"))["daily_summary_time"] == "20:30"
    await deny(server.get_tenant_settings(MARCO) if False else server.require_admin(MARCO))

    # 1) the migration: old states in today's names, a code for every commessa, the new attributes
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    for i, (sid, stato, at) in enumerate([("s_old1", "in corso", "2025-03-01T10:00:00Z"), ("s_old2", "chiusa", "2026-01-05T10:00:00Z"),
                                           ("s_old3", "preventivo", "2026-02-01T10:00:00Z")]):
        db.collection_sub_items.docs.append({"id": sid, "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": f"Lavoro {i}", "stato": stato},
                                             "created_at": at})
    n = await server._migrate_commesse()
    assert n == 3 and await server._migrate_commesse() == 0          # idempotent
    by = {x["id"]: x["data"] for x in db.collection_sub_items.docs}
    assert (by["s_old1"]["stato"], by["s_old2"]["stato"], by["s_old3"]["stato"]) == ("in lavorazione", "completata", "preventivo inviato")
    assert by["s_old1"]["codice"] == "2025-001" and by["s_old2"]["codice"] == "2026-001" and by["s_old3"]["codice"] == "2026-002"
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    sfield = next(f for f in cl["sub_item_fields"] if f["key"] == "stato")
    assert sfield["options"][:8] == vx.COMMESSA_STATI and {"tipo", "cf_piva", "referente"} <= {f["key"] for f in cl["fields"]}
    assert vx.norm_stato("Chiusa") == "completata" and vx.norm_stato("") == "nuova" and vx.is_closed("persa")

    # 2) a commessa from Liste: "nuova", with the next code; only the administrator creates it
    new = await server.create_sub_item(cl["id"], "c_rossi", server.CollectionSubItemPayload(data={"titolo": "Bagno"}), me)
    assert new["data"]["stato"] == "nuova" and new["data"]["codice"] == f"{jl.today_local().year}-{3 if jl.today_local().year == 2026 else 1:03d}"
    # (Marco, a user: the list is not even his to see when not shared; shared with the team, still no)
    await deny(server.create_sub_item(cl["id"], "c_rossi", server.CollectionSubItemPayload(data={"titolo": "Box"}), MARCO), (403, 404))
    cl["visibility"], cl["org_id"] = "org", "o1"
    next(c for c in db.collections.docs if c["id"] == cl["id"]).update(visibility="org", org_id="o1")
    db.users.docs[1]["org_id"] = "o1"; db.users.docs[0]["org_id"] = "o1"
    MARCO = server.User(**db.users.docs[1])
    assert "amministratore" in await deny(server.create_sub_item(cl["id"], "c_rossi", server.CollectionSubItemPayload(data={"titolo": "Box"}), MARCO))
    assert "amministratore" in await deny(server.create_collection_item(cl["id"], server.CollectionItemPayload(data={"nome": "Anna"}), MARCO))
    # users never create commesse by writing either (PA-09)
    jl.interpret = said2()
    r = await server._save_job_log(MARCO, "oggi dai Verdi posato il pavimento", new_client_name="Verdi")
    assert r["status"] == "invalid" and "amministratore" in r["message"]
    assert not any(x["data"].get("nome") == "Verdi" for x in db.collection_items.docs)

    # 3) every change of the parameters is kept (who, when, old, new)
    sid = new["id"]
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    await server.update_sub_item(cl["id"], "c_rossi", sid, server.CollectionSubItemPayload(
        data={**sub["data"], "indirizzo_cantiere": "Via Garibaldi 5", "codice": ""}), me)
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["codice"] == new["data"]["codice"]                        # the code stays
    h = await server._commessa_history(sid)
    assert any(x["field"] == "Indirizzo cantiere" and x["new"] == "Via Garibaldi 5" and x["by_name"] == "Luca" for x in h), h
    await deny(server.update_sub_item(cl["id"], "c_rossi", sid, server.CollectionSubItemPayload(data=sub["data"]), MARCO), (403, 404))

    # 4) states: lost only with its reason; the diary says why
    await deny(server.set_job_commessa_stato(sid, server.CommessaStatoPayload(stato="persa"), me), 400)
    await deny(server.set_job_commessa_stato(sid, server.CommessaStatoPayload(stato="persa", lost_category="altro"), me), 400)
    await deny(server.update_sub_item(cl["id"], "c_rossi", sid, server.CollectionSubItemPayload(data={**sub["data"], "stato": "persa"}), me), 400)
    v = await server.set_job_commessa_stato(sid, server.CommessaStatoPayload(stato="persa", lost_category="prezzo", lost_reason="troppo caro"), me)
    assert v["stato"] == "persa" and v["lost_reason"]["category"] == "prezzo" and v["quote_outcome"] == "perso"
    ev = [lg for lg in db.job_logs.docs if lg["commessa_id"] == sid and lg.get("kind") == "stato"][-1]
    assert "Motivo: Prezzo – troppo caro" in ev["text"]
    v = await server.set_job_commessa_stato(sid, server.CommessaStatoPayload(stato="in lavorazione"), me)
    await deny(server.set_job_commessa_stato(sid, server.CommessaStatoPayload(stato="completata"), MARCO), (403, 404))   # not his to change

    # 5) costs to the users: no, unless the organization says so
    det = await server.get_job_commessa(sid, current=me)
    assert det["economics"] is not None and det["can_see_costs"] and det["is_admin"] and det["history"]
    assert not await server._sees_costs(MARCO)
    await server.patch_tenant(server.TenantPatch(users_see_costs=True), me)
    assert await server._sees_costs(MARCO)
    await server.patch_tenant(server.TenantPatch(users_see_costs=False), me)

    # 6) a note with an expense and a problem; another one solves the problem
    jl.interpret = said2(problems=["manca il miscelatore"], expenses=[{"description": "nastro", "amount": 8}, {"description": "colla", "amount": 5}],
                         materials=[{"name": "cavo 2,5", "qty": 20, "unit": "m", "status": "usato"}])
    r = await server._save_job_log(me, "oggi montate 3 prese in cucina, usati 20 m di cavo 2,5, comprato nastro 8 €, manca il miscelatore",
                                   commessa_id=sid)
    assert r["status"] == "ok" and "💶 Spese: nastro € 8" in r["message"] and "colla" not in r["message"], r["message"]
    econ = next(e for e in db.job_economics.docs if e["commessa_id"] == sid)
    assert [(x["label"], x["amount"], x["log_id"]) for x in econ["extras"]] == [("nastro", 8.0, r["log"]["id"])]
    t = (await server.get_job_commessa(sid, current=me))["totals"]
    assert t["problems"][0]["status"] == "aperta" and t["problems"][0]["severity"] == "media"
    jl.interpret = said2()
    r2 = await server._save_job_log(me, "risolto il problema del miscelatore, montato", commessa_id=sid)
    assert "✅ Risolto: manca il miscelatore" in r2["message"]
    p = (await server.get_job_commessa(sid, current=me))["totals"]["problems"][0]
    assert p["status"] == "risolta" and p["resolved_by"] == "Luca"
    # by hand: open again, severity
    out = await server.patch_job_problem(r["log"]["id"], 0, server.ProblemPatch(resolved=False, severity="alta"), me)
    assert out["status"] == "aperta" and out["severity"] == "alta"

    # 7) a collaborator only sending (WRITE) or also asking (READ_WRITE) on a commessa
    c = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Neri", commesse=[sid]), me)
    cid = c["collaborator"]["id"]
    out = await server.set_commessa_collaborator(sid, cid, server.CollabEnablePayload(enabled=True, level="write"), me)
    assert out["level"] == "write"
    assert [x["level"] for x in await server._assignable_collaborators(sid)] == ["write"]
    assert server._collab_level(next(x for x in db.collaborators.docs if x["id"] == cid), sid) == "write"
    assert server._collab_level({"levels": {}}, sid) == "read_write"
    print("ALL OK")

asyncio.run(main())
