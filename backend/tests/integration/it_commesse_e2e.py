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
db.users.docs.append({"user_id": "u2", "email": "x@b.it", "name": "Marco Bianchi", "role": "user", "tenant_id": "ten_1", "org_id": None,
                      "telegram_chat_id": 78})
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


import weather as wx, client_updates as cu
from zoneinfo import ZoneInfo
ROME = ZoneInfo("Europe/Rome")
async def sunny(lat, lon, day):
    return {"rain_pct": 70, "wind_kmh": 10, "tmin": 8, "tmax": 14, "code": 61}
wx.provider = sunny
PINS = []
async def fake_pin_send(chat_id, text, kb):
    PINS.append(("send", chat_id, text, kb)); return 1000 + len(PINS)
async def fake_pin_edit(chat_id, mid, text, kb):
    PINS.append(("edit", chat_id, text, kb))
async def fake_pin_unpin(chat_id, mid):
    PINS.append(("unpin", chat_id, None, None))
server._day_pin_send, server._day_pin_edit, server._day_pin_unpin = fake_pin_send, fake_pin_edit, fake_pin_unpin
async def client_lines(title, notes, user_id=None):
    return ["Smontati i sanitari del bagno"] if notes else []
cu.summarize = client_lines
async def fake_commessa_summary(*a, **k):
    return {"stato": "Lavori conclusi.", "attivita": "Rifacimento del bagno."}
import work_reports
work_reports.commessa_summary = fake_commessa_summary
REPORTS = []
async def fake_deliver(current, docx_bytes, fname, folder, subs, caption):
    REPORTS.append((fname, " / ".join([folder] + list(subs)))); return "https://drive/r", "https://drive/f", False
server._deliver_work_report = fake_deliver


def at(day, hh, mm=0):
    return datetime.combine(day, datetime.min.time(), tzinfo=ROME).replace(hour=hh, minute=mm).astimezone(timezone.utc)


def to(chat):
    return [(t, kb) for c, t, kb in BOT_SENT if c == chat]


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    MARCO = server.User(**db.users.docs[1])
    jl.interpret = said()
    D = jl.today_local()

    # 1) "Nuova commessa per Mario Rossi, rifacimento bagno in via Garibaldi 5 a Torino, inizio 10 novembre":
    #    no such client -> the summary with the new client, created only when confirmed: client, commessa, code, diary, folders
    NEXT_JOB.update(client="Mario Rossi", title="Rifacimento bagno", address="via Garibaldi 5, Torino", start="2026-11-10", end="", value=None, description="")
    r = await server._execute_list_update(me, "Nuova commessa per Mario Rossi, rifacimento bagno in via Garibaldi 5 a Torino, inizio 10 novembre")
    assert r["status"] == "commessa_draft" and "(nuovo: lo aggiungo" in r["message"] and not db.collection_sub_items.docs, r
    out = await server.confirm_commessa_draft(r["draft"]["id"], server.DraftConfirmPayload(choice="ok"), me)
    assert out["status"] == "created"
    sub = db.collection_sub_items.docs[0]
    sid = sub["id"]
    assert sub["data"]["stato"] == "nuova" and sub["data"]["codice"] and sub["data"]["indirizzo_cantiere"] == "via Garibaldi 5, Torino"
    assert any(x["data"].get("nome") == "Mario Rossi" for x in db.collection_items.docs)
    await settle()
    base = f"Clienti / Mario Rossi / {sub['data']['codice']} – Rifacimento bagno"
    assert any(f.startswith(base) for f in FOLDERS), FOLDERS
    sub["geo"] = {"lat": 45.07, "lon": 7.68, "source": "manual"}

    # 2) 4 photos and the photo of the handwritten notes: transcribed, Sopralluogo filled, files named, state SOPRALLUOGO
    await server._save_job_log(me, "piastrelle da rifare", images=[jpeg_uri()] * 4, commessa_id=sid)
    await settle()
    await server._save_job_log(me, "appunti", images=[jpeg_uri()], commessa_id=sid)
    await settle()
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["stato"] == "sopralluogo" and sub["survey"]["requests"]
    stamp = D.strftime("%Y%m%d")
    names = [n for f, n in SAVED if f == f"{base} / Sopralluogo"]
    assert f"sopralluogo_{stamp}_piastrelle-rifare.jpg" in names and f"sopralluogo_{stamp}_piastrelle-rifare_02.jpg" in names, names
    assert f"sopralluogo_{stamp}_appunti.jpg" in names
    assert any(lg.get("ocr") for lg in db.job_logs.docs if lg.get("commessa_id") == sid)

    # 3) the quote, 8.500 €: read, confirmed, PREVENTIVO_INVIATO; after 7 days the outcome asked; "accettato" -> IN_LAVORAZIONE + what to plan
    QUOTE.clear(); QUOTE.update(total=8500.0, taxable=None, vat=None, items=[{"description": "Smontaggio sanitari", "amount": 600.0}],
                                start="2026-11-10", end="2026-11-28", validity="", payments=[], activities=["Smontaggio sanitari", "Posa piatto doccia"],
                                materials=[], description="")
    READ_DOC.update(kind="preventivo")
    up = await server._ingest_commessa_document(me, sid, "preventivo.txt", b"PREVENTIVO Totale 8.500,00", "text/plain", hint="preventivo")
    assert up["type"] == "quote" and up["value"] == 8500.0
    await server.confirm_quote(up["quote"]["id"], server.QuoteConfirmPayload(), me)
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["stato"] == "preventivo inviato"
    assert (await server.get_job_commessa(sid, current=me))["economics"]["budget"] == 8500.0
    BOT_SENT.clear()
    assert await server._quote_followups(datetime.now(timezone.utc) + timedelta(days=7, hours=1)) == 1
    assert buttons(to(77)[-1][1])[0] == f"qo:{sid}:accettato"
    acc = await server._quote_outcome(me, sid, "accettato")
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["stato"] == "in lavorazione" and "Smontaggio sanitari" in acc["message"], acc

    # 4) planned for D with the user and the plumber; D-1 at 18:00 both get the reminder with what to bring and the weather;
    #    the plumber adds "portare flessibili da 30 cm"
    c = await server.create_collaborator(server.CollaboratorPayload(first_name="Gino", last_name="Neri", company="Neri Idraulica", commesse=[sid]), me)
    gino = next(x for x in db.collaborators.docs if x["id"] == c["collaborator"]["id"])
    gino.update(status="active", telegram_chat_id=900)
    a = await server.create_activity(sid, server.ActivityPayload(description="Smontaggio sanitari", date=D.isoformat(), start_time="09:00", end_time="13:00",
                                     assignees=[server.ActivityAssignee(type="user", id="u2"), server.ActivityAssignee(type="collab", id=gino["id"])],
                                     items=[server.ActivityItem(category="attrezzi", text="avvitatore")], origin="preventivo"), me)
    BOT_SENT.clear()
    assert await server._activity_notifications(at(D - timedelta(days=1), 18, 0)) == 2
    for chat in (78, 900):
        g1 = to(chat)[-1][0]
        assert "Smontaggio sanitari · inizio 09:00" in g1 and "avvitatore" in g1 and "pioggia 70%" in g1, g1
    assert await tap(900, f"aca:{a['id']}") and await send(900, "portare flessibili da 30 cm")
    assert any(i["text"] == "portare flessibili da 30 cm" for i in next(x for x in db.job_activities.docs if x["id"] == a["id"])["items"])
    await server.confirm_activity(a["id"], server.ActivityConfirmPayload(status="confermato"), MARCO)
    assert await tap(900, f"acf:{a['id']}")

    # 5) on D at 7:00 the pinned message; at 9:30 the plumber has no check-in: the administrator told, he asked;
    #    "arrivato alle 9:10" -> a DICHIARATA check-in
    PINS.clear()
    assert await server._collab_day_briefs(at(D, 7, 0)) == 1 and PINS[-1][1] == 900 and "flessibili da 30 cm" in PINS[-1][2]
    BOT_SENT.clear(); NOTICES.clear()
    await server._activity_notifications(at(D, 9, 31))
    assert any("Non risulti ancora arrivato" in t for t, _ in to(900)), to(900)
    assert any("*Gino Neri* non ha segnato l'arrivo" in t for _c, t in NOTICES), NOTICES
    view = server._commessa_view(sub, next(x for x in db.collection_items.docs if x["id"] == sub["item_id"]), cl)
    now_l = datetime.now(ROME)
    if now_l.hour * 60 + now_l.minute >= 9 * 60 + 15:   # said on Telegram (only once 9:10 has passed for real)
        assert await send(900, "arrivato alle 9:10")
    else:
        await server._presence_start(gino, me, view, at(D, 9, 10), None)
    ws = next(x for x in db.work_sessions.docs if x["collaborator_id"] == gino["id"])
    assert ws["origin"] == "dichiarata" and server._local(ws["start_at"]).strftime("%H:%M") == "09:10", ws
    await server._presence_start(server._user_worker(db.users.docs[1], "u1"), me, view, at(D, 8, 55), None)
    jl.interpret = said(hours=[{"who": "Gino", "hours": 4}], problems=["manca il rubinetto d'arresto"])
    await server._save_job_log(me, "smontati tutti i sanitari, manca il rubinetto d'arresto; comprato silicone 12 €", commessa_id=sid)
    lg = db.job_logs.docs[-1]
    lg["expenses"] = [{"label": "silicone", "amount": 12.0}]
    assert next(x for x in db.job_activities.docs if x["id"] == a["id"])["status"] == "svolta"

    # 6) the evening summary by site; on Friday the report with the margin and the draft for Mario Rossi, approved and sent
    BOT_SENT.clear()
    assert await server._daily_site_summary(at(D, 20, 0)) == 1 and "*Rifacimento bagno* — Mario Rossi" in to(77)[-1][0]
    F = D + timedelta(days=(4 - D.weekday()) % 7)
    W = D if D.weekday() >= 4 else F       # the report of the week D is in (asked on the weekend: that day's)
    rep = await server._job_weekly_summary(me, at(W, 18, 0).astimezone(ROME))
    assert "Margine" in rep and "valore € 8.500" in rep and "manodopera" in rep, rep
    if W - timedelta(days=W.weekday()) <= D:
        assert "1 svolte su 1 pianificate" in rep and "1 ancora aperti" in rep, rep
    act = next(x for x in db.scheduled_actions.docs if x.get("system_key") == server.WEEKLY_JOBS_KEY)
    assert act["schedule"]["weekdays"] == [4] and act["schedule"]["time"] == "18:00" and act["title"] == "Report settimanale cantieri"
    # the users never see the money
    assert "Margine" not in await server._job_weekly_summary(MARCO, at(W, 18, 0).astimezone(ROME))
    # nothing reaches the client without the approval
    db.client_links.docs.append({"id": "cl1", "owner_user_id": "u1", "collection_id": cl["id"], "item_id": sub["item_id"], "telegram_chat_id": 555,
                                 "status": "active", "name": "Mario Rossi"})
    if F - timedelta(days=F.weekday()) <= D:
        BOT_SENT.clear(); NOTICES.clear()
        assert await server._client_weekly_updates(at(F, 17, 59)) == 0
        assert await server._client_weekly_updates(at(F, 18, 0)) == 1
        assert not [t for c_, t in NOTICES if c_ == 555]
        txt, kb = to(77)[-1]
        assert "Bozza per il cliente" in txt and "Smontati i sanitari del bagno" in txt and buttons(kb) == [f"cud:ok:{sid}", f"cud:ed:{sid}", f"cud:no:{sid}"]
        assert "Gino" not in txt and "€" not in txt.split("\n\n", 1)[1]
        st = await server.get_client_updates(sid, me)
        assert st["approval"] and st["draft"]["text"].startswith("🏗️ Avanzamento lavori")
        await deny(server.decide_client_draft(sid, server.ClientDraftPayload(action="approve"), MARCO), (403, 404))
        out = await server.decide_client_draft(sid, server.ClientDraftPayload(action="save", text="Buongiorno, questa settimana abbiamo smontato i sanitari."), me)
        out = await server.decide_client_draft(sid, server.ClientDraftPayload(action="approve"), me)
        assert out["status"] == "inviata" and NOTICES[-1] == (555, "Buongiorno, questa settimana abbiamo smontato i sanitari.")
        await deny(server.decide_client_draft(sid, server.ClientDraftPayload(action="approve"), me), 409)   # once
    # by hand, also for a client not on Telegram: approved = copied by the administrator
    db.client_links.docs.clear()
    db.job_logs.docs.append({"id": "lw", "commessa_id": sid, "date": D.isoformat(), "text": "posato il piatto doccia", "hours": [], "materials": [], "problems": []})
    st = await server.new_client_draft(sid, me)
    out = await server.decide_client_draft(sid, server.ClientDraftPayload(action="approve"), me)
    assert out["status"] == "approvata" and not out["linked"] and "copia il testo" in out["message"]
    st = await server.new_client_draft(sid, me)
    assert (await server.decide_client_draft(sid, server.ClientDraftPayload(action="discard"), me))["status"] == "scartata"
    # the approval switched off (an organization's choice): straight to the clients on Telegram, as before
    db.client_links.docs.append({"id": "cl2", "owner_user_id": "u1", "collection_id": cl["id"], "item_id": sub["item_id"], "telegram_chat_id": 556, "status": "active", "name": "Mario Rossi"})
    await server.patch_tenant_settings({"client_report_approval": False}, me)
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    sub["client_updates"]["last_checked"] = None
    db.job_logs.docs.append({"id": "lw2", "commessa_id": sid, "date": (F + timedelta(days=7)).isoformat(), "text": "posate le piastrelle",
                             "hours": [], "materials": [], "problems": []})
    NOTICES.clear()
    assert await server._client_weekly_updates(at(F + timedelta(days=7), 18, 0)) == 1 and NOTICES[0][0] == 556
    await server.patch_tenant_settings({"client_report_approval": True, "weekly_report_day": "THU", "weekly_report_time": "17:30"}, me)
    act = next(x for x in db.scheduled_actions.docs if x.get("system_key") == server.WEEKLY_JOBS_KEY)
    assert act["schedule"]["weekdays"] == [3] and act["schedule"]["time"] == "17:30"
    await server.patch_tenant_settings({"weekly_report_day": "FRI", "weekly_report_time": "18:00"}, me)

    # the next week's programme (AUT-WEEK-04): to each operator, by commessa, with what to bring and what is still open
    nxt = F - timedelta(days=F.weekday()) + timedelta(days=7)
    b = await server.create_activity(sid, server.ActivityPayload(description="Posa piatto doccia", date=(nxt + timedelta(days=1)).isoformat(), start_time="08:00",
                                     assignees=[server.ActivityAssignee(type="user", id="u2")], items=[server.ActivityItem(category="materiali", text="silicone")]), me)
    BOT_SENT.clear()
    assert await server._weekly_programme(at(F, 17, 0)) == 0
    assert await server._weekly_programme(at(F, 18, 0)) == 1
    prog = to(78)[-1][0]
    assert "La tua prossima settimana" in prog and "*Rifacimento bagno* — Mario Rossi" in prog and "08:00 — Posa piatto doccia" in prog, prog
    assert "Materiali: silicone" in prog and "Ancora aperto: manca il rubinetto d'arresto" in prog
    assert await server._weekly_programme(at(F, 18, 30)) == 0

    # the organization's choices: no positions kept (C.4), the lunch break taken off a long day (PA-04)
    await server.patch_tenant_settings({"save_position": False, "lunch_break_minutes": 60}, me)
    ans, lid = await server._presence_stop(server._user_worker(db.users.docs[1], "u1"), at(D, 16, 55), {"lat": 45.07, "lon": 7.68})
    plog = next(x for x in db.job_logs.docs if x["id"] == lid)
    assert plog["presence"]["pause_min"] == 60 and plog["hours"][0]["hours"] == 7 and plog["presence"]["end_loc"] is None, plog
    assert "pausa" in plog["text"], plog["text"]

    # 7) closure: what is open listed and confirmed first (AUT-CHI-01); then the final report in Report/, the reminders off (AUT-CHI-02)
    db.job_todos.docs.append({"id": "t1", "commessa_id": sid, "text": "ritirare il furgone", "done": False, "due_date": D.isoformat()})
    err = await deny(server.set_job_commessa_stato(sid, server.CommessaStatoPayload(stato="completata"), me), 409)
    assert err["code"] == "close_check" and err["problems"] == ["manca il rubinetto d'arresto"] and "Posa piatto doccia" in err["activities"][0]
    sub = next(x for x in db.collection_sub_items.docs if x["id"] == sid)
    assert sub["data"]["stato"] == "in lavorazione"
    await deny(server.set_job_commessa_stato(sid, server.CommessaStatoPayload(stato="completata", confirm_close=True), MARCO), (403, 404))
    v = await server.set_job_commessa_stato(sid, server.CommessaStatoPayload(stato="completata", confirm_close=True), me)
    assert v["stato"] == "completata"
    await settle()
    assert next(x for x in db.job_activities.docs if x["id"] == b["id"])["status"] == "annullata"
    assert next(x for x in db.job_todos.docs if x["id"] == "t1")["reminders_off"] is True
    fin = [w for w in db.work_reports.docs if w.get("commessa_id") == sid]
    assert fin and fin[-1]["template_name"] == "Report finale di commessa" and REPORTS[-1][1] == f"{base} / Report", (fin, REPORTS)
    parts = {s["title"] for s in fin[-1]["sections"]}
    import work_reports as wr
    assert parts == {"Dati della commessa", *dict(wr.COMMESSA_PARTS).values()}, parts     # all of it, costs and margin included (the administrator)
    BOT_SENT.clear()
    assert await server._activity_notifications(at(nxt, 18, 0)) == 0          # nothing more for a closed commessa
    print("ALL OK")

asyncio.run(main())
