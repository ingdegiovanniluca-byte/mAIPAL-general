"""QR of the organization: the administrator creates one and changes what it shows (the code stays, the old text is
kept in the history); someone of the organization opens it by scanning (or typing the printed code); anyone else gets
"not found" - the same as a wrong code; a new code makes the old label stop working; only web links; only the
administrator manages them."""
import asyncio, copy, os, re, sys
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x", APP_BASE_URL="https://maipal.it/general")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import io
import server, qr_tags as qr, file_store as fs
from fastapi import HTTPException, UploadFile
fs.store = server.fstore.store = fs.MemoryStore()


def _match(doc, q):
    return all(doc.get(k) == v for k, v in (q or {}).items())


class Cur:
    def __init__(s, d): s.d = d
    def sort(s, f, dr=1): s.d = sorted(s.d, key=lambda x: x.get(f) or "", reverse=dr == -1); return s
    async def to_list(s, n): return [copy.deepcopy(x) for x in (s.d if n is None else s.d[:n])]
    def __aiter__(s):
        s._it = iter(copy.deepcopy(s.d)); return s
    async def __anext__(s):
        try: return next(s._it)
        except StopIteration: raise StopAsyncIteration


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
                for k, v in u.get("$push", {}).items(): d.setdefault(k, []).append(copy.deepcopy(v))
                for k, v in u.get("$pull", {}).items(): d[k] = [x for x in d.get(k, []) if not _match(x, v)]
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
        def __init__(s, ip, geo=None, pass_=None):
            s.headers = {"cf-connecting-ip": ip, **({"x-geo": geo} if geo else {})}; s.client = None
            s.query_params = {"pass": pass_} if pass_ else {}
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

    # ---- files: a photo and a PDF on the QR, opened with the QR's own visibility ----
    from PIL import Image
    from pypdf import PdfWriter
    img = Image.new("RGB", (3000, 2000), (200, 30, 30))
    exif = Image.Exif(); exif[0x8825] = {2: (45.0, 30.0, 0.0)}   # a GPS position in the photo
    buf = io.BytesIO(); img.save(buf, "JPEG", exif=exif); photo = buf.getvalue()
    w = PdfWriter(); w.add_blank_page(595, 842); w.add_blank_page(595, 842); pb = io.BytesIO(); w.write(pb); pdf = pb.getvalue()
    up = lambda data, name: server.upload_qr_file(q["id"], UploadFile(io.BytesIO(data), filename=name), admin)
    d = await up(photo, "cancello.jpeg")
    d = await up(pdf, "../../Planimetria piano 2.PDF")
    fimg, fpdf = d["files"]
    assert (fimg["kind"], fimg["name"], fimg["width"]) == ("image", "cancello.jpg", 2400) and (fpdf["kind"], fpdf["name"], fpdf["pages"]) == ("pdf", "Planimetria piano 2.pdf", 2)
    stored = fs.store.files[fimg["id"]][0]
    assert b"GPS" not in stored and Image.open(io.BytesIO(stored)).getexif().get(0x8825) is None, "the photo's position is dropped"
    assert [v["file_added"]["name"] for v in d["versions"] if v.get("file_added")] == ["Planimetria piano 2.pdf", "cancello.jpg"]
    await fails(server.upload_qr_file(q["id"], UploadFile(io.BytesIO(photo), filename="x.jpg"), worker), 403)
    for bad, name in ((b"<html><script>alert(1)</script></html>", "foto.jpg"), (b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>', "a.svg"),
                      (b"%PDF-1.4 not really a pdf", "x.pdf"), (b"MZ\x90\x00", "x.pdf"), (b"", "vuoto.pdf"), (b"\xff\xd8\xff" + b"0" * (fs.MAX_UPLOAD_BYTES + 1), "big.jpg")):
        await fails(up(bad, name), 400)
    # opened: by the organization (scan), by the admin; never by another organization; publicly only if the QR is public
    cur = db.qr_codes.docs[0]["code"]
    seen = await server.scan_qr(cur, worker)
    assert [f["url"] for f in seen["files"]] == [f"qr/scan/{cur}/files/{fimg['id']}", f"qr/scan/{cur}/files/{fpdf['id']}"]
    resp = await server.scan_qr_file(cur, fpdf["id"], worker)
    assert resp.media_type == "application/pdf" and resp.body == pdf and resp.headers["x-content-type-options"] == "nosniff"
    resp = await server.scan_qr_file(cur, fimg["id"], worker)
    assert resp.media_type == "image/jpeg" and resp.headers["content-security-policy"] == "default-src 'none'"
    await fails(server.scan_qr_file(cur, fimg["id"], other), 404)
    await fails(server.scan_public_qr_file(cur, fimg["id"], Req("2.2.2.2")), 404)        # private QR: not publicly
    await server.update_qr(q["id"], P(visibility="public"), admin)
    assert (await server.scan_public_qr(cur, Req("2.2.2.2")))["files"][1]["url"] == f"qr/public/{cur}/files/{fpdf['id']}"
    assert (await server.scan_public_qr_file(cur, fpdf["id"], Req("2.2.2.2"))).body == pdf
    await fails(server.scan_public_qr_file(cur, "0" * 24, Req("2.2.2.2")), 404)
    await server.update_qr(q["id"], P(visibility="org"), admin)
    # another QR's file through this QR: no
    q_other = await server.create_qr(P(title="Altro"), admin)
    o = await server.upload_qr_file(q_other["id"], UploadFile(io.BytesIO(pdf), filename="altro.pdf"), admin)
    await fails(server.scan_qr_file(cur, o["files"][0]["id"], worker), 404)
    # taken off: who scans no longer sees it, the administrator still opens it from the history
    d = await server.remove_qr_file(q["id"], fpdf["id"], admin)
    assert [f["id"] for f in d["files"]] == [fimg["id"]] and d["versions"][0]["file_removed"]["name"] == "Planimetria piano 2.pdf"
    await fails(server.scan_qr_file(cur, fpdf["id"], worker), 404)
    assert (await server.get_qr_file(q["id"], fpdf["id"], admin)).body == pdf
    await fails(server.get_qr_file(q["id"], fpdf["id"], worker), 403)
    await fails(server.get_qr_file(q["id"], fpdf["id"], other), 404)
    # at most 5
    for i in range(4):
        await up(pdf, f"p{i}.pdf")
    await fails(up(pdf, "sesto.pdf"), 400)
    # a photo of the linked commessa, without uploading it again
    import base64
    async def can_read(cur_, cid, write=True):
        if cid != "s1": raise HTTPException(status_code=404, detail="Commessa non trovata")
        return {}, {}, {}
    server._commessa_or_404 = can_read
    db.job_photos.docs += [{"id": "ph1", "commessa_id": "s1", "data_b64": base64.b64encode(photo).decode(), "created_at": "2026-11-20T10:00:00"},
                           {"id": "ph9", "commessa_id": "s9", "data_b64": base64.b64encode(photo).decode()}]
    await server.remove_qr_file(q["id"], fimg["id"], admin)
    assert [p["id"] for p in await server.qr_commessa_photos(q["id"], admin)] == ["ph1"]          # (the QR is linked to s1)
    d = await server.add_qr_file_from_photo(q["id"], server.QrPhotoPayload(photo_id="ph1"), admin)
    assert d["files"][-1]["name"] == "Foto 2026-11-20.jpg"
    await fails(server.add_qr_file_from_photo(q["id"], server.QrPhotoPayload(photo_id="ph9"), admin), 404)   # another commessa's
    await server.delete_qr(q_other["id"], admin)
    assert o["files"][0]["id"] not in fs.store.files and len(fs.store.files) == 7   # (q: 5 on it + 2 taken off, in its history)

    # ---- augmented reality: a 3D model (GLB) or a photo of the QR, shown on the label ----
    import struct
    js = b'{"asset":{"version":"2.0"},"scenes":[{"nodes":[]}]}'
    js += b" " * (-len(js) % 4)
    glb = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(js)) + struct.pack("<II", len(js), 0x4E4F534A) + js
    aq = await server.create_qr(P(title="Impianto sotto traccia"), admin)
    await fails(server.upload_qr_file(aq["id"], UploadFile(io.BytesIO(glb[:-4]), filename="tubi.glb"), admin), 400)    # length wrong
    await fails(server.upload_qr_file(aq["id"], UploadFile(io.BytesIO(b"glTF" + struct.pack("<II", 1, 12)), filename="v1.glb"), admin), 400)
    d = await server.upload_qr_file(aq["id"], UploadFile(io.BytesIO(glb), filename="Tubi bagno.GLTF"), admin)
    mfile = d["files"][0]
    assert (mfile["kind"], mfile["name"]) == ("model", "Tubi bagno.glb")
    d = None
    def sized_glb(n):   # a valid GLB of n bytes (a JSON chunk of 8 bytes, then filler)
        return b"glTF" + struct.pack("<II", 2, n) + struct.pack("<II", 8, 0x4E4F534A) + b"0" * (n - 20)
    d = await server.upload_qr_file(aq["id"], UploadFile(io.BytesIO(sized_glb(fs.MAX_UPLOAD_BYTES + 100)), filename="big.glb"), admin)
    assert d["files"][-1]["size"] > fs.MAX_UPLOAD_BYTES                     # a model may be over 10 MB...
    await server.remove_qr_file(aq["id"], d["files"][-1]["id"], admin)
    await fails(server.upload_qr_file(aq["id"], UploadFile(io.BytesIO(sized_glb(fs.MAX_MODEL_BYTES + 100)), filename="huge.glb"), admin), 400)  # ...not over 25
    # AR settings: only with a model / photo of the QR; clamped values; out without
    await fails(server.update_qr(aq["id"], P(ar={"on": True, "file_id": "nope"}), admin), 400)
    d = await server.update_qr(aq["id"], P(ar={"on": True, "file_id": mfile["id"], "label": "frame", "label_cm": 10,
                                               "offset_cm": [0, -30, 5], "rot_deg": [90, 0, 400], "scale": 1}), admin)
    ar = d["ar"]
    assert ar["kind"] == "model" and ar["label"] == "frame" and ar["offset_cm"] == [0, -30, 5] and ar["rot_deg"] == [90, 0, 360]
    assert ar["url"] == f"qr/{aq['id']}/files/{mfile['id']}" and ar["qr_modules"] >= 21
    seen = await server.scan_qr(aq["code"], worker)
    assert seen["ar"]["url"] == f"qr/scan/{aq['code']}/files/{mfile['id']}"
    resp = await server.scan_qr_file(aq["code"], mfile["id"], worker)
    assert resp.media_type == "model/gltf-binary" and resp.body == glb and resp.headers["x-content-type-options"] == "nosniff"
    await fails(server.update_qr(aq["id"], P(ar={"on": True, "file_id": mfile["id"], "label_cm": 0.5}), admin), 400)
    assert (await server.get_qr(aq["id"], admin))["versions"][0]["changed"] == ["ar"]
    d = await server.remove_qr_file(aq["id"], mfile["id"], admin)       # its model taken off: no AR
    assert d["ar"] is None and db.qr_codes.docs[-1].get("ar") is None
    await server.delete_qr(aq["id"], admin)

    # ---- a QR that opens only in one place (within the radius of the phone's position) ----
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    await fails(server.create_qr(P(title="x", place={"on": True}), admin), 400)
    await fails(server.create_qr(P(title="x", place={"on": True, "lat": 46.5, "lon": 11.35, "radius_m": 5}), admin), 400)
    assert (await server.create_qr(P(title="ovunque", place={"on": False}), admin))["place"] is None
    gq = await server.create_qr(P(title="Locale tecnico", text="Codice armadio 1234", visibility="org",
                                  place={"on": True, "lat": 46.5, "lon": 11.35, "radius_m": 100, "label": "Cantiere Rossi"}), admin)
    assert gq["place"] == {"on": True, "lat": 46.5, "lon": 11.35, "radius_m": 100, "label": "Cantiere Rossi"}
    gfile = (await server.upload_qr_file(gq["id"], UploadFile(io.BytesIO(pdf), filename="schema.pdf"), admin))["files"][0]["id"]
    gc = gq["code"]
    need = await fails(server.scan_qr(gc, worker, Req("1.1.1.1")), 428)
    assert need["reason"] == "need" and "Cantiere Rossi" in need["message"] and "Codice" not in str(need)
    far = await fails(server.scan_qr(gc, worker, Req("1.1.1.1", "46.51,11.35,10")), 428)
    assert far["reason"] == "far" and 1050 < far["distance_m"] < 1200 and "1,1 km" in far["message"], far
    assert (await fails(server.scan_qr(gc, worker, Req("1.1.1.1", "46.5003,11.35,800")), 428))["reason"] == "imprecise"
    assert (await fails(server.scan_qr(gc, worker, Req("1.1.1.1", "46.5,11.35,abc")), 428))["reason"] == "need"
    here = await server.scan_qr(gc, worker, Req("1.1.1.1", "46.5003,11.35,15"))          # ~33 m away
    assert here["text"] == "Codice armadio 1234" and "place_note" not in here
    assert db.qr_scans.docs[-1]["distance_m"] == 33 and "lat" not in db.qr_scans.docs[-1]   # (how far, not where)
    url = here["files"][0]["url"]; token = url.split("?pass=")[1]
    assert url.startswith(f"qr/scan/{gc}/files/{gfile}?pass=")
    await fails(server.scan_qr_file(gc, gfile, worker, Req("1.1.1.1")), 403)                  # no pass: no file
    assert (await server.scan_qr_file(gc, gfile, worker, Req("1.1.1.1", pass_=token))).body == pdf
    # a pass is for its QR only, and expires
    other_q = await server.create_qr(P(title="altro", place={"on": True, "lat": 46.5, "lon": 11.35, "radius_m": 100}), admin)
    ofile = (await server.upload_qr_file(other_q["id"], UploadFile(io.BytesIO(pdf), filename="o.pdf"), admin))["files"][0]["id"]
    await fails(server.scan_qr_file(other_q["code"], ofile, worker, Req("1.1.1.1", pass_=token)), 403)
    next(p_ for p_ in db.qr_passes.docs if p_["token"] == token)["until"] = _dt.now(_tz.utc) - _td(seconds=1)
    await fails(server.scan_qr_file(gc, gfile, worker, Req("1.1.1.1", pass_=token)), 403)
    # the administrator: anywhere (to manage it), told so
    adm = await server.scan_qr(gc, admin, Req("1.1.1.1"))
    assert adm["text"] and adm["place_note"] and (await server.scan_qr_file(gc, gfile, admin, Req("1.1.1.1"))).body == pdf
    # public and in one place: who has no account too, only there; the place's name not shown to them
    await server.update_qr(gq["id"], P(visibility="public"), admin)
    pneed = await fails(server.scan_public_qr(gc, Req("5.5.5.5")), 428)
    assert pneed["reason"] == "need" and pneed["label"] == "" and "Cantiere Rossi" not in pneed["message"]
    await fails(server.scan_public_qr(gc, Req("5.5.5.5", "45.0,9.0,10")), 428)
    pub_here = await server.scan_public_qr(gc, Req("5.5.5.5", "46.5,11.3501,10"))
    ptok = pub_here["files"][0]["url"].split("?pass=")[1]
    await fails(server.scan_public_qr_file(gc, gfile, Req("5.5.5.5")), 403)
    assert (await server.scan_public_qr_file(gc, gfile, Req("5.5.5.5", pass_=ptok))).body == pdf
    # turned off: anywhere again; the change is in the history
    d = await server.update_qr(gq["id"], P(place={"on": False}), admin)
    assert d["place"] is None and d["versions"][0]["changed"] == ["place"] and d["versions"][0]["before"]["place"]["label"] == "Cantiere Rossi"
    assert (await server.scan_qr(gc, worker, Req("1.1.1.1")))["text"] == "Codice armadio 1234"
    for x in (gq, other_q):
        await server.delete_qr(x["id"], admin)
    for x in list(db.qr_codes.docs):
        if x["title"] == "ovunque":
            await server.delete_qr(x["id"], admin)

    # a new code: the old label stops working, the content stays
    q3 = await server.regenerate_qr_code(q["id"], admin)
    assert q3["code"] != q["code"] and q3["text"] == "Cancello: codice 7788"
    await fails(server.scan_qr(q["code"], worker), 404)
    assert (await server.scan_qr(q3["code"], worker))["title"] == "Cantiere Rossi · ingresso"

    # deleted: with its history and scans
    await server.delete_qr(q["id"], admin)
    assert not db.qr_codes.docs and not db.qr_code_versions.docs and not db.qr_scans.docs
    assert not fs.store.files, "its files go too, also the ones in the history"
    await fails(server.scan_qr(q3["code"], worker), 404)
    print("ALL OK")

asyncio.run(main())
