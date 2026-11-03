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


import io, base64
from datetime import date as _date
from PIL import Image
import archive_names as an


async def deny(coro, code=403):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code in (code if isinstance(code, tuple) else (code,)), (e.status_code, e.detail)
        return e.detail
    raise AssertionError("not denied")


def jpeg_uri():
    buf = io.BytesIO(); Image.new("RGB", (40, 30), (200, 80, 80)).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


# the archive: one Drive, made of folders and files kept here
FOLDERS, SAVED = [], []
DRIVE = {"up": True}
async def fake_targets(uid): return ["google"] if DRIVE["up"] else []
async def fake_path(current, folder, subs):
    FOLDERS.append(" / ".join([folder] + list(subs)))
    return {"name": " / ".join([folder] + list(subs)), "ids": {"google": "f1"}, "links": {"google": "https://drive/f/" + str(len(FOLDERS))}}
async def fake_save(user_id, folder, tmp_path, filename, ctype, only=None, subfolders=None):
    if DRIVE.get("fail"):
        raise HTTPException(status_code=500, detail="Drive non risponde")
    SAVED.append((" / ".join([folder] + list(subfolders or [])), filename))
    return {"saved": ["google"], "links": {"google": f"https://drive/{filename}"}, "web_view_link": f"https://drive/{filename}", "errors": {}}
server._storage_targets = fake_targets
server._ensure_storage_path = fake_path
server._storage_save = fake_save
async def new_job(text, user_id=None, channel="web"):
    return dict(NEXT_JOB)
jl.read_new_commessa = new_job
NEXT_JOB = {}


async def main():
    # 0) names and folders (AUT-GEN-06/07)
    assert an.describe("foto del tetto, sopralluogo del 28 ottobre") == "tetto"
    assert an.file_name("sopralluogo", _date(2026, 10, 28), "foto del tetto, sopralluogo del 28 ottobre", "JPG") == "sopralluogo_20261028_tetto.jpg"
    assert an.file_name("sopralluogo", _date(2026, 11, 2), "", "jpg") == "sopralluogo_20261102.jpg"
    assert an.file_name("lavori", _date(2026, 11, 2), "Impianto elettrico della cucina", "pdf") == "lavori_20261102_impianto-elettrico.pdf"
    assert an.file_name("preventivo", _date(2026, 11, 2), "", "pdf", version=2) == "preventivo_20261102_v2.pdf"
    assert an.unique("a_1.jpg", ["a_1.jpg", "a_1_02.jpg"]) == "a_1_03.jpg" and an.unique("x.jpg", []) == "x.jpg"
    assert an.commessa_folder("2026-015", "Rifacimento  bagno") == "2026-015 – Rifacimento bagno"

    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    MARCO = server.User(**db.users.docs[1])

    # 1) a new commessa from a message: what is missing is asked, nothing invented
    NEXT_JOB.update(client="", title="Rifacimento bagno", address="", start="", end="", value=None, description="")
    r = await server._save_job_log(me, "Nuova commessa per rifacimento bagno", channel="telegram")
    assert r["status"] == "unclear" and "il cliente" in r["message"]
    # a user never creates it
    r = await server._save_job_log(MARCO, "Nuova commessa per Mario Rossi, rifacimento bagno")
    assert r["status"] == "invalid" and "amministratore" in r["message"]

    # 2) a client with a similar name: asked which one (AUT-CRE-01)
    NEXT_JOB.update(client="Mario Rosi", title="Rifacimento bagno", address="via Garibaldi 5, Torino", start="2026-11-10", value=8500)
    r = await server._save_job_log(me, "Nuova commessa per Mario Rosi, rifacimento bagno in via Garibaldi 5 a Torino, inizio 10 novembre, 8.500 euro",
                                   channel="telegram")
    assert r["status"] == "commessa_draft", r
    keys = [o["key"] for o in r["draft"]["options"]]
    assert keys == ["c:c_rossi", "new", "no"] and "nome simile: Mario Rossi" in r["message"] and "💶 Valore: € 8.500" in r["message"]
    assert "inizio 10/11" in r["message"] or "inizio 10 nov" in r["message"], r["message"]
    await deny(server.confirm_commessa_draft(r["draft"]["id"], server.DraftConfirmPayload(choice="ok"), me), 400)   # which client first
    out = await server.confirm_commessa_draft(r["draft"]["id"], server.DraftConfirmPayload(choice="c:c_rossi"), me)
    v = out["commessa"]
    assert out["status"] == "created" and v["client_name"] == "Mario Rossi" and v["stato"] == "nuova" and v["codice"] == f"{jl.today_local().year}-001"
    assert v["address"] == "via Garibaldi 5, Torino" and v["data_inizio"] == "2026-11-10"
    assert next(e for e in db.job_economics.docs if e["commessa_id"] == v["id"])["budget"] == 8500
    assert any(h["field"] == "Creata" for h in await server._commessa_history(v["id"]))
    # the folders: the commessa's in its client's, and its phase folders (AUT-CRE-02, AUT-GEN-06)
    base = f"Clienti / Mario Rossi / {v['codice']} – Rifacimento bagno"
    assert base in FOLDERS and all(f"{base} / {ph}" in FOLDERS for ph in ("Sopralluogo", "Preventivi", "Lavori", "Spese", "Report")), FOLDERS
    assert f"Cartella: {base}" in out["message"] and "https://drive/" in out["message"]
    await deny(server.confirm_commessa_draft(r["draft"]["id"], server.DraftConfirmPayload(choice="ok"), me), 404)   # done already
    # a new client, cancelled
    NEXT_JOB.update(client="Anna Verdi", title="Tetto", address="", start="", value=None)
    r = await server._save_job_log(me, "Nuova commessa per Anna Verdi, tetto")
    assert [o["key"] for o in r["draft"]["options"]] == ["ok", "no"] and "(nuovo: lo aggiungo" in r["message"]
    assert (await server.confirm_commessa_draft(r["draft"]["id"], server.DraftConfirmPayload(choice="no"), me))["status"] == "cancelled"
    assert not any(x["data"].get("nome") == "Anna Verdi" for x in db.collection_items.docs)
    r = await server._save_job_log(me, "Nuova commessa per Anna Verdi, tetto")
    out2 = await server.confirm_commessa_draft(r["draft"]["id"], server.DraftConfirmPayload(choice="ok"), me)
    assert out2["client_created"] and out2["commessa"]["codice"] == f"{jl.today_local().year}-002"

    # 3) photos of a new commessa: in Sopralluogo, named by the note (AUT-SOP-03 / AUT-GEN-07)
    async def interp(t, speaker, team, known=None, user_id=None, channel="web", photos=0):
        return {"kind": "nota", "doubt": "", "date": "2026-10-28", "text": t, "hours": [], "materials": [], "problems": [], "client": "", "commessa": ""}
    jl.interpret = interp
    res = await server._save_job_log(me, "foto del tetto, sopralluogo del 28 ottobre", images=[jpeg_uri(), jpeg_uri()], commessa_id=v["id"])
    for _ in range(30):
        await asyncio.sleep(0.05)
    names = [n for f, n in SAVED if f == f"{base} / Sopralluogo"]
    assert names == ["sopralluogo_20261028_tetto.jpg", "sopralluogo_20261028_tetto_02.jpg"], SAVED
    ph = next(p for p in db.job_photos.docs if p["log_id"] == res["log"]["id"])
    assert ph["drive_link"] == "https://drive/sopralluogo_20261028_tetto.jpg"

    # 4) the archive not answering: queued, retried, the administrator told after a day (AUT-GEN-08)
    DRIVE["fail"] = True
    rec = await server._archive_commessa_bytes("u1", cl, next(x for x in db.collection_sub_items.docs if x["id"] == v["id"]), v, "lavori",
                                               b"%PDF-1.4 x", "pdf", "application/pdf", day=_date(2026, 11, 2), description="impianto elettrico")
    assert rec["status"] == "queued" and rec["name"] == "lavori_20261102_impianto-elettrico.pdf" and rec["attempts"] == 1
    assert next(x for x in db.archive_files.docs if x["id"] == rec["id"])["data_b64"]
    NOTICES.clear()
    later = datetime.now(timezone.utc) + timedelta(hours=25)
    assert await server._archive_retry(later) == 0
    assert any("non riesco a salvare" in t for _c, t in NOTICES), NOTICES
    n_notes = len(NOTICES)
    await server._archive_retry(later + timedelta(hours=2))
    assert len(NOTICES) == n_notes                                               # told once
    DRIVE["fail"] = False
    assert await server._archive_retry(later + timedelta(hours=3)) == 1
    done = next(x for x in db.archive_files.docs if x["id"] == rec["id"])
    assert done["status"] == "saved" and not done.get("data_b64") and (f"{base} / Lavori", "lavori_20261102_impianto-elettrico.pdf") in SAVED

    # 5) a collaborator enabled on a commessa is told on Telegram (AUT-CRE-03)
    c = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Neri"), me)
    cdoc = next(x for x in db.collaborators.docs if x["id"] == c["collaborator"]["id"])
    cdoc.update(status="active", telegram_chat_id=555)
    BOT_SENT.clear()
    await server.set_commessa_collaborator(v["id"], cdoc["id"], server.CollabEnablePayload(enabled=True), me)
    assert any(chat == 555 and "Sei abilitato sulla commessa «Rifacimento bagno» — Mario Rossi" in text and "via Garibaldi 5" in text
               for chat, text, _kb in BOT_SENT), BOT_SENT
    print("ALL OK")

asyncio.run(main())
