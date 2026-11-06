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

def said(kind="nota", text=None, hours=None, problems=None, materials=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web", photos=0):
        f.last = {"speaker": speaker, "team": team, "known": known}
        return {"kind": kind, "doubt": "", "date": jl.today_local().isoformat(), "text": text or t,
                "hours": jl.clean_hours(hours or [], speaker), "materials": jl.clean_materials(materials or []), "problems": problems or [], "client": "", "commessa": ""}
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
    async def send_message(s, chat_id=None, text=None, reply_markup=None, **k): BOT_SENT.append((chat_id, text, reply_markup))
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


import json as _json, types
MODEL_EXTRAS = {"extras": []}
CALLS = []
class FakeCompletions:
    async def create(self, **k):
        CALLS.append(k["messages"][1]["content"])
        msg = types.SimpleNamespace(content=_json.dumps(MODEL_EXTRAS))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None, model="x", id="r1")
class FakeOpenAI:
    def __init__(self, *a, **k): self.chat = types.SimpleNamespace(completions=FakeCompletions())
jl.openai.AsyncOpenAI = FakeOpenAI

import nearby as nb, site_presence as sp

ORIGIN = {"lat": 45.0700, "lon": 7.6800}          # where I am (Torino)
def north(km_):                                     # a point km_ north of me
    return {"lat": round(ORIGIN["lat"] + km_ / 111.195, 6), "lon": ORIGIN["lon"]}
ROADS = []
async def fake_road(a, b):
    ROADS.append(b)
    return {"m": nb.distance_m(a, b) * 1.3, "min": 7}
nb.router = fake_road
GEOCODED = []
PLACES = {"Moncalieri": north(-8), "via Garibaldi 3, Torino": north(1)}
async def fake_geocode(addr):
    GEOCODED.append(addr)
    return PLACES.get(addr)
sp.geocode = fake_geocode


async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    MARCO = server.User(**db.users.docs[1])

    # 1) the question, read from the words (no model)
    assert nb.said("dammi l'elenco dei clienti vicino a me") == {"me": True, "place": None, "radius_km": None, "filter": None}
    assert nb.said("chi ho vicino entro 5 km?")["radius_km"] == 5
    assert nb.said("clienti vicini a via Roma 10, Torino") ["place"] == "via Roma 10, Torino"
    assert nb.said("cantieri aperti vicino a me")["filter"] == "aperte"
    assert nb.said("manutenzioni da fare qui intorno?")["filter"] == "manutenzione"
    assert nb.said("dove posso passare qui vicino?")["filter"] == "opportunita"
    assert nb.said("clienti vicino a me nel raggio di 500 metri")["radius_km"] == 0.5
    assert nb.said("il vicino ha chiesto un preventivo per il bagno") is None
    assert nb.said("sono vicino al cantiere dei Rossi, arrivo tra 10 minuti") is None
    assert nb.said("oggi posato il gres") is None

    # 2) the clients: where they live and where their sites are; the nearest one counts
    def client(cid, name, addr="", geo=None, phone=""):
        it = {"id": cid, "collection_id": cl["id"], "data": {"nome": name, "indirizzo": addr, "telefono": phone}}
        if geo is not None:
            it["geo"] = {"address": addr, "source": "address", **geo}
        db.collection_items.docs.append(it)
    def job(sid, cid, title, stato, addr, geo):
        db.collection_sub_items.docs.append({"id": sid, "collection_id": cl["id"], "item_id": cid,
                                             "data": {"titolo": title, "stato": stato, "indirizzo_cantiere": addr},
                                             "geo": {"address": addr, "source": "address", **geo}})
    client("c_anna", "Anna Verdi", "via Po 1, Torino", north(2), "011 123 4567")             # no commesse: at the bottom
    client("c_bruno", "Bruno Neri", "via Lontana 9, Chieri", north(8))
    job("s_bruno", "c_bruno", "Bagno", "in lavorazione", "corso Francia 5, Torino", north(3))  # his site is nearer
    client("c_carla", "Carla Blu", "via Nizza 4, Torino", north(6))
    job("s_carla", "c_carla", "Cucina", "preventivo inviato", "via Nizza 4, Torino", north(6))
    client("c_hugo", "Hugo Gialli", "via Cibrario 7, Torino", north(5))
    job("s_hugo", "c_hugo", "Caldaia", "completata", "via Cibrario 7, Torino", north(5))
    due = (jl.today_local() + timedelta(days=20)).isoformat()
    db.tasks.docs.append({"id": "t1", "commessa_id": "s_hugo", "kind": "manutenzione", "completed": False, "due_date": due, "title": "Manutenzione caldaia"})
    client("c_dario", "Dario Rosa", "Asti", north(25))                                       # out of the radius
    client("c_elena", "Elena Viola")                                                          # no address
    client("c_franco", "Franco Grigi", "via Inesistente 99", {"lat": None, "lon": None})      # looked up, not found
    client("c_gino", "Gino Bruni", "via Garibaldi 3, Torino")                                 # not looked up yet

    res = await server._nearby_search(me, ORIGIN)
    names = [r["name"] for r in res["rows"]]
    assert res["radius_km"] == 10 and names == ["Bruno Neri", "Hugo Gialli", "Carla Blu", "Anna Verdi"], names
    bruno, hugo, carla, anna = res["rows"]
    assert bruno["via"] == "cantiere «Bagno»" and abs(bruno["distance_m"] - 3000) < 20 and [c["title"] for c in bruno["commesse"]] == ["Bagno"]
    assert hugo["commesse"] == [] and hugo["opportunities"] == [f"manutenzione da fare entro il {server._short_it_date(due)}"]
    assert carla["opportunities"] == ["preventivo in attesa di esito («Cucina»)"]
    assert anna["commesse"] == [] and anna["opportunities"] == [] and anna["phone"] == "011 123 4567" and anna["via"] == ""
    # the road for the first 3 only, the straight line for the others
    assert all(r.get("road_m") for r in res["rows"][:3]) and "road_m" not in anna and len(ROADS) == 3
    assert res["missing"] == {"no_address": 1, "not_found": 1, "pending": 1}, res["missing"]
    assert anna["maps"].startswith("https://www.google.com/maps/dir/?api=1&destination=45.")
    txt = nb.message(res)
    assert txt.startswith("📍 4 clienti vicino a te entro 10 km:") and "1. *Bruno Neri* — 3,9 km su strada, 7 min (cantiere «Bagno»)" in txt, txt
    assert "💡 preventivo in attesa di esito («Cucina»)" in txt and "📞 011 123 4567" in txt and "4. *Anna Verdi* — 2,0 km" in txt
    assert "Non nell'elenco: 1 senza indirizzo, 1 con un indirizzo che non trovo, 1 ancora da localizzare" in txt
    # the address not looked up yet: found in the background, then in the list
    for _ in range(100):
        if (next(i for i in db.collection_items.docs if i["id"] == "c_gino").get("geo") or {}).get("lat"):
            break
        await asyncio.sleep(0.05)
    assert "via Garibaldi 3, Torino" in GEOCODED and "via Po 1, Torino" not in GEOCODED          # each address once
    res = await server._nearby_search(me, ORIGIN)
    assert "Gino Bruni" in [r["name"] for r in res["rows"]] and "pending" not in res["missing"]

    # 3) the radius from the settings, or the one said; the nearest when nobody is inside
    ten = next(t for t in db.tenants.docs if t["id"] == "ten_1")
    ten["settings"] = {**(ten.get("settings") or {}), "nearby_radius_km": 4}
    res = await server._nearby_search(me, ORIGIN)
    assert res["radius_km"] == 4 and [r["name"] for r in res["rows"]] == ["Bruno Neri", "Gino Bruni", "Anna Verdi"], [r["name"] for r in res["rows"]]
    ten["settings"]["nearby_radius_km"] = 10
    res = await server._nearby_search(me, ORIGIN, radius_km=0.5)
    assert res["rows"] == [] and res["nearest"]["name"] == "Gino Bruni"
    assert "Nessun cliente vicino a te entro 0,5 km" in nb.message(res) or "Nessun cliente vicino a te entro 0.5 km" in nb.message(res)
    assert "Il più vicino è Gino Bruni, a 1,0 km: chiedimi «entro 1 km»" in nb.message(res), nb.message(res)

    # 4) the filters: open commesse, quotes, maintenances, opportunities
    rows = lambda r: [x["name"] for x in r["rows"]]
    assert rows(await server._nearby_search(me, ORIGIN, 30, "aperte")) == ["Bruno Neri", "Carla Blu"]
    assert rows(await server._nearby_search(me, ORIGIN, 30, "preventivi")) == ["Carla Blu"]
    assert rows(await server._nearby_search(me, ORIGIN, 30, "manutenzione")) == ["Hugo Gialli"]
    assert rows(await server._nearby_search(me, ORIGIN, 30, "opportunita")) == ["Hugo Gialli", "Carla Blu", "Bruno Neri"]
    assert "Dario Rosa" in rows(await server._nearby_search(me, ORIGIN, 30))

    # 5) the endpoints: my position needed; a place on the map; a commessa named
    assert (await server.nearby_intent(server.NearbyPayload(text="clienti vicino a me?"), me))["nearby"]["me"]
    assert (await server.nearby_intent(server.NearbyPayload(text="ho finito il bagno"), me))["nearby"] is None
    await deny(server.nearby_search(server.NearbyPayload(text="dammi i clienti vicino a me"), me), 400)
    out = await server.nearby_search(server.NearbyPayload(text="dammi i clienti vicino a me", lat=ORIGIN["lat"], lon=ORIGIN["lon"]), me)
    assert out["rows"] and out["message"].startswith("📍 ")
    out = await server.nearby_search(server.NearbyPayload(text="clienti vicino a Moncalieri entro 3 km"), me)
    assert out["place"] == "Moncalieri" and out["radius_km"] == 3 and out["rows"] == [] and out["nearest"]
    out = await server.nearby_search(server.NearbyPayload(text="clienti vicino al cantiere Bagno dei Neri entro 2 km"), me)
    assert [r["name"] for r in out["rows"]][0] == "Bruno Neri" and out["rows"][0]["distance_m"] == 0, out["rows"]
    await deny(server.nearby_search(server.NearbyPayload(text="clienti vicino a Paperopoli"), me), 400)
    # another vertical: not a nearby question
    db.users.docs.append({"user_id": "u9", "email": "v@b.it", "name": "Vet", "role": "user", "tenant_id": "ten_9", "business_vertical": "veterinario"})
    assert (await server.nearby_intent(server.NearbyPayload(text="clienti vicino a me?"), server.User(**db.users.docs[-1])))["nearby"] is None

    # 6) Telegram: the question, the button for the position, the list
    udoc = next(u for u in db.users.docs if u["user_id"] == "u1")
    REPLIES.clear()
    assert await tg._try_nearby(Upd(77, "chi ho vicino entro 5 km?"), Ctx(), db, udoc, "chi ho vicino entro 5 km?")
    txt, kb = REPLIES[-1]
    assert "Mandami la tua posizione" in txt and "entro 5 km" in txt and kb.keyboard[0][0].request_location
    state = await tg._get_state(db, "u1", 77)
    assert state["pending_nearby"]["radius_km"] == 5
    u = Upd(77, None)
    u.message.location = types.SimpleNamespace(latitude=ORIGIN["lat"], longitude=ORIGIN["lon"])
    await tg._on_location(u, Ctx())
    txt, kb = REPLIES[-1]
    assert txt.startswith("📍 4 clienti vicino a te entro 5 km:") and "2. *Hugo Gialli* — 6,5 km su strada, 7 min\n" in txt and "Dario" not in txt, txt
    assert isinstance(kb, telegram.ReplyKeyboardRemove)
    assert not (await tg._get_state(db, "u1", 77)).get("pending_nearby")
    # a place: no position asked
    REPLIES.clear()
    assert await tg._try_nearby(Upd(77, "clienti vicino a via Garibaldi 3, Torino"), Ctx(), db, udoc, "clienti vicino a via Garibaldi 3, Torino")
    assert REPLIES[-1][0].startswith("📍 ") and "vicino a via Garibaldi 3, Torino" in REPLIES[-1][0]
    # a note is not a question
    assert not await tg._try_nearby(Upd(77, "x"), Ctx(), db, udoc, "sono vicino al cantiere, arrivo")
    print("ALL OK")

asyncio.run(main())
