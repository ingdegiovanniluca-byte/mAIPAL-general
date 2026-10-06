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
                if op == "$in" and val not in arg: return False
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
                for k, v in u.get("$inc", {}).items(): d[k] = (d.get(k) or 0) + v
                for k, v in u.get("$addToSet", {}).items():
                    arr = d.setdefault(k, [])
                    for x in (v["$each"] if isinstance(v, dict) and "$each" in v else [v]):
                        if x not in arr: arr.append(x)
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
            if _match(d, q): d.update(u.get("$set", {})); n += 1
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
import json as J
U = {"user_id": "u1", "email": "a@b.it", "name": "Luca"}
db.users.docs.append(U)




from fastapi import HTTPException
async def no_sharing(colls, current): return colls
server._add_sharing_info = no_sharing
class Agg:
    def __init__(s, out): s.out = out
    async def to_list(s, n): return s.out
db.collection_items.aggregate = lambda pipe: Agg([])

import io, base64, job_logs as jl
from PIL import Image

server._storage_targets = lambda uid: _none()
async def _none(): return []

CALLS = []
def said(client="", commessa="", hours=None, materials=None, problems=None, date=None):
    async def f(text, speaker, team, known=None, user_id=None, channel="web"):
        CALLS.append({"text": text, "speaker": speaker, "team": team, "known": known})
        return {"date": date or jl.today_local().isoformat(), "text": text.capitalize(), "hours": jl.clean_hours(hours or [], speaker),
                "materials": jl.clean_materials(materials or []), "problems": problems or [], "client": client, "commessa": commessa}
    return f

def jpeg_uri():
    b = io.BytesIO(); Image.new("RGB", (3000, 2000), (200, 80, 40)).save(b, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()

async def main():
    u = server.User(**U)
    me = await server.update_profile(server.ProfilePatch(business_vertical="artigiano"), u)
    db.users.docs.append({"user_id": "u9", "email": "g@x.it", "name": "Gino Neri", "org_id": me.org_id, "org_role": "member"})
    cl = next(c for c in db.collections.docs if c.get("system_key") == "artigiano_clienti")
    def client(i, name): db.collection_items.docs.append({"id": i, "collection_id": cl["id"], "data": {"nome": name}})
    def comm(i, item, title, stato): db.collection_sub_items.docs.append({"id": i, "collection_id": cl["id"], "item_id": item, "data": {"titolo": title, "stato": stato}})
    client("c_rossi", "Mario Rossi"); comm("s_bagno", "c_rossi", "Bagno", "in corso"); comm("s_old", "c_rossi", "Caldaia", "chiusa")
    client("c_bianchi", "Anna Bianchi"); comm("s_cucina", "c_bianchi", "Cucina", "in corso"); comm("s_tetto", "c_bianchi", "Tetto", "preventivo")
    client("c_verdi", "Luigi Verdi")

    # 1) the client has one open commessa -> that one; hours per person, "io" = the speaker
    jl.interpret = said(client="Rossi", hours=[{"who": "io", "hours": 4}, {"who": "Gino", "hours": "4,5"}],
                        materials=[{"name": "corrugato 25", "qty": 20, "unit": "m"}], problems=["manca una scatola 503"])
    r = await server._save_job_log(me, "oggi io e Gino dai Rossi, 20 metri di corrugato, manca una scatola 503")
    print(r["message"])
    assert r["status"] == "ok" and r["log"]["commessa_id"] == "s_bagno" and r["log"]["client_name"] == "Mario Rossi"
    assert r["log"]["hours"] == [{"who": "Luca", "hours": 4.0}, {"who": "Gino", "hours": 4.5}]
    assert "Luca 4 h, Gino 4,5 h (totale 8,5 h)" in r["message"] and "20 m corrugato 25" in r["message"]
    assert CALLS[-1]["speaker"] == "Luca" and CALLS[-1]["team"] == ["Luca", "Gino"]

    # 2) a client with two open commesse -> asked; then saved on the chosen one
    jl.interpret = said(client="Bianchi")
    r = await server._save_job_log(me, "dalla Bianchi abbiamo smontato i pensili")
    print(r["message"], [c["title"] for c in r["candidates"]])
    assert r["status"] == "pick_commessa" and {c["commessa_id"] for c in r["candidates"]} == {"s_cucina", "s_tetto"}
    r = await server._save_job_log(me, r["text"], commessa_id="s_cucina")
    assert r["log"]["commessa_id"] == "s_cucina" and CALLS[-1]["known"] == {"title": "Cucina", "client": "Anna Bianchi"}
    # ...naming the job too: no question
    r = await server._save_job_log(me, "dalla Bianchi per il tetto: sopralluogo con il ponteggista")
    assert r["status"] == "ok" and r["log"]["commessa_id"] == "s_tetto"
    # 3) no names: the conversation's commessa; with none, asked among the open ones (never the closed)
    jl.interpret = said()
    r = await server._save_job_log(me, "nel pomeriggio finito il massetto", hint_commessa_id="s_bagno")
    assert r["log"]["commessa_id"] == "s_bagno"
    r = await server._save_job_log(me, "nel pomeriggio finito il massetto")
    assert r["status"] == "pick_commessa" and "s_old" not in {c["commessa_id"] for c in r["candidates"]} and len(r["candidates"]) == 3
    # 4) a client in the list without open commesse -> one is opened ("in corso")
    jl.interpret = said(client="Verdi", commessa="Cancello")
    r = await server._save_job_log(me, "da Verdi montato il motore del cancello")
    assert r["commessa_created"] and r["log"]["commessa_title"] == "Cancello" and "Commessa nuova" in r["message"]
    new = next(s for s in db.collection_sub_items.docs if s["id"] == r["log"]["commessa_id"])
    assert new["item_id"] == "c_verdi" and new["data"]["stato"] == "in corso" and new["data"]["data_inizio"]
    # 5) a client not in the list: asked, never created silently; "è nuovo" -> client + commessa
    n_items = len(db.collection_items.docs)
    jl.interpret = said(client="Esposito", commessa="Impianto box")
    r = await server._save_job_log(me, "dagli Esposito tracce per l'impianto del box")
    assert r["status"] == "pick_commessa" and r["new_client_name"] == "Esposito" and len(db.collection_items.docs) == n_items
    r = await server._save_job_log(me, r["text"], new_client_name="Esposito")
    assert r["client_created"] and r["commessa_created"] and r["log"]["client_name"] == "Esposito" and r["log"]["commessa_title"] == "Impianto box"
    # 6) namesakes without open commesse -> client chosen -> new commessa for them
    client("c_verdi2", "Paolo Verdi")
    db.collection_sub_items.docs = [s for s in db.collection_sub_items.docs if s["item_id"] != "c_verdi"]
    jl.interpret = said(client="Verdi")
    r = await server._save_job_log(me, "dai Verdi preventivo per il cancello")
    assert r["status"] == "pick_commessa" and {c["item_id"] for c in r["clients"]} == {"c_verdi", "c_verdi2"}
    r = await server._save_job_log(me, r["text"], client_item_id="c_verdi2")
    assert r["commessa_created"] and r["log"]["client_item_id"] == "c_verdi2"
    assert r["log"]["commessa_title"] == "Lavori"
    # a commessa called just "Lavori" is not picked by "finiti i lavori": the conversation's one is
    jl.interpret = said()
    r = await server._save_job_log(me, "finiti i lavori di oggi", hint_commessa_id="s_cucina")
    assert r["log"]["commessa_id"] == "s_cucina", r["log"]["commessa_title"]

    # 7) photos: kept in mAIPAL compressed, served back
    jl.interpret = said(client="Rossi", hours=[{"who": "io", "hours": 2}], materials=[{"name": "Corrugato 25", "qty": 5, "unit": "m"}])
    r = await server._save_job_log(me, "dai Rossi altri 5 metri di corrugato", images=[jpeg_uri(), "data:text/plain;base64,eHh4"])
    assert len(r["log"]["photos"]) == 1 and "1 foto" in r["message"]
    ph = db.job_photos.docs[0]
    raw = base64.b64decode(ph["data_b64"]); assert len(raw) <= server.JOB_PHOTO_MAX_BYTES
    assert max(Image.open(io.BytesIO(raw)).size) <= server.JOB_PHOTO_MAX_DIM
    resp = await server.get_job_photo(ph["id"], me); assert resp.media_type == "image/jpeg" and resp.body == raw
    await asyncio.sleep(0)

    # 8) the commessa page: entries newest first, totals (materials summed by name+unit)
    d = await server.get_job_commessa("s_bagno", me)
    t = d["totals"]; print(t["hours_total"], t["by_person"], t["materials"])
    assert t["hours_total"] == 10.5 and t["by_person"] == {"Luca": 6.0, "Gino": 4.5}
    assert [(m["name"].lower(), m["unit"], m["qty"]) for m in t["materials"]] == [("corrugato 25", "m", 25.0)] and t["problems"][0]["text"] == "manca una scatola 503"
    assert d["commessa"]["client_name"] == "Mario Rossi" and d["logs"][0]["created_at"] >= d["logs"][-1]["created_at"]
    # edit hours, delete the photo, delete an entry
    lid = r["log"]["id"]
    out = await server.update_job_log(lid, server.JobLogPatch(hours=[{"who": "Luca", "hours": 3}], date="2099-01-01"), me)
    assert out["hours"] == [{"who": "Luca", "hours": 3.0}] and out["date"] == jl.today_local().isoformat()
    out = await server.delete_job_photo(lid, ph["id"], me)
    assert out["photos"] == [] and not db.job_photos.docs
    await server.delete_job_log(lid, me)
    assert not any(l["id"] == lid for l in db.job_logs.docs)
    # stato -> chiusa sets the end date; list: in corso first, chiuse last
    v = await server.set_job_commessa_stato("s_bagno", server.CommessaStatoPayload(stato="chiusa"), me)
    assert v["stato"] == "chiusa" and v["data_fine"]
    rows = await server.list_job_commesse(me)
    print([(c["title"], c["stato"], c["entries"]) for c in rows])
    assert rows[-1]["stato"] == "chiusa" and rows[0]["stato"] == "in corso"
    try:
        await server.set_job_commessa_stato("s_bagno", server.CommessaStatoPayload(stato="boh"), me); assert False
    except HTTPException as he:
        assert he.status_code == 400

    # 9) another user (no team) can't see the commessa
    other = server.User(user_id="zz", email="z@z", name="Zed")
    try:
        await server.get_job_commessa("s_cucina", other); assert False
    except HTTPException as he:
        assert he.status_code == 404

    # 10) Cerca: the entries, and the totals when the question names the client
    async def no_emb(*a, **k): raise RuntimeError("offline")
    retrieval.emb.embed_query = no_emb; retrieval.emb.embed_texts = no_emb
    hits = await retrieval.retrieve(db, "u1", "quante ore abbiamo fatto dai Rossi?", scope="all", org_id=me.org_id)
    summ = [h["display"] for h in hits if h["display"].startswith("[Riepilogo diario commessa")]
    print(summ)
    assert summ and "«Bagno» · Mario Rossi" in summ[0] and "Ore totali: 8,5 h (Luca 4 h, Gino 4,5 h)" in summ[0] and "manca una scatola 503" in summ[0]
    hits = await retrieval.retrieve(db, "u1", "chi ha smontato i pensili?", scope="all", org_id=me.org_id)
    jh = [h for h in hits if h["source"] == "job_log" and "pensili" in h["display"].lower()]
    assert jh and "Anna Bianchi · Cucina (Luca)" in jh[0]["display"], hits
    # 11) Telegram: the diary goes to the diario di commessa, buttons when it can't tell
    import telegram_bot as tb
    SENT = []
    class Msg:
        def __init__(s, chat): s.chat = type("C", (), {"id": chat})()
        async def reply_text(s, text, **k): SENT.append((text, k.get("reply_markup")))
    class Bot:
        async def send_chat_action(s, **k): pass
        async def send_message(s, chat_id, text, reply_markup=None, **k): SENT.append((text, reply_markup))
    class Ctx: bot = Bot()
    await db.users.update_one({"user_id": "u1"}, {"$set": {"telegram_chat_id": 77, "business_vertical": "artigiano",
                                                          "org_id": me.org_id, "org_role": "owner"}})
    user = await db.users.find_one({"user_id": "u1"})
    upd = type("U", (), {})(); upd.message = Msg(77); upd.effective_chat = upd.message.chat
    jl.interpret = said(client="Bianchi", hours=[{"who": "io", "hours": 3}])
    await tb._run_and_reply(upd, Ctx(), db, user, "journal", "dalla Bianchi 3 ore")
    text, kb = SENT[-1]; print(text)
    assert "Di quale commessa" in text and {r[0].callback_data for r in kb.inline_keyboard} == {"jobc:s_cucina", "jobc:s_tetto"}
    st = await tb._get_state(db, "u1", 77)
    assert st["pending_job_context"]["text"] == "dalla Bianchi 3 ore"
    # answered by writing instead of the button
    jl.interpret = said(client="Bianchi", hours=[{"who": "io", "hours": 3}])
    assert await tb._answer_pending_job(upd, Ctx(), db, user, st, "la cucina")
    print(SENT[-1][0]); assert "«Cucina»" in SENT[-1][0] and "Luca 3 h" in SENT[-1][0]
    st = await tb._get_state(db, "u1", 77)
    assert st["job_commessa_id"] == "s_cucina" and not st.get("pending_job_context")
    # a follow-up without names stays on that commessa; a photo with no caption joins the entry
    jl.interpret = said(materials=[{"name": "silicone", "qty": 2, "unit": "pz"}])
    await tb._run_and_reply(upd, Ctx(), db, user, "journal", "usati anche due tubi di silicone")
    assert "«Cucina»" in SENT[-1][0] and "2 pz silicone" in SENT[-1][0]
    st = await tb._get_state(db, "u1", 77)
    await tb._run_and_reply(upd, Ctx(), db, user, "journal", tb.PHOTO_ONLY, images=[jpeg_uri()])
    print(SENT[-1][0]); assert SENT[-1][0].startswith("📷 Foto aggiunta al diario di «Cucina»")
    lg = next(l for l in db.job_logs.docs if l["id"] == st["job_log_id"]); assert len(lg["photos"]) == 1
    # the button path
    jl.interpret = said()
    db.users.docs[0]["telegram_chat_id"] = 78
    upd2 = type("U", (), {})(); upd2.message = Msg(78); upd2.effective_chat = upd2.message.chat
    await tb._run_and_reply(upd2, Ctx(), db, user, "journal", "pulizia finale del cantiere")
    assert "commessa" in SENT[-1][0]
    q = type("Q", (), {})(); q.message = Msg(78); q.data = "jobc:s_tetto"
    async def ans(*a, **k): pass
    q.answer = ans
    upd3 = type("U", (), {})(); upd3.callback_query = q; upd3.effective_chat = q.message.chat
    await tb._on_callback(upd3, Ctx())
    print(SENT[-1][0]); assert "«Tetto»" in SENT[-1][0]
    # a non-artigiano keeps the usual diary
    assert not await tb._answer_pending_job(upd, Ctx(), db, user, {"chat_id": 1}, "x")
    # classifier prompt mentions the cantiere only for an artigiano
    # 12) the watch: same engine, the conversation remembers its commessa
    jl.interpret = said(client="Rossi")
    reply, conv = await tb._process_action(db, user, "journal", "dai Rossi controllato il quadro", None, channel="watch")
    print(reply); assert "Mario Rossi non ha commesse aperte" in reply and "Bagno — Mario Rossi" in reply
    assert not any(s_["data"].get("titolo") == "Lavori" and s_["item_id"] == "c_rossi" for s_ in db.collection_sub_items.docs)
    # on Telegram the same question offers "nuova commessa per Mario Rossi" -> opened for them
    await tb._run_and_reply(upd, Ctx(), db, user, "journal", "dai Rossi controllato il quadro")
    datas = [r[0].callback_data for r in SENT[-1][1].inline_keyboard]
    assert "jobk:c_rossi" in datas and "jobc:s_bagno" in datas
    jl.interpret = said(client="Bianchi")
    reply, conv = await tb._process_action(db, user, "journal", "dalla Bianchi per la cucina, montati i pensili", None, channel="watch")
    assert "«Cucina»" in reply
    jl.interpret = said()
    reply, conv2 = await tb._process_action(db, user, "journal", "e cambiato un interruttore", conv, channel="watch")
    assert conv2 == conv and "«Cucina»" in reply
    # 13) @diario in the web chat, right after a report: that report's commessa
    db.work_reports.docs.append({"id": "wrep_x", "commessa_id": "s_tetto"})
    jl.interpret = said()
    res = await server._run_sub_agent(me, "journal", "domani portiamo il ponteggio", "...", {"type": "work_report", "id": "wrep_x"}, "conv_w")
    print(res); assert res["status"] == "ok" and "«Tetto»" in res["message"]
    res = await server._run_sub_agent(me, "journal", "pulito tutto", "...", None, "conv_w2")
    assert res["status"] == "error" and "Non l'ho salvato" in res["message"]
    print("ALL OK")
asyncio.run(main())
