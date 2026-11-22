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


import weather as wx
from zoneinfo import ZoneInfo
ROME = ZoneInfo("Europe/Rome")


async def deny(coro, code=403):
    try:
        await coro
    except HTTPException as e:
        assert e.status_code in (code if isinstance(code, tuple) else (code,)), (e.status_code, e.detail)
        return e.detail
    raise AssertionError("not denied")


async def rainy(lat, lon, day):
    return {"rain_pct": 80, "wind_kmh": 12, "tmin": 9, "tmax": 15, "code": 61}
wx.provider = rainy
PINS = []
async def fake_pin_send(chat_id, text, kb):
    PINS.append(("send", chat_id, text, kb)); return 1000 + len(PINS)
async def fake_pin_edit(chat_id, mid, text, kb):
    PINS.append(("edit", chat_id, text, kb))
async def fake_pin_unpin(chat_id, mid):
    PINS.append(("unpin", chat_id, None, None))
server._day_pin_send, server._day_pin_edit, server._day_pin_unpin = fake_pin_send, fake_pin_edit, fake_pin_unpin


def at(day, hh, mm=0):
    return datetime.combine(day, datetime.min.time(), tzinfo=ROME).replace(hour=hh, minute=mm).astimezone(timezone.utc)


def to(chat):
    return [(t, kb) for c, t, kb in BOT_SENT if c == chat]


async def main():
    """The commessa's value and expected cost: the same in the Clienti list and in the diary (Costi), both ways; a plan for
    "questo pomeriggio"; people tagged with @ in the commessa's chat."""
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), server.User(**U))
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    smap = cl["system_sub_map"]
    assert smap.get("valore") and smap.get("spesa_prevista")
    assert {f["label"] for f in cl["sub_item_fields"]} >= {"Valore commessa", "Spesa prevista"}
    assert not any("aliases" in f for f in cl["sub_item_fields"])
    # a list with its own column for it ("Importo") keeps it: mapped, not doubled
    fields, m = server.vx.merge_system_fields([{"key": "titolo", "label": "Titolo"}, {"key": "importo", "label": "Importo", "type": "text"}],
                                              server.vx.COMMESSA_FIELDS)
    assert m["valore"] == "importo" and [f["label"] for f in fields].count("Valore commessa") == 0
    assert server._money_val("12.500,50 €") == 12500.5 and server._money_val("€ 3.200") == 3200 and server._money_val("8000") == 8000 \
        and server._money_val("") is None and server._money_val("da definire") is None

    db.collection_items.docs.append({"id": "c_rossi", "collection_id": cl["id"], "data": {"nome": "Mario Rossi"}})
    db.collection_sub_items.docs.append({"id": "s_bagno", "collection_id": cl["id"], "item_id": "c_rossi", "geo": {"lat": 45.07, "lon": 7.68, "source": "manual"},
                                         "data": {"titolo": "Bagno", "stato": "in lavorazione", "indirizzo_cantiere": "Via Garibaldi 5, Torino",
                                                  smap["valore"]: "9.000 €"}})
    sub = lambda: next(x for x in db.collection_sub_items.docs if x["id"] == "s_bagno")
    econ = lambda: next((e for e in db.job_economics.docs if e["commessa_id"] == "s_bagno"), {})

    # 1) at the start: a value only in the list goes in the diary
    await server._migrate_list_values()
    assert econ()["budget"] == 9000 and server._money_val(sub()["data"][smap["valore"]]) == 9000   # (the list keeps its own writing)

    # 2) the list changed -> the diary (with its line and history)
    data = {**sub()["data"], smap["valore"]: "12.500 €", smap["spesa_prevista"]: "8.000"}
    await server.update_sub_item(cl["id"], "c_rossi", "s_bagno", server.CollectionSubItemPayload(data=data), me)
    assert econ()["budget"] == 12500 and econ()["expected_cost"] == 8000
    assert any(lg.get("kind") == "valore" and "scritto nella lista Clienti" in lg["text"] for lg in db.job_logs.docs)
    e = await server.get_commessa_economics("s_bagno", me)
    assert e["budget"] == 12500 and e["expected_cost"] == 8000 and e["expected_margin"] == 4500

    # 3) the diary changed (Costi) -> the list
    await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(budget=13000), me)
    assert sub()["data"][smap["valore"]] == 13000
    await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(expected_cost=8500), me)
    assert sub()["data"][smap["spesa_prevista"]] == 8500 and econ()["budget"] == 13000
    await server.patch_commessa_economics("s_bagno", server.EconomicsPatch(clear_expected_cost=True), me)
    assert sub()["data"][smap["spesa_prevista"]] == "" and econ()["expected_cost"] is None

    # 4) "questo pomeriggio è prevista …, assegnala a …": a plan for today, to that person
    c = await server.create_collaborator(server.CollaboratorPayload(first_name="Avanzino", last_name="Neri", company="Neri Impianti", commesse=["s_bagno"]), me)
    av = next(x for x in db.collaborators.docs if x["id"] == c["collaborator"]["id"])
    av.update(status="active", telegram_chat_id=950)
    t = "questo pomeriggio è prevista la prova fumi assegnala a avanzino"
    assert jl.future_activity_said(t) and jl.said_day(t, jl.today_local()) == jl.today_local().isoformat()
    assert not jl.future_activity_said("oggi è prevista pioggia") and not jl.future_activity_said("oggi c'è il ponteggio montato")
    async def read_act(text, people, user_id=None, channel="web"):
        return {"description": "Prova fumi", "date": jl.said_day(text, jl.today_local()), "start": "", "end": "", "assignees": [], "items": [], "info": ""}
    jl.read_activity = read_act
    jl.interpret = said()
    # tagged with @ in the chat: on it even when the reader of the message names nobody
    tagged = await server._tagged_people(me, "s_bagno", [{"type": "collab", "id": av["id"]}, {"type": "collab", "id": "nobody"}])
    assert [p["name"] for p in tagged] == ["Avanzino Neri"]
    r = await server._save_job_log(me, "questo pomeriggio è prevista la prova fumi assegnala a Avanzino Neri", commessa_id="s_bagno", tagged=tagged)
    assert r["status"] == "commessa_update", r
    a = [x for x in db.job_activities.docs if x["description"] == "Prova fumi"][-1]
    assert a["date"] == jl.today_local().isoformat() and [p["name"] for p in a["assignees"]] == ["Avanzino Neri"]

    # 5) a diary note with someone tagged: saved, and sent to them (Telegram for a collaborator)
    BOT_SENT.clear()
    out = await server.create_job_log(server.JobLogPayload(text="Avanzino Neri controlla la pressione dell'impianto, oggi fatto il lavaggio",
                                                           commessa_id="s_bagno", tagged=[{"type": "collab", "id": av["id"]}]), me)
    assert out["status"] == "ok" and "🔔 L'ho mandata a Avanzino" in out["message"], out
    assert any("ti ha taggato in una nota su «Bagno»" in t_ for t_, _ in to(950)), to(950)
    assert next(x for x in db.job_logs.docs if x["id"] == out["log"]["id"])["tagged"][0]["name"] == "Avanzino Neri"

    # 6) who doesn't see the costs doesn't see the list's money columns (list, its commesse, Cerca)
    MARCO = server.User(**db.users.docs[1])
    assert not await server._sees_costs(MARCO) and await server._sees_costs(me)
    subs = [dict(sub(), data=dict(sub()["data"]))]
    hidden = await server._hide_money(MARCO, dict(cl), subs)
    assert not {smap["valore"], smap["spesa_prevista"]} & {f["key"] for f in hidden["sub_item_fields"]}
    assert smap["valore"] not in subs[0]["data"] and subs[0]["data"]["titolo"] == "Bagno"
    shown = await server._hide_money(me, dict(cl), [dict(sub(), data=dict(sub()["data"]))])
    assert {smap["valore"]} <= {f["key"] for f in shown["sub_item_fields"]}
    found = await retrieval.retrieve(db, "u1", "commessa Bagno valore", scope="all", hide_sub_keys={smap["valore"], smap["spesa_prevista"]})
    assert not any("Valore commessa" in (h.get("display") or "") for h in found), [h.get("display") for h in found]

    # 7) an administrator corrects a collaborator's note: the collaborator told what changed
    db.job_logs.docs.append({"id": "lgav", "commessa_id": "s_bagno", "commessa_title": "Bagno", "collaborator_id": av["id"], "author_name": "Avanzino",
                             "date": jl.today_local().isoformat(), "text": "montate 3 scatole 503", "raw_text": "montate 3 scatole 503",
                             "hours": [{"who": "Avanzino", "hours": 8}], "materials": [{"name": "scatole 503", "qty": 3, "unit": "pz"}], "problems": []})
    BOT_SENT.clear()
    await server.update_job_log("lgav", server.JobLogPatch(materials=[{"name": "scatole 503", "qty": 2, "unit": "pz"}]), me)
    await asyncio.sleep(0.05)
    t_ = next(t for t, _ in to(950) if "ha corretto la tua nota" in t)
    assert "• Materiali: 3 pz scatole 503 → 2 pz scatole 503" in t_ and "«Bagno»" in t_, t_

    # 8) an administrator deletes someone else's note: written in the diary, its author told
    BOT_SENT.clear()
    await server.delete_job_log("lgav", me)
    await asyncio.sleep(0.05)
    assert not any(x["id"] == "lgav" for x in db.job_logs.docs)
    ev = [x for x in db.job_logs.docs if x.get("kind") == "nota_eliminata"][-1]
    assert ev["text"].startswith("🗑 Nota di Avanzino del") and "eliminata da Luca" in ev["text"] and "montate 3 scatole 503" in ev["text"], ev["text"]
    assert any("ha eliminato la tua nota" in t for t, _ in to(950)), to(950)

    # 9) a notice to the administrator ("ancora in cantiere", the answer…): in the app too, where the preferences say so
    import notify_prefs as nprefs
    PUSHED = []
    real_push = server.push.fire_and_forget
    server.push.fire_and_forget = lambda db_, uid, title, body, url="/dashboard", tag=None, kind=None: PUSHED.append((uid, title, body, kind))
    me_doc = server.User(**next(u for u in db.users.docs if u["user_id"] == "u1"))
    await nprefs.set_pref(db, "u1", "presence", True, "both")
    BOT_SENT.clear(); NOTICES.clear()
    await server._notify_owner(me_doc, "✅ *Avanzino Neri* conferma di essere ancora in cantiere su «Bagno».", kind="presence")
    assert NOTICES and PUSHED[-1][0] == "u1" and PUSHED[-1][1].startswith("✅ Avanzino Neri conferma") and PUSHED[-1][3] == "presence", PUSHED
    n = len(PUSHED)
    await server._notify_owner(me_doc, "x", kind="presence", push_too=False)   # (the caller sends its own)
    assert len(PUSHED) == n
    await nprefs.set_pref(db, "u1", "presence", True, "telegram")
    real_push(db, "u1", "t", "b", kind="presence")   # telegram only: the app's push is not sent (checked inside)
    server.push.fire_and_forget = real_push
    print("ALL OK")

asyncio.run(main())
