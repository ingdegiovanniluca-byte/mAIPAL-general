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


async def main():
    # Luca is the administrator (no team yet); Marco is already in another team (Gamma)
    db.users.docs[0].update(role="admin", org_id=None)
    db.organizations.docs.append({"id": "org_g", "name": "Gamma", "join_code": "GGGGGG", "created_by": "u9"})
    db.users.docs.append({"user_id": "u2", "email": "marco@b.it", "name": "Marco Bianchi", "role": "user", "org_id": "org_g",
                          "org_role": "member", "telegram_chat_id": 78})
    db.users.docs.append({"user_id": "u3", "email": "sara@v.it", "name": "Sara Verdi", "role": "user", "org_id": None})
    get = lambda uid: server.User(**next(u for u in db.users.docs if u["user_id"] == uid))
    me = lambda: get("u1")

    # 1) a new team: whoever creates it is in it (and active there, having no other)
    a = await server.admin_create_team(server.OrgCreatePayload(name="Alpha"), me())
    assert [m["user_id"] for m in a["members"]] == ["u1"] and me().org_id == a["id"]
    org = await server.get_org(me())
    assert org["name"] == "Alpha" and [m["user_id"] for m in org["members"]] == ["u1"]
    b = await server.admin_create_team(server.OrgCreatePayload(name="Beta"), me())
    assert me().org_id == a["id"] and set(me().org_ids) == {a["id"], b["id"]}       # still active in Alpha
    assert {t["name"]: t["active"] for t in (await server.get_org(me()))["teams"]} == {"Alpha": True, "Beta": False}

    # 2) Marco, already in Gamma, is invited to Alpha: he sees it (and is told), accepts it, no code
    NOTICES.clear()
    await server.admin_invite_to_team(a["id"], server.TeamInviteCreate(email="Marco@B.it"), me())
    assert any(c == 78 and "ti ha invitato nel team «Alpha»" in t for c, t in NOTICES)
    inv = (await server.get_org(get("u2")))["invites"]
    assert [(i["org_id"], i["name"]) for i in inv] == [(a["id"], "Alpha")]
    await server.accept_team_invite(a["id"], get("u2"))
    m2 = get("u2")
    assert m2.org_id == "org_g" and set(m2.org_ids) == {"org_g", a["id"]}          # in both, Gamma still active
    assert not (await server.get_org(m2))["invites"]
    assert {m["user_id"] for m in (await server.get_org(me()))["members"]} == {"u1", "u2"}   # Alpha's members
    await denied(server.accept_team_invite(a["id"], get("u2")), 400)
    await denied(server.admin_invite_to_team(a["id"], server.TeamInviteCreate(email="marco@b.it"), me()), 400)
    # a list Luca shares with Marco in Alpha: Marco sees it, whatever his active team
    F = [server.CollectionFieldDef(key="nome", label="Nome", type="text")]
    lst = await server.create_collection(server.CollectionCreatePayload(name="Fornitori", fields=F, shared_with=["u2"]), me())
    assert lst["shared_with"] == ["u2"]
    assert (await server.get_collection(lst["id"], get("u2")))["my_perm"] == "edit"
    # the active team is his to choose
    await server.switch_org(server.OrgSwitchPayload(org_id=a["id"]), get("u2"))
    assert get("u2").org_id == a["id"] and (await server.get_org(get("u2")))["name"] == "Alpha"
    await denied(server.switch_org(server.OrgSwitchPayload(org_id=b["id"]), get("u2")), 404)
    # leaving the active one: back to the other
    await server.leave_org(server.OrgLeavePayload(org_id=a["id"]), get("u2"))
    assert get("u2").org_id == "org_g" and get("u2").org_ids == ["org_g"]
    await denied(server.get_collection(lst["id"], get("u2")), 404)

    # 3) Sara: invited to Beta, declines; then with the code into Alpha (invited)
    await server.admin_invite_to_team(b["id"], server.TeamInviteCreate(email="sara@v.it"), me())
    await server.decline_team_invite(b["id"], get("u3"))
    assert not (await server.get_org(get("u3")) or {}).get("invites")
    await denied(server.join_org(server.OrgJoinPayload(code=a["join_code"]), get("u3")), 403)        # not invited
    await server.admin_invite_to_team(a["id"], server.TeamInviteCreate(email="sara@v.it"), me())
    await server.join_org(server.OrgJoinPayload(code=a["join_code"].lower()), get("u3"))
    assert get("u3").org_id == a["id"]

    # 4) the administrator inviting himself: simply in
    c = await server.admin_create_team(server.OrgCreatePayload(name="Delta"), me())
    await server.leave_org(server.OrgLeavePayload(org_id=c["id"]), me())
    assert c["id"] not in me().org_ids
    r = await server.admin_invite_to_team(c["id"], server.TeamInviteCreate(email=me().email), me())
    assert r.get("joined") and c["id"] in me().org_ids

    # 5) removed from a team / team deleted: memberships follow, the active one falls back
    await server.admin_remove_team_member(a["id"], "u3", me())
    assert get("u3").org_id is None and get("u3").org_ids == []
    await server.switch_org(server.OrgSwitchPayload(org_id=b["id"]), me())
    await server.admin_delete_team(b["id"], me())
    assert me().org_id in (a["id"], c["id"]) and b["id"] not in me().org_ids
    print("ALL OK")

asyncio.run(main())
