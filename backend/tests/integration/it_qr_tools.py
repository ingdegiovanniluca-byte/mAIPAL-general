"""A tool's QR (artigiani): the Attrezzatura list is made by itself; a tool's QR is linked to a tool of the list (the
one chosen, else the one with its name, else a new one); scanned, whoever is in the organization takes the tool or
gives it back, the QR and the list say who has it and since when, every move is kept."""
import asyncio, copy, os, sys
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x", APP_BASE_URL="https://maipal.it/general")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import server, verticals as vx
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
    async def update_one(s, q, u):
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
    async def delete_many(s, q): s.docs = [d for d in s.docs if not _match(d, q)]
    async def delete_one(s, q):
        for i, d in enumerate(s.docs):
            if _match(d, q): s.docs.pop(i); return


class DB:
    def __getattr__(s, n):
        c = Coll(); setattr(s, n, c); return c


db = DB()
server.db = db
U = lambda uid, name, role, ten, org, vert="artigiano": server.User(user_id=uid, email=f"{uid}@x.it", name=name, role=role,
                                                                   tenant_id=ten, org_id=org, business_vertical=vert)
admin = U("ua", "Anna Bianchi", "admin", "ten1", "o1")
walter = U("uw", "Walter Neri", "user", "ten1", "o1")
gino = U("ug", "Gino Verdi", "user", "ten1", "o1")
other = U("ux", "Xeno Rossi", "admin", "ten2", "o2", vert=None)
P = server.QrPayload
A = server.QrToolAction


async def fails(coro, status):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == status, (e.status_code, e.detail)
        return e.detail
    raise AssertionError(f"expected {status}")


def tool_list():
    return [c for c in db.collections.docs if c.get("system_key") == vx.ATTREZZI_KEY]


def item(iid):
    return next(i for i in db.collection_items.docs if i["id"] == iid)


async def main():
    for u in (admin, walter, gino, other):
        await db.users.insert_one({"user_id": u.user_id, "name": u.name, "org_id": u.org_id, "org_ids": [u.org_id]})

    # a tool's QR: the Attrezzatura list is made, the tool goes in it with the QR's name
    q = await server.create_qr(P(title="Trapano Hilti", kind="attrezzo"), admin)
    assert len(tool_list()) == 1 and tool_list()[0]["visibility"] == "org" and tool_list()[0]["name"] == "Attrezzatura"
    lst = tool_list()[0]
    labels = [f["label"] for f in lst["fields"]]
    assert labels[:3] == ["Nome", "Marca e modello", "Matricola"] and "Data ultima revisione / riparazione" in labels and labels[-2:] == ["Ce l'ha", "Dal"]
    assert q["tool"] == {"item_id": q["tool"]["item_id"], "name": "Trapano Hilti", "holder": None, "files": []}
    assert item(q["tool"]["item_id"])["data"] == {"nome": "Trapano Hilti"} and item(q["tool"]["item_id"])["org_id"] == "o1"
    # the same name again: the same tool, not a copy
    q_same = await server.create_qr(P(title="trapano hilti ", kind="attrezzo"), admin)
    assert q_same["tool"]["item_id"] == q["tool"]["item_id"] and len(db.collection_items.docs) == 1
    # a tool of the list chosen
    await db.collection_items.insert_one({"id": "item_flex", "collection_id": lst["id"], "data": {"nome": "Flessibile Makita"}})
    tools = await server.qr_tools(admin)
    assert [t["name"] for t in tools["items"]] == ["Flessibile Makita", "Trapano Hilti"] and tools["list"]["id"] == lst["id"]
    q2 = await server.create_qr(P(title="Smerigliatrice furgone 2", kind="attrezzo", tool_item_id="item_flex"), admin)
    assert q2["tool"]["name"] == "Flessibile Makita" and len(db.collection_items.docs) == 2
    await fails(server.create_qr(P(title="x", kind="attrezzo", tool_item_id="nope"), admin), 404)
    await fails(server.qr_tools(walter), 403)

    # scanned by a worker: nobody has it; «Prendi»
    seen = await server.scan_qr(q["code"], walter)
    assert seen["tool"]["holder"] is None and seen["pass"] is None
    r = await server.qr_tool_action(q["code"], A(action="take"), walter)
    assert r["tool"]["holder"]["name"] == "Walter Neri" and r["tool"]["holder"]["mine"] is True
    it = item(q["tool"]["item_id"])["data"]
    assert it["preso_da"] == "Walter Neri" and len(it["preso_il"]) == 10
    assert (await server.qr_tool_action(q["code"], A(action="take"), walter))["tool"]["holder"]["mine"] is True   # (twice: once)
    seen = await server.scan_qr(q["code"], admin)
    assert seen["tool"]["holder"]["name"] == "Walter Neri" and seen["tool"]["holder"]["mine"] is False
    # a colleague takes it from him; Walter can't give back what he no longer has
    await server.qr_tool_action(q["code"], A(action="take"), gino)
    msg = await fails(server.qr_tool_action(q["code"], A(action="return"), walter), 403)
    assert "Gino" in msg
    assert db.qr_tool_moves.docs[-1]["from_name"] == "Walter Neri"
    # «Restituisci»: nobody has it, the list says so too
    r = await server.qr_tool_action(q["code"], A(action="return"), gino)
    assert r["tool"]["holder"] is None and item(q["tool"]["item_id"])["data"]["preso_da"] == ""
    # the administrator gives back a tool for whoever has it
    await server.qr_tool_action(q["code"], A(action="take"), walter)
    assert (await server.qr_tool_action(q["code"], A(action="return"), admin))["tool"]["holder"] is None
    full = await server.get_qr(q["id"], admin)
    assert [m["action"] for m in full["tool_moves"]][:2] == ["return", "take"] and len(full["tool_moves"]) == 5

    # a QR that opens only on the spot: taken only with the scan's pass
    db.qr_codes.docs[0]["place"] = {"on": True, "lat": 46.5, "lon": 11.35, "radius_m": 100}
    await fails(server.qr_tool_action(q["code"], A(action="take"), walter), 403)
    token = await server._qr_pass(db.qr_codes.docs[0], "uw")
    assert (await server.qr_tool_action(q["code"], A(action="take", token=token), walter))["tool"]["holder"]["mine"]
    db.qr_codes.docs[0]["place"] = None

    # not a tool: no buttons, no tool; changed into another kind: no tool any more
    site = await server.create_qr(P(title="Cantiere Rossi", kind="cantiere"), admin)
    assert site["tool"] is None
    await fails(server.qr_tool_action(site["code"], A(action="take"), walter), 400)
    changed = await server.update_qr(q2["id"], P(kind="punto"), admin)
    assert changed["tool"] is None and db.qr_codes.docs[2].get("tool_item_id") is None
    # ...and back to a tool: linked again by its name (a new tool in the list)
    back = await server.update_qr(q2["id"], P(kind="attrezzo"), admin)
    assert back["tool"]["name"] == "Smerigliatrice furgone 2" and len(db.collection_items.docs) == 3

    # another organization: never sees or moves these tools; without the artigiano pack no list is made
    await fails(server.qr_tool_action(q["code"], A(action="take"), other), 404)
    oq = await server.create_qr(P(title="Scala", kind="attrezzo"), other)
    assert oq["tool"] == {"item_id": None, "name": None, "holder": None, "files": []} and len(tool_list()) == 1
    r = await server.qr_tool_action(oq["code"], A(action="take"), other)          # (the QR alone still says who has it)
    assert r["tool"]["holder"]["name"] == "Xeno Rossi"

    # deleted: its moves go too
    await server.delete_qr(q["id"], admin)
    assert not [m for m in db.qr_tool_moves.docs if m["qr_id"] == q["id"]]
    print("ALL OK")


asyncio.run(main())
