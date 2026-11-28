"""The verticals of an organization, from the organizations' file (verticali=): Impostazioni shows only those; one not
included can't be chosen; one taken off the file is taken off its accounts; with a single one the organization's
administrator (and who is already in a team) gets it by itself."""
import asyncio, copy, os, sys, tempfile
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x", APP_BASE_URL="https://maipal.it/general")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
FILE = os.path.join(tempfile.mkdtemp(), "org_admins.txt")
os.environ["ORG_ADMINS_FILE"] = FILE
import server, access
from fastapi import HTTPException


def _get(doc, k):
    for part in k.split("."):
        doc = (doc or {}).get(part) if isinstance(doc, dict) else None
    return doc


def _match(doc, q):
    for k, v in (q or {}).items():
        if k == "$or":
            if not any(_match(doc, x) for x in v):
                return False
            continue
        val = _get(doc, k)
        if isinstance(v, dict) and any(x.startswith("$") for x in v):
            if "$in" in v and not (val in v["$in"] or (isinstance(val, list) and set(val) & set(v["$in"]))):
                return False
            if "$ne" in v and val == v["$ne"]:
                return False
            if "$nin" in v and val in v["$nin"]:
                return False
        elif isinstance(val, list) and not isinstance(v, list):
            if v not in val:
                return False
        elif val != v:
            return False
    return True


class Cur:
    def __init__(s, d): s.d = d
    def sort(s, f, dr=1): s.d = sorted(s.d, key=lambda x: x.get(f) or "", reverse=dr == -1); return s
    async def to_list(s, n): return [copy.deepcopy(x) for x in (s.d if n is None else s.d[:n])]
    def __aiter__(s):
        s._it = iter(copy.deepcopy(s.d)); return s
    async def __anext__(s):
        try: return next(s._it)
        except StopIteration: raise StopAsyncIteration


class Coll:
    def __init__(s): s.docs = []
    def find(s, q=None, proj=None): return Cur([d for d in s.docs if _match(d, q)])
    async def find_one(s, q=None, proj=None): return next((copy.deepcopy(d) for d in s.docs if _match(d, q)), None)
    async def insert_one(s, d): s.docs.append(copy.deepcopy(d))
    async def update_one(s, q, u, upsert=False):
        if upsert and not any(_match(d, q) for d in s.docs):
            s.docs.append({k: v for k, v in q.items() if not k.startswith("$")})
        for d in s.docs:
            if _match(d, q):
                for k, v in u.get("$set", {}).items():
                    t = d
                    *path, last = k.split(".")
                    for p in path:
                        t = t.setdefault(p, {})
                    t[last] = copy.deepcopy(v)
                for k, v in u.get("$inc", {}).items(): d[k] = (d.get(k) or 0) + v
                return
    async def count_documents(s, q): return len([d for d in s.docs if _match(d, q)])
    async def update_many(s, q, u):
        n = 0
        for d in s.docs:
            if _match(d, q):
                d.update(copy.deepcopy(u.get("$set", {}))); n += 1
        return type("R", (), {"modified_count": n})()
    async def delete_many(s, q): s.docs = [d for d in s.docs if not _match(d, q)]
    async def delete_one(s, q):
        for i, d in enumerate(s.docs):
            if _match(d, q): s.docs.pop(i); return


class DB:
    def __getattr__(s, n):
        c = Coll(); setattr(s, n, c); return c


db = DB()
server.db = db


def write(text):
    with open(FILE, "w", encoding="utf-8") as f:
        f.write(text)
    access._cache["key"] = None


async def fails(coro, status):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == status, (e.status_code, e.detail)
        return e.detail
    raise AssertionError(f"expected {status}")


async def user(uid):
    return server.User(**await db.users.find_one({"user_id": uid}))


async def main():
    # the file: verticali= with one or more, aliases, all, none; unknown names left out
    p = access.parse("a@x.it ; Rossi ; verticali=artigiano\nb@x.it ; Bianchi ; max_users=3 ; verticali=Fitness, veterinari\n"
                     "c@x.it ; Verdi ; verticali=tutti\nd@x.it ; Neri ; verticali=nessuno\ne@x.it ; Gialli ; verticali=pippo")
    assert p["a@x.it"]["verticals"] == ["artigiano"] and p["b@x.it"]["verticals"] == ["fitness", "veterinario"]
    assert p["b@x.it"]["plan"]["max_users"] == 3 and p["c@x.it"]["verticals"] is None and p["d@x.it"]["verticals"] == []
    assert p["e@x.it"]["verticals"] == [] and access.parse("f@x.it")["f@x.it"]["verticals"] is None

    write("anna@rossi.it ; Impresa Rossi ; verticali=artigiano\nluca@palestra.it ; Palestra Luca ; verticali=fitness,veterinario\n")
    for uid, email, role, ten in (("ua", "anna@rossi.it", "admin", "t1"), ("uw", "walter@rossi.it", "user", "t1"),
                                  ("ul", "luca@palestra.it", "admin", "t2")):
        await db.users.insert_one({"user_id": uid, "email": email, "name": uid, "role": role, "tenant_id": ten, "onboarded": True})
    await db.tenants.insert_one({"id": "t1", "name": "Impresa Rossi", "owner_email": "anna@rossi.it", "owner_user_id": "ua"})
    await db.tenants.insert_one({"id": "t2", "name": "Palestra Luca", "owner_email": "luca@palestra.it", "owner_user_id": "ul"})

    # one vertical only: the administrator gets it by itself (its team and lists too); the app knows which ones
    me = await server.me(await user("ua"))
    assert me.business_vertical == "artigiano" and me.tenant["verticals"] == ["artigiano"]
    assert (await db.users.find_one({"user_id": "ua"}))["business_vertical"] == "artigiano"
    assert any(c.get("system_key") == "artigiano_clienti" for c in db.collections.docs)
    # a user not yet in a team: no team made for them, they choose it in Impostazioni (only the one allowed)
    w = await server.me(await user("uw"))
    assert w.business_vertical is None and w.tenant["verticals"] == ["artigiano"]
    msg = await fails(server.update_profile(server.ProfilePatch(business_vertical="fitness"), await user("uw")), 403)
    assert "fitness" in msg and "non è incluso" in msg, msg
    assert (await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), await user("uw"))).business_vertical == "artigiano"

    # two verticals: chosen between those; nothing set by itself
    l = await server.me(await user("ul"))
    assert l.business_vertical is None and l.tenant["verticals"] == ["fitness", "veterinario"]
    await fails(server.update_profile(server.ProfilePatch(business_vertical="artigiano"), await user("ul")), 403)

    # the file changes: a vertical taken off is taken off its accounts (on opening the app, and every 10 minutes)
    await db.users.update_one({"user_id": "ul"}, {"$set": {"business_vertical": "fitness"}})
    write("anna@rossi.it ; Impresa Rossi ; verticali=artigiano\nluca@palestra.it ; Palestra Luca ; verticali=veterinario\n")
    assert await server._sync_tenant_verticals() == 1
    assert (await db.users.find_one({"user_id": "ul"}))["business_vertical"] is None
    await db.users.update_one({"user_id": "uw"}, {"$set": {"business_vertical": "fitness"}})     # (set before the file)
    # (set before the file: off; he is in a team now, so he gets the organization's only one instead)
    assert (await server.me(await user("uw"))).business_vertical == "artigiano"
    # nothing written (or "tutti"): all, as before
    write("anna@rossi.it ; Impresa Rossi\nluca@palestra.it ; Palestra Luca ; verticali=tutti\n")
    assert (await server.me(await user("ul"))).tenant["verticals"] is None
    assert (await server.update_profile(server.ProfilePatch(business_vertical="fitness"), await user("ul"))).business_vertical == "fitness"
    assert await server._sync_tenant_verticals() == 0
    # "nessuno": only the general app
    write("luca@palestra.it ; Palestra Luca ; verticali=nessuno\n")
    assert (await server.me(await user("ul"))).business_vertical is None
    await fails(server.update_profile(server.ProfilePatch(business_vertical="veterinario"), await user("ul")), 403)
    print("ALL OK")


asyncio.run(main())
