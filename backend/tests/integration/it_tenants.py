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
import tempfile, access as orgaccess, embeddings as emb
from fastapi import HTTPException, Response

# the local file of the administrators ("who subscribed"): two organizations, Alfa and Beta
_f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
_f.write("# test\nboss@alfa.it ; Alfa Srl ; max_users=2 ; max_collaborators=1 ; max_admins=2\ncapo@beta.it ; Beta\n")
_f.close()
os.environ["ORG_ADMINS_FILE"] = _f.name
async def no_emb(q): raise RuntimeError("offline")
Cur.limit = lambda s, n: s
class _NoRows:            # the legacy backfill of the documents list (chunks without a document): none here
    def __aiter__(s): return s
    async def __anext__(s): raise StopAsyncIteration
Coll.aggregate = lambda s, pipeline: _NoRows()
emb.embed_query = no_emb


async def denied(coro, code=403):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == code, (e.status_code, e.detail)
        return e.detail
    raise AssertionError("not denied")


def user(email):
    return server.User(**next(u for u in db.users.docs if u["email"] == email))


async def reg(email, name):
    r = await server.register(server.RegisterRequest(email=email, password="password123", name=name), Response())
    return r["user"]


async def main():
    # 0) the file: who may come in as an administrator; everyone else only when added
    assert orgaccess.parse("a@b.it ; X ; max_users=9 ; junk\nnot-an-email\n# c@d.it")["a@b.it"] == {"org": "X", "plan": {"max_users": 9, "max_collaborators": 5, "max_admins": 1}}
    assert (await server._access_gate("BOSS@alfa.it "))[0] == "admin"
    assert await server._access_gate("nobody@x.it") is None
    assert "non è abilitato" in await denied(reg("nobody@x.it", "Nessuno"))

    # 1) registering: the administrators listed get their own organization
    boss = await reg("boss@alfa.it", "Bruno Alfa")
    capo = await reg("capo@beta.it", "Carla Beta")
    ta, tb = boss["tenant_id"], capo["tenant_id"]
    assert ta and tb and ta != tb and boss["role"] == capo["role"] == "admin"
    assert next(t for t in db.tenants.docs if t["id"] == ta)["name"] == "Alfa Srl"
    B, C = user("boss@alfa.it"), user("capo@beta.it")
    assert server._plan(await server._tenant_of(B)) == {"max_users": 2, "max_collaborators": 1, "max_admins": 2}
    assert server._plan(await server._tenant_of(C)) == orgaccess.DEFAULT_PLAN

    # 2) users: added by e-mail, within the plan; not one of another organization
    await server.invite_tenant_user(server.TenantUserInvite(email="mario@alfa.it"), B)
    await server.invite_tenant_user(server.TenantUserInvite(email="luigi@alfa.it"), B)
    await denied(server.invite_tenant_user(server.TenantUserInvite(email="terzo@alfa.it"), B))          # 2 seats
    assert "un'altra organizzazione" in await denied(server.invite_tenant_user(server.TenantUserInvite(email="boss@alfa.it"), C), 409)
    await denied(server.invite_tenant_user(server.TenantUserInvite(email="capo@beta.it"), B), 409)
    mario = await reg("mario@alfa.it", "Mario Rossi")
    luigi = await reg("luigi@alfa.it", "Luigi Verdi")
    assert mario["tenant_id"] == luigi["tenant_id"] == ta and mario["role"] == "user"
    assert not db.tenant_invites.docs
    M, L = user("mario@alfa.it"), user("luigi@alfa.it")
    me_m = await server.me(M)
    assert not me_m.can_collaborators and me_m.tenant["name"] == "Alfa Srl" and "plan" not in me_m.tenant   # a user: no limits shown
    await denied(server.require_admin(M))

    # 3) isolation: each administrator sees only their own organization
    va, vb = await server.get_tenant(B), await server.get_tenant(C)
    assert {m["email"] for m in va["members"]} == {"boss@alfa.it", "mario@alfa.it", "luigi@alfa.it"} and va["members"][0]["owner"]
    assert {m["email"] for m in vb["members"]} == {"capo@beta.it"}
    assert "members" not in await server.get_tenant(M)
    await denied(server.patch_tenant_user(mario["user_id"], server.TenantUserPatch(suspended=True), C), 404)
    await denied(server.remove_tenant_user(mario["user_id"], C), 404)
    await denied(server.patch_tenant_user(boss["user_id"], server.TenantUserPatch(role="user"), B), 400)     # the subscriber stays

    # teams: of the organization only
    team = await server.admin_create_team(server.OrgCreatePayload(name="Cantieri"), B)
    assert team["tenant_id"] == ta
    assert await server.admin_list_teams(C) == []
    await denied(server.admin_invite_to_team(team["id"], server.TeamInviteCreate(email="capo@beta.it"), C), 404)
    assert "Organizzazione" in await denied(server.admin_invite_to_team(team["id"], server.TeamInviteCreate(email="capo@beta.it"), B), 400)
    await server.admin_invite_to_team(team["id"], server.TeamInviteCreate(email="mario@alfa.it"), B)
    await denied(server.join_org(server.OrgJoinPayload(code=team["join_code"]), C), 404)     # the code alone: not from outside
    await server.join_org(server.OrgJoinPayload(code=team["join_code"]), user("mario@alfa.it"))

    # collaborators: the administrators, within the plan; never seen by another organization
    await denied(server.create_collaborator(server.CollaboratorPayload(first_name="A", last_name="B", phone="333 1111111"), user("mario@alfa.it")))
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Neri", phone="333 1234567"), B)
    assert next(c for c in db.collaborators.docs if c["id"] == r["collaborator"]["id"])["tenant_id"] == ta
    assert "abbonamento" in (await denied(server.create_collaborator(server.CollaboratorPayload(first_name="P", last_name="Q", phone="333 7654321"), B))).lower()
    assert await server.list_collaborators(C) == []
    await denied(server.update_collaborator(r["collaborator"]["id"], server.CollaboratorPayload(first_name="X", last_name="Y"), C), 404) \
        if hasattr(server, "update_collaborator") else None

    # 4) another administrator, if the plan allows (2 here)
    await server.patch_tenant_user(mario["user_id"], server.TenantUserPatch(role="admin"), B)
    assert (await server.me(user("mario@alfa.it"))).can_collaborators
    assert "amministratori" in await denied(server.patch_tenant_user(luigi["user_id"], server.TenantUserPatch(role="admin"), B))

    # 5) the sharing rule: off, only the administrators share
    await server.patch_tenant(server.TenantPatch(users_share=False), B)
    assert not await server._sharing_allowed(user("luigi@alfa.it")) and await server._sharing_allowed(user("mario@alfa.it"))
    F = [server.CollectionFieldDef(key="nome", label="Nome", type="text")]
    assert "amministratore" in await denied(server.create_collection(server.CollectionCreatePayload(name="Fornitori", fields=F, shared_with=["u_x"]), user("luigi@alfa.it")))
    await server.create_collection(server.CollectionCreatePayload(name="Mie note", fields=F), user("luigi@alfa.it"))   # private: fine
    await server.patch_tenant(server.TenantPatch(users_share=True), B)

    # 6) the archive: a user's files go to the administrator's Drive / OneDrive
    assert await server._storage_user(luigi["user_id"]) == boss["user_id"]          # nobody connected yet: the subscriber
    db.integrations.docs.append({"user_id": mario["user_id"], "provider": "google"})
    assert await server._storage_user(luigi["user_id"]) == mario["user_id"]         # the administrator with one connected
    db.integrations.docs.append({"user_id": boss["user_id"], "provider": "microsoft"})
    assert await server._storage_user(luigi["user_id"]) == boss["user_id"]          # the subscriber's first
    assert await server._storage_user(mario["user_id"]) == mario["user_id"]         # an administrator: their own
    assert await server._storage_user(capo["user_id"]) == capo["user_id"]
    assert (await server._storage_owner_view(user("luigi@alfa.it")))["name"] == "Bruno Alfa"
    assert await server._storage_owner_view(B) is None

    # 7) the organization's knowledge: the administrator's document, read by its users only
    now = datetime.now(timezone.utc).isoformat()
    db.kb_documents.docs.append({"doc_id": "d1", "user_id": boss["user_id"], "name": "Procedura ponteggi", "category": "lavoro", "created_at": now})
    db.kb_chunks.docs.append({"chunk_id": "k1", "doc_id": "d1", "user_id": boss["user_id"], "title": "Procedura ponteggi",
                              "text": "Procedura di montaggio dei ponteggi: ancoraggi ogni 4 metri", "created_at": now})
    assert await server.list_kb_documents(user("luigi@alfa.it")) == []
    await denied(server.set_kb_document_org("d1", server.OrgKbPayload(shared=True), user("mario@alfa.it")), 404)   # not his
    await server.set_kb_document_org("d1", server.OrgKbPayload(shared=True), B)
    got = await server.list_kb_documents(user("luigi@alfa.it"))
    assert [d["doc_id"] for d in got] == ["d1"] and got[0]["org_kb"] and not got[0]["mine"]
    assert (await server.list_kb_documents(B))[0]["mine"]
    assert await server.list_kb_documents(C) == []
    await denied(server.delete_kb_document("d1", user("luigi@alfa.it")), 404)      # read-only for the others
    hits = await retrieval.retrieve(db, luigi["user_id"], "procedura ponteggi")
    assert any(h["source"] == "kb" and "ponteggi" in h["text"] for h in hits)
    assert not any("ponteggi" in h["text"] for h in await retrieval.retrieve(db, capo["user_id"], "procedura ponteggi"))
    await server.set_kb_document_org("d1", server.OrgKbPayload(shared=False), B)
    assert await server.list_kb_documents(user("luigi@alfa.it")) == []

    # 8) suspended: no access, data kept; removed: out (and free to join another organization)
    await server.patch_tenant_user(luigi["user_id"], server.TenantUserPatch(suspended=True), B)
    assert await server._access_gate("luigi@alfa.it") is None
    await server.patch_tenant_user(luigi["user_id"], server.TenantUserPatch(suspended=False), B)
    assert (await server._access_gate("luigi@alfa.it"))[0] == "member"
    await server.remove_tenant_user(luigi["user_id"], B)
    assert user("luigi@alfa.it").tenant_id is None and await server._access_gate("luigi@alfa.it") is None
    assert (await server.get_tenant(B))["usage"]["users"] == 1
    await server.invite_tenant_user(server.TenantUserInvite(email="luigi@alfa.it"), C)
    assert user("luigi@alfa.it").tenant_id == tb and (await server._access_gate("luigi@alfa.it"))[0] == "member"

    # 9) the migration of an installation that had only the whitelist (idempotent)
    db2 = DB(); server.db = db2
    os.environ["ORG_ADMINS_FILE"] = _f.name + ".none"           # no file yet: the installation's admin only
    db2.users.docs += [{"user_id": "x1", "email": server.ADMIN_EMAIL, "name": "Luca", "role": "admin"},
                       {"user_id": "x2", "email": "old@b.it", "name": "Old", "role": "user"}]
    db2.allowed_emails.docs += [{"email": "old@b.it"}, {"email": "never@b.it"}]
    db2.organizations.docs.append({"id": "o1", "name": "Squadra", "created_by": "x2"})
    db2.collaborators.docs.append({"id": "c1", "owner_user_id": "x1"})
    for _ in range(2):
        await server._migrate_tenants()
    assert len(db2.tenants.docs) == 1
    main_t = db2.tenants.docs[0]["id"]
    assert {u["user_id"]: (u["tenant_id"], u["role"]) for u in db2.users.docs} == {"x1": (main_t, "admin"), "x2": (main_t, "user")}
    assert [i["email"] for i in db2.tenant_invites.docs] == ["never@b.it"]
    assert db2.organizations.docs[0]["tenant_id"] == main_t and db2.collaborators.docs[0]["tenant_id"] == main_t
    os.unlink(_f.name)
    print("ALL OK")

asyncio.run(main())
