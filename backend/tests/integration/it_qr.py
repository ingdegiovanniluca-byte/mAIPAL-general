"""QR of the organization: the administrator creates one and changes what it shows (the code stays, the old text is
kept in the history); someone of the organization opens it by scanning (or typing the printed code); anyone else gets
"not found" - the same as a wrong code; a new code makes the old label stop working; only web links; only the
administrator manages them."""
import asyncio, copy, os, re, sys
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x", APP_BASE_URL="https://maipal.it/general")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import server, qr_tags as qr
from fastapi import HTTPException


def _match(doc, q):
    return all(doc.get(k) == v for k, v in (q or {}).items())


class Cur:
    def __init__(s, d): s.d = d
    def sort(s, f, dr=1): s.d = sorted(s.d, key=lambda x: x.get(f) or "", reverse=dr == -1); return s
    async def to_list(s, n): return [copy.deepcopy(x) for x in (s.d if n is None else s.d[:n])]


class R:
    def __init__(s, n): s.deleted_count = s.modified_count = n


class Coll:
    def __init__(s): s.docs = []
    def find(s, q=None, proj=None): return Cur([d for d in s.docs if _match(d, q)])
    async def find_one(s, q=None, proj=None): return next((copy.deepcopy(d) for d in s.docs if _match(d, q)), None)
    async def insert_one(s, d): s.docs.append(copy.deepcopy(d))
    async def update_one(s, q, u):
        for d in s.docs:
            if _match(d, q):
                d.update(u.get("$set", {}))
                for k, v in u.get("$inc", {}).items(): d[k] = (d.get(k) or 0) + v
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
admin = server.User(user_id="ua", email="a@x.it", name="Anna Bianchi", role="admin", tenant_id="ten1", org_id="o1")
worker = server.User(user_id="uw", email="w@x.it", name="Walter Neri", role="user", tenant_id="ten1", org_id="o1")
other = server.User(user_id="ux", email="x@y.it", name="Xeno Rossi", role="admin", tenant_id="ten2", org_id="o2")
P = server.QrPayload


async def fails(coro, status):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == status, (e.status_code, e.detail)
        return e.detail
    raise AssertionError(f"expected {status}")


async def main():
    # the code: random, not guessable, readable; typed or scanned in any form
    codes = {qr.new_code() for _ in range(2000)}
    assert len(codes) == 2000 and all(len(c) == 12 and not set(c) & set("0O1IL") for c in codes)
    assert qr.norm_code("k7p3-xq9m 2tra") == "K7P3XQ9M2TRA" == qr.norm_code("https://maipal.it/general/q/K7P3XQ9M2TRA?x=1")
    assert qr.norm_code("ABC") == "" and qr.norm_code("K7P3XQ9M2TR0") == ""

    # only the administrator manages them
    await fails(server.create_qr(P(title="x"), worker), 403)
    await fails(server.list_qr(worker), 403)
    await fails(server.create_qr(P(title="  "), admin), 400)
    await fails(server.create_qr(P(title="x", links=[{"label": "a", "url": "javascript:alert(1)"}]), admin), 400)

    q = await server.create_qr(P(title="Cantiere Rossi · ingresso", kind="cantiere", text="Cancello: codice 4521",
                                 links=[{"label": "", "url": "drive.google.com/file/d/abc"}]), admin)
    assert q["url"] == f"https://maipal.it/general/q/{q['code']}" and re.fullmatch(r"\w{4}-\w{4}-\w{4}", q["code_label"])
    assert q["images"]["svg"].startswith("data:image/svg+xml") and q["images"]["png"].startswith("data:image/png")
    assert q["links"] == [{"label": "drive.google.com", "url": "https://drive.google.com/file/d/abc"}]
    assert (await server.list_qr(admin))["qr"][0]["id"] == q["id"]
    assert (await server.list_qr(other))["qr"] == []

    # what it shows changes, the label (code) stays; the old text in the history
    q2 = await server.update_qr(q["id"], P(text="Cancello: codice 7788"), admin)
    assert q2["code"] == q["code"] and q2["text"] == "Cancello: codice 7788"
    assert q2["versions"][0]["before"]["text"] == "Cancello: codice 4521" and q2["versions"][0]["changed"] == ["text"]
    assert q2["versions"][0]["edited_by_name"] == "Anna"
    assert len((await server.update_qr(q["id"], P(text="Cancello: codice 7788"), admin))["versions"]) == 1   # nothing changed

    # scanned: by the organization (also typed, with dashes); by anyone else as if it didn't exist
    seen = await server.scan_qr(q["code_label"].lower(), worker)
    assert seen["text"] == "Cancello: codice 7788" and seen["can_edit"] is False and "images" not in seen
    assert (await server.scan_qr(q["code"], admin))["can_edit"] is True
    not_found = await fails(server.scan_qr(q["code"], other), 404)
    assert not_found == await fails(server.scan_qr("ZZZZZZZZZZZZ", other), 404)     # the same answer as a wrong code
    for f in (server.get_qr(q["id"], other), server.update_qr(q["id"], P(text="x"), other),
              server.regenerate_qr_code(q["id"], other), server.delete_qr(q["id"], other)):
        await fails(f, 404)
    assert db.qr_codes.docs[0]["text"] == "Cancello: codice 7788" and db.qr_codes.docs[0]["scans"] == 2
    assert len(db.qr_scans.docs) == 2 and {s["user_id"] for s in db.qr_scans.docs} == {"uw", "ua"}

    # only the administrators see it; turned off: only the administrator
    await server.update_qr(q["id"], P(visibility="admins"), admin)
    await fails(server.scan_qr(q["code"], worker), 403)
    await server.update_qr(q["id"], P(visibility="org", active=False), admin)
    await fails(server.scan_qr(q["code"], worker), 410)
    assert (await server.scan_qr(q["code"], admin))["active"] is False
    await server.update_qr(q["id"], P(active=True), admin)

    # a commessa only if the administrator reaches it
    async def access(cur, cid): return None
    server._commessa_access = access
    await fails(server.update_qr(q["id"], P(commessa_id="s_other"), admin), 404)

    # public: anyone who scans it (no login), only what was written for it; private / off / missing: the same answer
    import server as srv
    class Req:
        def __init__(s, ip): s.headers = {"cf-connecting-ip": ip}; s.client = None
    await server.update_qr(q["id"], P(commessa_id=""), admin)
    db.qr_codes.docs[0]["commessa_id"] = "s1"          # (linked to a commessa: never shown publicly)
    private_msg = await fails(server.scan_public_qr(q["code"], Req("1.1.1.1")), 404)
    assert private_msg == await fails(server.scan_public_qr("ZZZZZZZZZZZZ", Req("1.1.1.1")), 404)
    await server.update_qr(q["id"], P(visibility="public"), admin)
    pub = await server.scan_public_qr(q["code_label"], Req("1.1.1.1"))
    assert pub["text"] == "Cancello: codice 7788" and pub["title"] == "Cantiere Rossi · ingresso" and pub["public"] is True
    assert not {"commessa", "commessa_id", "id", "code", "updated_by_name", "last_scan_by_name", "tenant_id", "scans"} & set(pub)
    assert db.qr_codes.docs[0]["public_scans"] == 1
    assert (await server.scan_qr(q["code"], worker))["can_edit"] is False                 # the organization: the full view
    await fails(server.scan_qr(q["code"], other), 404)                                     # (another org: the public view)
    await server.update_qr(q["id"], P(active=False), admin)
    assert await fails(server.scan_public_qr(q["code"], Req("1.1.1.1")), 404) == private_msg
    await server.update_qr(q["id"], P(active=True, visibility="org"), admin)
    # wrong codes from one address: limited
    srv._QR_MISSES.clear()
    for _ in range(srv.QR_MAX_MISSES):
        await fails(server.scan_public_qr("ZZZZZZZZZZZZ", Req("9.9.9.9")), 404)
    await fails(server.scan_public_qr(q["code"], Req("9.9.9.9")), 429)
    await fails(server.scan_public_qr("ZZZZZZZZZZZZ", Req("8.8.8.8")), 404)          # another address: not affected

    # a new code: the old label stops working, the content stays
    q3 = await server.regenerate_qr_code(q["id"], admin)
    assert q3["code"] != q["code"] and q3["text"] == "Cancello: codice 7788"
    await fails(server.scan_qr(q["code"], worker), 404)
    assert (await server.scan_qr(q3["code"], worker))["title"] == "Cantiere Rossi · ingresso"

    # deleted: with its history and scans
    await server.delete_qr(q["id"], admin)
    assert not db.qr_codes.docs and not db.qr_code_versions.docs and not db.qr_scans.docs
    await fails(server.scan_qr(q3["code"], worker), 404)
    print("ALL OK")

asyncio.run(main())
