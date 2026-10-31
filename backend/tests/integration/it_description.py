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

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77, "tenant_id": "ten_1"}
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

db.tenants.docs.append({"id": "ten_1", "name": "Impresa Rossi", "owner_user_id": "u1", "owner_email": "a@b.it",
                       "plan": {"max_users": 5, "max_collaborators": 5, "max_admins": 1}, "sharing": {"users_share": True, "collab_contacts": False}})
import io, json as _json
from starlette.datastructures import UploadFile


class _Resp:   # the model's answer, for jl.read_document
    def __init__(s, content): s.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]; s.usage = None
class _FakeOpenAI:
    answer = {}
    def __init__(s, **k):
        s.chat = type("Ch", (), {})(); s.chat.completions = type("Co", (), {})()
        async def create(**k):
            _FakeOpenAI.seen = k["messages"][-1]["content"]
            return _Resp(_json.dumps(_FakeOpenAI.answer))
        s.chat.completions.create = create
jl.openai.AsyncOpenAI = _FakeOpenAI
jl._track = lambda *a, **k: None

QUOTE = """PREVENTIVO n. 45/2026 - Spett.le Mario Rossi
Rifacimento bagno al piano primo
1) Demolizione pavimento e rivestimenti esistenti - a corpo  € 1.200,00
2) Rifacimento impianto idraulico di scarico e adduzione       € 3.800,00
3) Posa pavimento e rivestimento in gres 60x60 (28 mq)          € 4.500,00
4) Fornitura e posa sanitari sospesi e piatto doccia            € 3.000,00
Totale imponibile € 12.500,00   IVA 10% € 1.250,00   Totale € 13.750,00
Pagamento: 30% all'ordine, saldo a fine lavori."""


def sub():
    return next(x for x in db.collection_sub_items.docs if x["id"] == "s_bagno")


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "data": {"titolo": "Bagno", "stato": "in corso"}})
    key = (cl.get("system_sub_map") or {}).get("descrizione", "descrizione")
    jl.interpret = said()

    # 1) said in the chat (or dictated): the description, not a diary entry
    n_logs = len(db.job_logs.docs)
    res = await server._save_job_log(me, "Descrizione attività: rifacimento completo del bagno con sostituzione dei sanitari", commessa_id="s_bagno")
    assert res["status"] == "description", res
    assert sub()["data"][key] == "rifacimento completo del bagno con sostituzione dei sanitari"
    assert sub()["description_meta"]["source"] == "messaggio" and len(db.job_logs.docs) == n_logs
    res = await server._save_job_log(me, "aggiungi alla descrizione: anche lo spostamento della caldaia", commessa_id="s_bagno")
    assert res["status"] == "description" and sub()["data"][key].endswith("\n\nanche lo spostamento della caldaia")
    # a question of the model is no matter: said in so many words
    jl.interpret = said(kind="domanda")
    assert (await server._save_job_log(me, "il lavoro consiste nel rifacimento del bagno", commessa_id="s_bagno"))["status"] == "description"
    assert sub()["data"][key] == "il lavoro consiste nel rifacimento del bagno"
    jl.interpret = said()
    # an ordinary note stays a note
    assert (await server._save_job_log(me, "oggi demolito il pavimento", commessa_id="s_bagno"))["status"] == "ok"
    assert sub()["data"][key] == "il lavoro consiste nel rifacimento del bagno"
    # a collaborator never writes it: theirs is a note
    gino = {"id": "k1", "first_name": "Gino", "name": "Gino Neri", "company": ""}
    r = await server._save_job_log(me, "descrizione attività: tutto da rifare", commessa_id="s_bagno", author=gino, channel="telegram")
    assert r["status"] == "ok" and sub()["data"][key] == "il lavoro consiste nel rifacimento del bagno"
    # nor a user who is not the owner nor an administrator
    assert not server._can_describe(server.User(user_id="u9", email="u9@b.it", name="Ugo", role="user"), cl)
    assert server._can_describe(me, cl)

    # 2) the diary shows it, with where it came from
    d = await server.get_job_commessa("s_bagno", current=me)
    assert d["commessa"]["descrizione"].startswith("il lavoro consiste") and d["commessa"]["descrizione_info"]["source"] == "messaggio"

    # 3) a quote uploaded: the activities and the value proposed (nothing saved yet)
    _FakeOpenAI.answer = {"kind": "preventivo", "description": "Rifacimento del bagno al piano primo:\n- demolizione di pavimento e rivestimenti",
                          "amount": 12500, "amount_basis": "imponibile"}
    up = UploadFile(file=io.BytesIO(QUOTE.encode()), filename="Preventivo 45.txt")
    prop = await server.read_commessa_document("s_bagno", up, me)
    assert prop["kind"] == "preventivo" and prop["amount"] == 12500 and prop["amount_basis"] == "imponibile", prop
    assert prop["current_description"].startswith("il lavoro") and prop["file_name"] == "Preventivo 45.txt"
    assert "Totale imponibile" in _FakeOpenAI.seen
    assert sub()["data"][key].startswith("il lavoro")                       # not saved yet
    # a figure that is not written in the document is never proposed
    _FakeOpenAI.answer = {**_FakeOpenAI.answer, "amount": 12000}
    prop2 = await server.read_commessa_document("s_bagno", UploadFile(file=io.BytesIO(QUOTE.encode()), filename="p.txt"), me)
    assert prop2["amount"] is None and prop2["amount_basis"] == ""
    # an empty / unreadable file
    try:
        await server.read_commessa_document("s_bagno", UploadFile(file=io.BytesIO(b"ciao"), filename="x.txt"), me); assert False
    except HTTPException as e:
        assert e.status_code == 400 and "leggere" in e.detail
    try:
        await server.read_commessa_document("s_bagno", UploadFile(file=io.BytesIO(b"abc"), filename="x.exe"), me); assert False
    except HTTPException as e:
        assert e.status_code == 400

    # 4) confirmed: the description and the commessa's value (the quote in Costi)
    out = await server.set_commessa_description("s_bagno", server.CommessaDescriptionPayload(
        text=prop["description"], file_name=prop["file_name"], doc_kind=prop["kind"], budget=prop["amount"]), me)
    assert out["descrizione"].startswith("Rifacimento del bagno") and out["budget"] == 12500
    assert out["descrizione_info"]["source"] == "documento" and out["descrizione_info"]["kind"] == "preventivo"
    assert next(e for e in db.job_economics.docs if e["commessa_id"] == "s_bagno")["budget"] == 12500
    # a site-survey report added at the end, the value untouched
    out = await server.set_commessa_description("s_bagno", server.CommessaDescriptionPayload(
        text="Sopralluogo: scarichi da rifare.", mode="aggiungi", file_name="sopralluogo.pdf", doc_kind="sopralluogo"), me)
    assert out["descrizione"].endswith("\n\nSopralluogo: scarichi da rifare.") and out["budget"] == 12500

    # 5) the collaborators' answers know it (the commessa's card)
    assert "descrizione" in server._commessa_view(sub(), db.collection_items.docs[0], cl)
    print("ALL OK")

asyncio.run(main())
