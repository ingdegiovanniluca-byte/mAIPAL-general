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
import job_logs as jl, collab_telegram as ct, telegram_bot as tg
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from telegram.ext import ApplicationHandlerStop
import telegram

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77}
db.users.docs.append(dict(U))
db.users.docs.append({"user_id": "u2", "email": "x@b.it", "name": "Altro Utente", "role": "user"})
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

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    def client(i, name, phone=""): db.collection_items.docs.append({"id": i, "collection_id": cl["id"], "data": {"nome": name, "telefono": phone, "email": "cli@x.it"}})
    def comm(i, item, title, stato): db.collection_sub_items.docs.append({"id": i, "collection_id": cl["id"], "item_id": item, "data": {"titolo": title, "stato": stato}})
    client("c_rossi", "Mario Rossi", "333 9999999"); comm("s_bagno", "c_rossi", "Bagno", "in corso")
    client("c_bianchi", "Anna Bianchi"); comm("s_tetto", "c_bianchi", "Tetto", "in corso"); comm("s_box", "c_bianchi", "Box", "preventivo")

    # 1) only the Admin manages collaborators
    try:
        await server.list_collaborators(server.User(**db.users.docs[1])); assert False
    except HTTPException as e:
        assert e.status_code == 403
    # 2) a new one: the code, the WhatsApp message with link and code
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Neri", email="Gino@Idraulica.it",
        phone="333 123 4567", role="idraulico", company="Idraulica Neri", commesse=["s_bagno", "s_tetto", "nope"]), me)
    col, inv = r["collaborator"], r["invite"]
    code = inv["code"]
    assert len(code) == 8 and col["status"] == "invited" and [c["id"] for c in col["commesse"]] == ["s_bagno", "s_tetto"]
    assert inv["link"] == f"https://t.me/maipal_bot?start={code}" and code in inv["message"] and "Bagno" in inv["message"]
    assert inv["whatsapp_url"].startswith("https://wa.me/393331234567?text=")
    assert db.collaborators.docs[0]["email"] == "gino@idraulica.it"
    for bad in (dict(first_name="", last_name="X", email="a@b.it"), dict(first_name="A", last_name="B", email="nope"),
                dict(first_name="A", last_name="B", phone="12345")):
        try:
            await server.create_collaborator(server.CollaboratorPayload(**bad), me); assert False
        except HTTPException as e:
            assert e.status_code == 400
    # no e-mail: only the phone (an Italian mobile gets +39; a foreign one keeps its prefix)
    n = len(db.collaborators.docs)
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Pino", last_name="Verdi", phone="347 765 4321"), me)
    assert r["invite"]["whatsapp_url"].startswith("https://wa.me/393477654321?text=") and r["collaborator"]["email"] == ""
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Hans", last_name="Muller", phone="+41 79 123 45 67"), me)
    assert r["invite"]["whatsapp_url"].startswith("https://wa.me/41791234567?text=")
    r = await server.create_collaborator(server.CollaboratorPayload(first_name="Ugo", last_name="Bassi"), me)   # nothing: WhatsApp asks who
    assert r["invite"]["whatsapp_url"].startswith("https://wa.me/?text=")
    db.collaborators.docs[:] = db.collaborators.docs[:n]

    # 3) linking: a wrong code is not theirs (the app's own /start goes on), the right one asks the phone
    assert not await send(900, "/start WRONGCODE")
    assert await send(900, f"/start {code.lower()}")
    assert "conferma il tuo numero" in REPLIES[-1][0] and db.collaborators.docs[0]["pending_chat_id"] == 900
    contact = lambda num, uid=500: type("C", (), {"phone_number": num, "user_id": uid})()
    assert await send(900, contact=contact("+39 333 000 0000"))
    assert "non corrisponde" in REPLIES[-1][0] and not db.collaborators.docs[0].get("telegram_chat_id")
    assert await send(900, contact=contact("+393331234567", uid=999))
    assert "TUO numero" in REPLIES[-1][0]
    assert await send(900, contact=contact("+393331234567"))
    c0 = db.collaborators.docs[0]
    assert c0["telegram_chat_id"] == 900 and c0["status"] == "active" and c0["code"] is None
    assert "sei collegato" in REPLIES[-1][0] and "Bagno — Mario Rossi" in REPLIES[-1][0]
    assert NOTICES[-1][0] == 77 and "Gino Neri (Idraulica Neri) si è collegato" in NOTICES[-1][1]
    # the app user's own chat is not touched
    assert not await send(77, "ciao")

    # 4) an entry naming the commessa -> its diary, with the collaborator as author; a problem -> the admin is told
    jl.interpret = said(hours=[{"who": "io", "hours": 4}], problems=["manca una scatola 503"])
    assert await send(900, "oggi 4 ore sul bagno, manca una scatola 503")
    lg = db.job_logs.docs[-1]
    assert lg["commessa_id"] == "s_bagno" and lg["author_name"] == "Gino" and lg["collaborator_id"] == c0["id"]
    assert lg["author_company"] == "Idraulica Neri" and lg["user_id"] == "u1" and lg["hours"] == [{"who": "Gino", "hours": 4.0}]
    assert jl.interpret.last["speaker"] == "Gino" and "Luca" in jl.interpret.last["team"]
    assert buttons(REPLIES[-1][1]) == [f"clu:{lg['id']}"]
    assert "segnala su «Bagno»" in NOTICES[-1][1] and "manca una scatola 503" in NOTICES[-1][1]
    # the next message stays on the same commessa
    jl.interpret = said()
    assert await send(900, "pulito tutto alla fine")
    assert db.job_logs.docs[-1]["commessa_id"] == "s_bagno"
    # no commessa named, none in the conversation -> buttons with ONLY their commesse; the choice saves it
    await db.collaborators.update_one({"id": c0["id"]}, {"$set": {"tg_state": None}})
    assert await send(900, "smontato il ponteggio")
    assert sorted(buttons(REPLIES[-1][1])) == ["clc:s_bagno", "clc:s_tetto"]
    n = len(db.job_logs.docs)
    assert await tap(900, "clc:s_tetto")
    assert len(db.job_logs.docs) == n + 1 and db.job_logs.docs[-1]["commessa_id"] == "s_tetto" and db.job_logs.docs[-1]["text"] == "smontato il ponteggio"
    assert await tap(900, "clc:s_box") and "non è più abilitata" in REPLIES[-1][0]   # never enabled on Box

    # 5) a question: answered from that commessa only, the client's phone and e-mail left out
    jl.interpret = said(kind="domanda")
    n = len(db.job_logs.docs)
    assert await send(900, "cosa manca da fare sul bagno?")
    assert len(db.job_logs.docs) == n and "Mancano i sanitari." in REPLIES[-1][0]
    v = ANSWERS[-1]["view"]
    assert v["id"] == "s_bagno" and "client_phone" not in v and "client_email" not in v
    await server.update_collaborator(c0["id"], server.CollaboratorPatch(show_client_contacts=True), me)
    assert await send(900, "il numero del cliente del bagno?")
    assert ANSWERS[-1]["view"].get("client_phone") == "333 9999999" and ANSWERS[-1]["history"]

    # 6) Annulla within 10 minutes; later not
    jl.interpret = said()
    assert await send(900, "montato il lavabo del bagno")
    lid = db.job_logs.docs[-1]["id"]
    assert await tap(900, f"clu:{lid}") and not any(x["id"] == lid for x in db.job_logs.docs)
    assert await send(900, "montato il bidet del bagno")
    old = db.job_logs.docs[-1]
    old["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    assert await tap(900, f"clu:{old['id']}") and "Sono passati più di" in REPLIES[-1][0]
    # a photo, then its description: Annulla takes back only the description, the photo stays
    author = {"id": c0["id"], "first_name": "Gino", "name": "Gino Neri", "company": ""}
    import io as _io, base64 as _b64
    from PIL import Image
    buf = _io.BytesIO(); Image.new("RGB", (40, 30), (200, 80, 40)).save(buf, "JPEG")
    pic = await server._save_job_log(me, "Foto dal cantiere", images=["data:image/jpeg;base64," + _b64.b64encode(buf.getvalue()).decode()],
                                     commessa_id="s_bagno", channel="telegram", author=author)
    pid = pic["log"]["id"]
    async def describing(t, speaker, team, known=None, user_id=None, channel="web", photos=0):
        return {"kind": "nota" if photos else "non_chiara", "doubt": "", "date": jl.today_local().isoformat(), "text": "Montato il miscelatore.",
                "hours": [], "materials": [], "problems": [], "client": "", "commessa": ""}
    jl.interpret = describing
    n = len(db.job_logs.docs)
    assert await send(900, "qui ho montato il miscelatore")
    lg = next(x for x in db.job_logs.docs if x["id"] == pid)
    assert len(db.job_logs.docs) == n and lg["text"] == "Montato il miscelatore." and "Descrizione aggiunta" in REPLIES[-1][0]
    assert buttons(REPLIES[-1][1]) == [f"clu:{pid}"]
    assert await tap(900, f"clu:{pid}") and "resta la foto" in REPLIES[-1][0]
    lg = next(x for x in db.job_logs.docs if x["id"] == pid)
    assert lg["text"] == "Foto dal cantiere" and lg["photos"] and "before_description" not in lg

    # 7) only diary and questions: other commands never reach the app's agents
    assert await send(900, "/task chiamare il fornitore") and "Qui puoi solo" in REPLIES[-1][0]
    # 8) a closed commessa closes their access to it; suspended -> nothing
    db.collection_sub_items.docs[[s["id"] for s in db.collection_sub_items.docs].index("s_tetto")]["data"]["stato"] = "chiusa"
    await db.collaborators.update_one({"id": c0["id"]}, {"$set": {"tg_state": None}})
    assert await send(900, "lavori di oggi")
    assert db.job_logs.docs[-1]["commessa_id"] == "s_bagno"   # Tetto is closed: Bagno is the only one left
    await server.update_collaborator(c0["id"], server.CollaboratorPatch(status="suspended"), me)
    n = len(db.job_logs.docs)
    assert await send(900, "lavori sul bagno") and "sospeso" in REPLIES[-1][0] and len(db.job_logs.docs) == n
    await server.update_collaborator(c0["id"], server.CollaboratorPatch(status="active"), me)
    # 9) the daily limit
    await db.collaborators.update_one({"id": c0["id"]}, {"$set": {"msg_day": datetime.now(timezone.utc).date().isoformat(), "msg_count": server.COLLAB_DAILY_LIMIT}})
    assert await send(900, "altro") and "numero massimo" in REPLIES[-1][0]
    await db.collaborators.update_one({"id": c0["id"]}, {"$set": {"msg_count": 0}})

    # 10) the end-of-day reminder: Mon-Fri from 18:00, only if nothing written today, once a day
    monday_1830 = datetime(2026, 10, 12, 16, 30, tzinfo=timezone.utc)   # 18:30 in Rome
    assert await server._collab_remind_due(datetime(2026, 10, 12, 14, 0, tzinfo=timezone.utc)) == 0   # 16:00
    assert await server._collab_remind_due(datetime(2026, 10, 11, 16, 30, tzinfo=timezone.utc)) == 0  # Sunday
    db.job_logs.docs = [x for x in db.job_logs.docs if x.get("date") != "2026-10-12"]
    assert await server._collab_remind_due(monday_1830) == 1
    assert BOT_SENT[-1][0] == 900 and "cosa avete fatto oggi" in BOT_SENT[-1][1] and buttons(BOT_SENT[-1][2]) == ["clc:s_bagno"]
    assert await server._collab_remind_due(monday_1830) == 0

    # 11) from the commessa's diary: who is enabled, and enable / disable
    lst = await server.commessa_collaborators("s_box", me)
    assert lst[0]["id"] == c0["id"] and lst[0]["enabled"] is False
    await server.set_commessa_collaborator("s_box", c0["id"], server.CollabEnablePayload(enabled=True), me)
    assert "s_box" in db.collaborators.docs[0]["commesse"]
    await server.set_commessa_collaborator("s_box", c0["id"], server.CollabEnablePayload(enabled=False), me)
    assert "s_box" not in db.collaborators.docs[0]["commesse"]

    # 12) a new code; an expired one is refused; deleting a commessa drops it from them; removal
    r = await server.reinvite_collaborator(c0["id"], me)
    assert r["invite"]["code"] != code
    await db.collaborators.update_one({"id": c0["id"]}, {"$set": {"code_expires_at": "2020-01-01T00:00:00+00:00"}})
    assert await send(901, f"/start {r['invite']['code']}") and "scaduto" in REPLIES[-1][0]
    await server._delete_job_diaries(["s_bagno"])
    assert "s_bagno" not in db.collaborators.docs[0]["commesse"]
    lst = await server.list_collaborators(me)
    assert lst[0]["name"] == "Gino Neri" and lst[0]["linked"] and lst[0]["code"] is None
    await server.delete_collaborator(c0["id"], me)
    assert not db.collaborators.docs and not await send(900, "ciao")
    print("ALL OK")
asyncio.run(main())
