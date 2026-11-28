"""A tool from the chat: a photo of it (or of its booklet) or its manual is read (only what is written - the model is
faked here), shown as a draft, confirmed into the Attrezzatura list; a file about a tool already in the list fills only
what it doesn't have and goes in its folder (mAIPAL/Attrezzatura/<tool> on Drive, and with the tool in the app); the
files open for who sees the list and from the tool's QR; drafts cancelled or never confirmed leave nothing behind."""
import asyncio, copy, io, json, os, sys
from datetime import datetime, timedelta, timezone
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x", APP_BASE_URL="https://maipal.it/general")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import server, verticals as vx, tool_intake as ti, file_store as fs
from fastapi import HTTPException, UploadFile
from PIL import Image
fs.store = server.fstore.store = fs.MemoryStore()


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
READS = {}          # what the "model" reads in each kind of file


async def fake_llm(system, msg):
    text = getattr(msg[0], "text", "") or ""
    key = "image" if system == ti.SYSTEM_IMAGE else "text"
    return ti.parse_reply(json.dumps(READS.get(key, {})))
server._tool_llm = fake_llm
CLOUD, SAVED = [[]], []


async def targets(uid): return CLOUD[0]
async def storage_user(uid): return uid
async def save(uid, folder, path, filename, ctype, only=None, subfolders=None):
    SAVED.append((folder, tuple(subfolders or []), filename, open(path, "rb").read()[:4]))
    return {"saved": CLOUD[0]}
server._storage_targets = targets
server._storage_user = storage_user
server._storage_save = save


def jpeg():
    b = io.BytesIO(); Image.new("RGB", (40, 30), (200, 80, 20)).save(b, "JPEG"); return b.getvalue()


def up(name, data): return UploadFile(io.BytesIO(data), filename=name)


async def fails(coro, status):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code == status, (e.status_code, e.detail)
        return e.detail
    raise AssertionError(f"expected {status}")


async def main():
    for uid, role, ten, vert in (("ua", "admin", "t1", "artigiano"), ("uw", "user", "t1", "artigiano"), ("ux", "admin", "t2", None)):
        await db.users.insert_one({"user_id": uid, "email": f"{uid}@x.it", "name": uid.upper() + " Rossi", "role": role,
                                   "tenant_id": ten, "org_id": "o1" if ten == "t1" else "o2", "business_vertical": vert})
    U = lambda uid: server.User(**[d for d in db.users.docs if d["user_id"] == uid][0])
    admin, other = U("ua"), U("ux")

    # without the artigiano pack (no Attrezzatura list): said so
    assert "Artigiano" in await fails(server.tools_read([up("x.jpg", jpeg())], "aggiungi", other), 400)
    # not a photo nor a document
    await fails(server.tools_read([up("x.exe", b"MZ")], "", admin), 415)

    # 1) a photo of a new tool: the draft with what is written on it (nothing invented: no price, no date)
    READS["image"] = {"nome": "Smerigliatrice angolare", "marca_modello": "Makita GA9020", "matricola": "SN-77812",
                      "prezzo": None, "documento": "targhetta"}
    r = await server.tools_read([up("IMG_0012.HEIC.jpg", jpeg())], "aggiungi questo attrezzo", admin)
    assert r["status"] == "draft" and not r["draft"]["known"] and r["draft"]["name"] == "Smerigliatrice angolare"
    assert ("Matricola", "SN-77812") in r["draft"]["fields"] and not any(l == "Prezzo" for l, _v in r["draft"]["fields"])
    assert "lista Attrezzatura" in r["message"] and len(fs.store.files) == 1
    ok = await server.tools_draft_confirm(r["draft"]["id"], admin)
    lst = next(c for c in db.collections.docs if c.get("system_key") == vx.ATTREZZI_KEY)
    item = next(i for i in db.collection_items.docs if i["id"] == ok["item_id"])
    assert item["data"] == {"nome": "Smerigliatrice angolare", "marca_modello": "Makita GA9020", "matricola": "SN-77812"}
    assert ok["new"] and len(item["tool_files"]) == 1 and item["tool_files"][0]["kind"] == "image" and item["org_id"] == "o1"
    assert "nell'app" in ok["message"] and "collega Google Drive" in ok["message"] and not SAVED and not db.tool_drafts.docs
    assert "Link utili" in [f["label"] for f in lst["fields"]]

    # 2) later, its manual (a document): the tool of the list is recognized, only what it lacks is added, the file in
    #    its folder on Drive (mAIPAL/Attrezzatura/<tool>) and in the app
    await db.collection_items.update_one({"id": item["id"]}, {"$set": {"data.prezzo": 180}})
    READS["text"] = {"nome": "Smerigliatrice", "marca_modello": "MAKITA GA-9020", "prezzo": "199,00",
                     "frequenza_manutenzione": "ogni 12 mesi", "link": "www.makita.it/ricambi", "documento": "manuale"}
    CLOUD[0] = ["google"]
    r = await server.tools_read([up("Manuale GA9020.txt", b"Manuale d'uso... Manutenzione: ogni 12 mesi")],
                                "questo e il manuale del flessibile makita", admin)
    assert r["draft"]["known"] and "già nella lista" in r["message"] and "Prezzo" not in r["message"]
    assert "ogni anno" in r["message"] and "https://www.makita.it/ricambi" in r["message"]
    ok = await server.tools_draft_confirm(r["draft"]["id"], admin)
    item = next(i for i in db.collection_items.docs if i["id"] == item["id"])
    assert not ok["new"] and item["data"]["prezzo"] == 180                                   # (what was there stays)
    assert item["data"]["frequenza_manutenzione"] == "ogni anno" and item["data"]["link"] == "https://www.makita.it/ricambi"
    assert len(item["tool_files"]) == 2 and item["tool_files"][1]["document"] == "manuale"
    assert SAVED == [("Attrezzatura", ("Smerigliatrice angolare",), "Manuale GA9020.txt", b"Manu")]
    assert "Google Drive" in ok["message"] and "Attrezzatura / Smerigliatrice angolare" in ok["message"]
    assert len([i for i in db.collection_items.docs if i["collection_id"] == lst["id"]]) == 1

    # 3) nothing understood and no name written: asked, nothing kept
    READS["image"] = {"documento": "foto"}
    before = len(fs.store.files)
    r = await server.tools_read([up("x.jpg", jpeg())], "salva", admin)
    assert r["status"] == "unclear" and "nome" in r["message"] and len(fs.store.files) == before
    # ...but a file about a tool named in the message: that tool
    r = await server.tools_read([up("scontrino.jpg", jpeg())], "lo scontrino della Makita GA9020", admin)
    assert r["status"] == "draft" and r["draft"]["known"]
    # cancelled: its files go
    n = len(fs.store.files)
    await server.tools_draft_cancel(r["draft"]["id"], admin)
    assert len(fs.store.files) == n - 1 and not db.tool_drafts.docs
    await fails(server.tools_draft_confirm(r["draft"]["id"], admin), 404)

    # 4) the files: open for who sees the list (the team), not for another organization; on the tool's QR
    fid = item["tool_files"][1]["id"]
    resp = await server.tool_file(item["id"], fid, U("uw"))
    assert resp.body.startswith(b"Manu") and "attachment" in resp.headers["content-disposition"]
    assert "inline" in (await server.tool_file(item["id"], item["tool_files"][0]["id"], U("uw"))).headers["content-disposition"]
    await fails(server.tool_file(item["id"], fid, other), 404)
    q = await server.create_qr(server.QrPayload(title="Flessibile", kind="attrezzo", tool_item_id=item["id"]), admin)
    seen = await server.scan_qr(q["code"], U("uw"))
    assert [f["url"] for f in seen["tool"]["files"]] == [f"tools/{item['id']}/files/{x['id']}" for x in item["tool_files"]]
    # someone else's draft: not theirs
    READS["image"] = {"nome": "Trapano"}
    r = await server.tools_read([up("t.jpg", jpeg())], "", admin)
    await fails(server.tools_draft_confirm(r["draft"]["id"], U("uw")), 404)
    # never confirmed: gone after two days, with its files
    db.tool_drafts.docs[0]["created_at"] = (datetime.now(timezone.utc) - timedelta(hours=49)).isoformat()
    n = len(fs.store.files)
    assert await server._tool_drafts_cleanup() == 1 and len(fs.store.files) == n - 1
    print("ALL OK")


asyncio.run(main())
