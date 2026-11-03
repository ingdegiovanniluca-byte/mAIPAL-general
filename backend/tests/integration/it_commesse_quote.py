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


from starlette.datastructures import UploadFile

READ_DOC = {}
async def fake_read_doc(text, commessa, user_id=None, channel="web"):
    return dict(READ_DOC)
jl.read_document = fake_read_doc
QUOTE = {}
async def fake_read_quote(text, commessa, user_id=None, channel="web"):
    return dict(QUOTE)
jl.read_quote = fake_read_quote
SUMMARIES = []
async def fake_summary(entries, commessa, user_id=None, channel="web"):
    SUMMARIES.append(entries)
    return {"date_participants": "28/10, Luca", "state": "bagno 3x2 m", "requests": "doccia al posto della vasca", "issues": "", "materials": ""}
jl.survey_summary = fake_summary
async def fake_ocr(contents, filename, user_id=None, channel="web"):
    return "Appunti: parete 300 cm, altezza 270 cm, scarico da spostare"
server._ocr_image_bytes = fake_ocr


async def settle():
    for _ in range(40):
        await asyncio.sleep(0.03)


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    MARCO = server.User(**db.users.docs[1])
    v = await server.create_sub_item(cl["id"], "c_rossi", server.CollectionSubItemPayload(data={"titolo": "Rifacimento bagno"}), me)
    sid = v["id"]
    base = f"Clienti / Mario Rossi / {v['data']['codice']} – Rifacimento bagno"
    jl.interpret = said()

    # 1) the survey: a note on a new commessa -> section Sopralluogo, state "sopralluogo", organized
    r = await server._save_job_log(me, "bagno 3 per 2 metri, piastrelle da rifare, il cliente vuole la doccia", commessa_id=sid)
    assert r["status"] == "ok" and "Sopralluogo" in r["message"]
    lg = next(x for x in db.job_logs.docs if x["id"] == r["log"]["id"])
    assert lg["section"] == "sopralluogo"
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["stato"] == "sopralluogo"
    ev = [x for x in db.job_logs.docs if x["commessa_id"] == sid and x.get("kind") == "stato"]
    assert ev and "primo contenuto di sopralluogo" in ev[-1]["text"]
    await settle()
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["survey"]["requests"] == "doccia al posto della vasca" and sub["survey"]["entries"] == 1
    # a photo of handwritten notes: read, in the survey, named and archived
    r = await server._save_job_log(me, "appunti del sopralluogo", images=[jpeg_uri()], commessa_id=sid)
    await settle()
    lg = next(x for x in db.job_logs.docs if x["id"] == r["log"]["id"])
    assert lg["ocr"][0]["text"].startswith("Appunti: parete 300 cm")
    assert "scarico da spostare" in SUMMARIES[-1][-1]["text"]
    assert any(f == f"{base} / Sopralluogo" and n.startswith("sopralluogo_") and n.endswith("_appunti.jpg") for f, n in SAVED), SAVED
    # a collaborator's note is never survey
    gino = {"id": "k1", "first_name": "Gino", "name": "Gino Neri", "company": ""}
    r = await server._save_job_log(me, "sopralluogo fatto, misure prese", commessa_id=sid, author=gino, channel="telegram")
    assert not next(x for x in db.job_logs.docs if x["id"] == r["log"]["id"]).get("section")
    # a survey document
    READ_DOC.update(kind="sopralluogo", description="Rilievo: bagno 6 mq, vasca da togliere", amount=None, amount_basis="")
    out = await server._ingest_commessa_document(me, sid, "rilievo bagno.txt", b"Rilievo del bagno: 6 mq, vasca da togliere, scarico a pavimento",
                                                 "text/plain", caption="rilievo del bagno")
    assert out["type"] == "entry" and "(Sopralluogo)" in out["message"]
    assert any(n.startswith("sopralluogo_") and "rilievo-bagno" in n and n.endswith(".txt") for _f, n in SAVED), SAVED

    # 2) the quote: read, confirmed, version 1, state, value, description (AUT-PRE-01..03)
    QUOTE.update(total=13750.0, taxable=12500.0, vat=1250.0, items=[{"description": "Demolizioni", "amount": 1200.0}],
                 start="2026-11-10", end="2026-11-30", validity="2026-11-20", payments=["30% all'ordine"],
                 activities=["Demolizione pavimento", "Rifacimento scarichi", "Posa gres"], materials=["gres 60x60"],
                 description="Rifacimento del bagno:\n- demolizione\n- scarichi\n- posa gres")
    READ_DOC.update(kind="preventivo")
    up = await server.upload_commessa_document(sid, UploadFile(file=io.BytesIO(b"PREVENTIVO ... Totale imponibile 12.500,00 Totale 13.750,00"), filename="prev.txt"),
                                               None, None, me)
    assert up["type"] == "quote" and up["value"] == 12500.0 and up["current_budget"] is None
    assert "imponibile € 12.500" in up["message"] and "offerta valida fino al" in up["message"] and "Confermi i dati?" in up["message"]
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["stato"] == "sopralluogo"                     # nothing yet
    c1 = await server.confirm_quote(up["quote"]["id"], server.QuoteConfirmPayload(), me)
    assert c1["quote"]["version"] == 1 and "preventivo inviato" in c1["message"] and "Valore della commessa: € 12.500" in c1["message"]
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["stato"] == "preventivo inviato" and sub["data"]["descrizione"].startswith("Rifacimento del bagno")
    assert next(e for e in db.job_economics.docs if e["commessa_id"] == sid)["budget"] == 12500.0
    today = jl.today_local().strftime("%Y%m%d")
    assert (f"{base} / Preventivi", f"preventivo_{today}_v1.txt") in SAVED, SAVED
    assert any(x.get("kind") == "preventivo" and "Preventivo v1" in x["text"] for x in db.job_logs.docs)
    await deny(server.confirm_quote(up["quote"]["id"], server.QuoteConfirmPayload(), me), 404)   # once
    # v2 with another value: the administrator chooses (AUT-PRE-03)
    QUOTE.update(total=11000.0, taxable=10000.0)
    up2 = await server._ingest_commessa_document(me, sid, "prev2.txt", b"PREVENTIVO v2 Totale imponibile 10.000,00 Totale 11.000,00", "application/pdf",
                                                 hint="preventivo")
    assert "⚖️ Il valore della commessa ora è € 12.500" in up2["message"]
    BOT_SENT.clear()
    c2 = await server.confirm_quote(up2["quote"]["id"], server.QuoteConfirmPayload(), me)
    assert c2["quote"]["version"] == 2 and c2["quote"]["value_pending"] and any("quale tengo" in t for _c, t, _k in BOT_SENT)
    assert (f"{base} / Preventivi", f"preventivo_{today}_v2.txt") in SAVED
    assert (await server.choose_quote_value(up2["quote"]["id"], server.QuoteValuePayload(choice="new"), me))["message"].startswith("💶 Valore")
    assert next(e for e in db.job_economics.docs if e["commessa_id"] == sid)["budget"] == 10000.0
    # a user cannot choose the value nor register the outcome
    await deny(server._choose_quote_value(MARCO, up2["quote"]["id"], "keep"))
    await deny(server._quote_outcome(MARCO, sid, "accettato"))

    # 3) follow-ups on the outcome: after N days, every N days, at most M (AUT-PRE-04)
    later = datetime.now(timezone.utc) + timedelta(days=8)
    BOT_SENT.clear()
    assert await server._quote_followups(later) == 1
    chat, text, kb = BOT_SENT[-1]
    assert chat == 77 and "senza esito da" in text and buttons(kb) == [f"qo:{sid}:accettato", f"qo:{sid}:perso", f"qo:{sid}:in_attesa"]
    assert await server._quote_followups(later) == 0
    assert await server._quote_followups(later + timedelta(days=8)) == 1
    await server.patch_tenant_settings({"quote_followup_max": 2}, me)
    assert await server._quote_followups(later + timedelta(days=30)) == 0
    # the documents of the diary: the quotes
    d = await server.get_job_commessa(sid, current=me)
    assert [q["version"] for q in d["quotes"]] == [2, 1] and d["survey"]["state"] == "bagno 3x2 m"

    # 4) the outcome said in a message: accepted -> in lavorazione, the activities to plan (AUT-PRE-05)
    r = await server._save_job_log(me, "il preventivo del bagno dei Rossi è stato accettato", commessa_id=sid)
    assert r["status"] == "commessa_update" and "in lavorazione" in r["message"] and "• Posa gres" in r["message"], r
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["stato"] == "in lavorazione" and sub["quote_outcome"] == "accettato"

    # 5) lost, only with its reason; the history of the losses speaks (AUT-PRE-06/07)
    def new_sub(i, title):
        db.collection_sub_items.docs.append({"id": i, "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": title, "stato": "preventivo inviato"},
                                             "created_at": "2026-10-01T10:00:00Z"})
    new_sub("s_b2", "Bagno piccolo"); new_sub("s_b3", "Bagno ospiti"); new_sub("s_b4", "Bagno grande")
    r = await server._save_job_log(me, "il preventivo è stato perso", commessa_id="s_b2")
    assert r["status"] == "unclear" and "Perché" in r["message"]
    r = await server._save_job_log(me, "preventivo perso per il prezzo, troppo caro", commessa_id="s_b2")
    assert r["status"] == "commessa_update" and next(x for x in db.collection_sub_items.docs if x["id"] == "s_b2")["lost_reason"]["category"] == "prezzo"
    await server.set_quote_outcome("s_b3", server.QuoteOutcomePayload(outcome="perso", lost_category="prezzo"), me)
    await deny(server.set_quote_outcome("s_b4", server.QuoteOutcomePayload(outcome="perso"), me), 400)
    QUOTE.update(total=9000.0, taxable=None)
    up4 = await server._ingest_commessa_document(me, "s_b4", "prev.txt", b"PREVENTIVO Totale 9.000,00", "text/plain", hint="preventivo")
    assert "2 degli ultimi 2 preventivi persi per lavori simili («bagno») erano per prezzo" in up4["loss_feedback"], up4["loss_feedback"]
    print("ALL OK")

asyncio.run(main())
