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
        elif isinstance(val, list) and not isinstance(v, list):   # an array field matches one of its values
            if v not in val: return False
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

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77, "tenant_id": "ten_1"}
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

import json as _json
import collab_telegram as ct

# the model's answer is faked; interpret's own checks (materials used / to take) run for real
MODEL_SAYS = {}
class _Resp:
    def __init__(s, content): s.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]; s.usage = None
class _Completions:
    async def create(s, **kw): return _Resp(_json.dumps(MODEL_SAYS))
class _Client:
    def __init__(s, **kw): s.chat = type("Ch", (), {"completions": _Completions()})()
jl.openai.AsyncOpenAI = _Client
jl._track = lambda *a, **k: None
def model(text="", hours=None, materials=None, problems=None):
    MODEL_SAYS.clear(); MODEL_SAYS.update({"kind": "nota", "doubt": "", "date": "", "text": text, "hours": hours or [],
                                           "materials": materials or [], "problems": problems or [], "client": "", "commessa": ""})
PUSHED = []
server.push.fire_and_forget = lambda db_, uid, title, body, url="/", tag=None: PUSHED.append((uid, title, body))

class Msg:
    def __init__(s, text): s.text = text; s.location = None; s.voice = None; s.photo = None; s.caption = None; s.contact = None; s.replies = []
    async def reply_text(s, text, **kw): s.replies.append((text, kw.get("reply_markup")))
class Chat:
    id = 900
class Bot:
    async def send_chat_action(s, **kw): pass
class Ctx:
    bot = Bot()
class Upd:
    def __init__(s, msg): s.message = msg; s.callback_query = None; s.effective_chat = Chat()
class Q:
    def __init__(s, data): s.data = data; s.message = Msg(""); s.cleared = False
    async def answer(s): pass
    async def edit_message_reply_markup(s, reply_markup=None): s.cleared = True
class CbUpd:
    def __init__(s, data): s.message = None; s.callback_query = Q(data); s.effective_chat = Chat()
from fastapi import HTTPException

async def denied(coro, code=403):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == code, (e.status_code, e.detail)
        return e.detail
    raise AssertionError("not denied")


# his organization (he is its administrator)
db.tenants.docs.append({"id": "ten_1", "name": "Impresa Rossi", "owner_user_id": "u1", "owner_email": "a@b.it",
                       "plan": {"max_users": 5, "max_collaborators": 5, "max_admins": 2}, "sharing": {"users_share": True, "collab_contacts": False}})

async def main():
    # Luca (admin) and his team: Marco (whitelisted) and Sara; Pia is in another team
    db.users.docs[0].update(org_id="o1", role="admin")
    # Marco and Sara are users of his organization, Pia of another one
    for uid, name, email, org, chat, ten in (("u2", "Marco Bianchi", "marco@b.it", "o1", 78, "ten_1"), ("u3", "Sara Verdi", "sara@v.it", "o1", None, "ten_1"),
                                             ("u4", "Pia Neri", "pia@n.it", "o2", None, "ten_2")):
        db.users.docs.append({"user_id": uid, "email": email, "name": name, "role": "user", "org_id": org, "telegram_chat_id": chat, "tenant_id": ten})
    U2 = lambda: server.User(**next(u for u in db.users.docs if u["user_id"] == "u2"))
    U3 = lambda: server.User(**next(u for u in db.users.docs if u["user_id"] == "u3"))
    U4 = server.User(**next(u for u in db.users.docs if u["user_id"] == "u4"))
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**{**U, "org_id": "o1"}))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    cl["visibility"] = "private"            # his Clienti list is his own: only single commesse are shared
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})

    # 1) a list shared with Marco read-only and with Sara who can edit it
    F = [server.CollectionFieldDef(key="nome", label="Nome", type="text")]
    lst = await server.create_collection(server.CollectionCreatePayload(name="Fornitori", fields=F, shared_with=["u2", "u3", "u4"],
                                                                        share_perms={"u2": "read"}), me)
    assert lst["shared_with"] == ["u2", "u3"] and lst["share_perms"] == {"u2": "read"}      # Pia is not in the team
    assert {u["user_id"]: u["perm"] for u in lst["shared_with_users"]} == {"u2": "read", "u3": "edit"}
    got = await server.get_collection(lst["id"], U2())
    assert got["my_perm"] == "read" and not got["is_owner"]
    assert "sola lettura" in await denied(server.create_collection_item(lst["id"], server.CollectionItemPayload(data={"nome": "Edil"}), U2()))
    assert "sola lettura" in await denied(server.update_collection(lst["id"], server.CollectionUpdatePayload(name="X"), U2()))
    item = await server.create_collection_item(lst["id"], server.CollectionItemPayload(data={"nome": "Edil"}), U3())
    assert item["data"]["nome"] == "Edil"
    await denied(server.delete_collection_item(lst["id"], item["id"], None, U2()))
    # the chat agent never changes a read-only list
    r = await denied(server._execute_list_update(U2(), "aggiungi Ferramenta Rossi ai fornitori"), 400)
    assert "sola lettura" in r
    # shared with the whole team, read-only: Sara now reads only
    out = await server.set_collection_sharing(lst["id"], server.CollectionSharingPayload(visibility="org", org_perm="read"), me)
    assert out["org_perm"] == "read" and out["shared_with"] == []
    assert (await server.get_collection(lst["id"], U3()))["my_perm"] == "read"
    await denied(server.create_collection_item(lst["id"], server.CollectionItemPayload(data={"nome": "B"}), U3()))
    await denied(server.set_collection_sharing(lst["id"], server.CollectionSharingPayload(), U3()))   # only the owner

    # 2) one commessa's diary shared: Marco read-only, Sara can write
    assert not [c for c in await server.list_job_commesse(U2()) if c["id"] == "s_bagno"]
    await denied(server.get_job_commessa("s_bagno", current=U2()), 404)
    NOTICES.clear()
    sh = await server.set_commessa_sharing("s_bagno", server.CommessaSharingPayload(user_ids=["u2", "u3", "u4"], perms={"u2": "read"}), me)
    assert {m["user_id"]: (m["shared"], m["perm"]) for m in sh["members"]} == {"u2": (True, "read"), "u3": (True, "edit")}
    assert any(c == 78 and "ti ha condiviso il diario di «Bagno»" in t and "sola lettura" in t for c, t in NOTICES)
    rows = [c for c in await server.list_job_commesse(U2()) if c["id"] == "s_bagno"]
    assert rows and rows[0]["shared"] and rows[0]["perm"] == "read" and rows[0]["shared_by"] == "Luca Rossi"
    det = await server.get_job_commessa("s_bagno", current=U2())
    assert det["access"] == {"perm": "read", "shared_by": "Luca Rossi", "is_owner": False} and det["shared_count"] == 0
    assert (await server.get_job_commessa("s_bagno", current=me))["shared_count"] == 2
    await server.get_commessa_economics("s_bagno", current=U2())                      # costs: visible
    jl.interpret = said(hours=[{"who": "io", "hours": 2}])
    assert "sola lettura" in await denied(server._save_job_log(U2(), "oggi 2 ore di sopralluogo", commessa_id="s_bagno"))
    await denied(server.create_job_todo("s_bagno", server.JobTodoPayload(text="Ordinare i sanitari"), U2()))
    await denied(server.set_job_commessa_stato("s_bagno", server.CommessaStatoPayload(stato="sospesa"), U2()))
    # Sara writes in it: the entry goes to Luca's commessa
    r = await server._save_job_log(U3(), "oggi 2 ore di sopralluogo", commessa_id="s_bagno")
    assert r["status"] == "ok" and r["log"]["commessa_id"] == "s_bagno" and r["log"]["collection_id"] == cl["id"] and r["log"]["user_id"] == "u3"
    t = await server.create_job_todo("s_bagno", server.JobTodoPayload(text="Ordinare i sanitari"), U3())
    assert t["commessa_id"] == "s_bagno"
    e = await server.patch_job_costs(server.CostsPatch(rates={"Sara": 30}), "s_bagno", U3())   # the rates of Luca's list
    assert next(c for c in db.collections.docs if c["id"] == cl["id"])["costs"]["rates"]["Sara"] == 30
    # only Luca shares it; Pia (another team) never sees it, even if listed
    await denied(server.set_commessa_sharing("s_bagno", server.CommessaSharingPayload(user_ids=["u2"]), U3()))
    next(x for x in db.collection_sub_items.docs if x["id"] == "s_bagno")["shared_with"].append("u4")
    await denied(server.get_job_commessa("s_bagno", current=U4), 404)
    # Marco leaves the team: no more access
    next(u for u in db.users.docs if u["user_id"] == "u2")["org_id"] = None
    await denied(server.get_job_commessa("s_bagno", current=U2()), 404)
    next(u for u in db.users.docs if u["user_id"] == "u2")["org_id"] = "o1"
    # not shared any more
    await server.set_commessa_sharing("s_bagno", server.CommessaSharingPayload(user_ids=["u3"]), me)
    await denied(server.get_job_commessa("s_bagno", current=U2()), 404)

    # 3) collaborators: the organization's administrators (Marco made one, the plan allows 2)
    assert not (await server.me(U2())).can_collaborators
    await server.patch_tenant_user("u2", server.TenantUserPatch(role="admin"), me)
    assert (await server.me(me)).can_collaborators and (await server.me(U2())).can_collaborators
    assert not (await server.me(U3())).can_collaborators
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Neri", phone="333 1234567"), U2())
    assert r["collaborator"]["name"] == "Gino Neri" and next(c for c in db.collaborators.docs if c["id"] == r["collaborator"]["id"])["owner_user_id"] == "u2"
    assert [c["id"] for c in await server.list_collaborators(U2())] == [r["collaborator"]["id"]]
    assert "amministratore" in await denied(server.create_collaborator(server.CollaboratorPayload(first_name="A", last_name="B"), U3()), 403)
    await denied(server.list_collaborators(U3()))
    # not on a team-mate's commessa shared with them (their collaborators work on their own)
    await server.set_commessa_sharing("s_bagno", server.CommessaSharingPayload(user_ids=["u2", "u3"]), me)   # Marco can write in it
    await denied(server.set_commessa_collaborator("s_bagno", r["collaborator"]["id"], server.CollabEnablePayload(enabled=True), U2()), 404)
    await server._save_job_log(U2(), "oggi 2 ore di sopralluogo", commessa_id="s_bagno")       # (but he writes in it)
    print("ALL OK")

asyncio.run(main())
