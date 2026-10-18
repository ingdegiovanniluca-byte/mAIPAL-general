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
import job_logs as jl, telegram_bot as tg, retrieval, embeddings as emb
import scheduled_actions as sa
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

U = {"user_id": "u1", "email": "a@b.it", "name": "Luca Rossi", "role": "admin", "telegram_chat_id": 77}
db.users.docs.append(dict(U))
tg.bot_token = lambda: "123:abc"
NOTICES = []
async def fake_send(chat_id, text):
    NOTICES.append((chat_id, text)); return True
server._send_telegram_text = fake_send
async def no_emb(q): raise RuntimeError("offline")
emb.embed_query = no_emb
def said(hours=None, materials=None, problems=None, date=None):
    async def f(t, speaker, team, known=None, user_id=None, channel="web"):
        return {"kind": "nota", "doubt": "", "date": date or jl.today_local().isoformat(), "text": t,
                "hours": jl.clean_hours(hours or [], speaker), "materials": jl.clean_materials(materials or []),
                "problems": problems or [], "client": "", "commessa": ""}
    return f
ANSWERS = []
async def fake_answer(commessa, logs, reports, question, history, user_id=None, channel="web"):
    ANSWERS.append(commessa); return {"answer": "ok", "is_entry": False}
jl.answer = fake_answer

async def settle():
    for _ in range(5):
        await asyncio.sleep(0)

import re
import fitness as fx
CALLS = []
def fake_llm(plan):
    async def f(system, prompt, current, model, feature="creazione_lezioni"):
        CALLS.append((model, system))
        if model == "gpt-4o-mini":
            return json.dumps({"type": "Funzionale", "participants": None, "duration_min": None, "level": "medio", "body_parts": ["gambe"], "mode": None})
        return json.dumps(plan(system))
    return f
import json

async def main():
    me = await server.update_profile(server.ProfilePatch(business_vertical="fitness"), server.User(**U))
    me = server.User(**{**me.model_dump(), "business_vertical": "fitness"})
    # 1) the vertical's starting set, once
    ex = await server.list_exercises(me)
    assert len(ex) == 65 and all(e["builtin"] for e in ex)
    squat = next(e for e in ex if e["name"] == "Squat con due manubri")
    assert squat["equipment"] == "manubrio" and squat["equipment_per_person"] == 2 and squat["level"] == "alto"
    assert squat["timed"]["max_sec"] == 40 and squat["reps"]["max_reps"] == 12 and squat["body_part"] == "gambe"
    assert sum(1 for e in ex if e["role"] == "stretching") == 6 and sum(1 for e in ex if e["role"] == "riscaldamento") == 6
    eq = await server.list_equipment(me)
    assert {e["name"]: e["quantity"] for e in eq} == {"cavigliera": 20, "elastico piccolo": 30, "manubrio": 40}
    types = await server.list_lesson_types(me)
    assert [t["name"] for t in types] == ["Funzionale"] and types[0]["duration_min"] == 40 and types[0]["start_min"] == 5 and types[0]["end_kind"] == "stretching"
    await server._ensure_fitness_base(me)
    assert len(await server.list_exercises(me)) == 65 and len(await server.list_equipment(me)) == 3
    # deleted ones never come back
    await server.delete_exercise(ex[0]["id"], me)
    await server._ensure_fitness_base(me)
    assert len(await server.list_exercises(me)) == 64

    # 2) the user's exercises and equipment
    new = await server.create_exercise(server.ExerciseUpsert(name="  Plank  ", role="esercizio", body_part="Addome", level="intermedio",
        equipment="tappetino", equipment_per_person=1, timed={"allowed": True, "min_sec": "20", "max_sec": 60, "min_sets": 1, "max_sets": 3},
        reps={"allowed": False}), me)
    assert new["name"] == "Plank" and new["level"] == "medio" and new["body_part"] == "addome" and new["timed"]["min_sec"] == 20
    up = await server.update_exercise(new["id"], {"level": "avanzato", "notes": "schiena dritta"}, me)
    assert up["level"] == "alto" and up["notes"] == "schiena dritta"
    t = await server.add_equipment(server.EquipmentPayload(name="Tappetino", quantity=12), me)
    t2 = await server.add_equipment(server.EquipmentPayload(name="tappetino", quantity=3), me)   # the same: quantity added
    assert t2["quantity"] == 15 and len(await server.list_equipment(me)) == 4
    m = next(e for e in await server.list_equipment(me) if e["name"] == "manubrio")
    assert (await server.update_equipment(m["id"], server.EquipmentPayload(delta=-1), me))["quantity"] == 39
    assert (await server.update_equipment(m["id"], server.EquipmentPayload(quantity=40), me))["quantity"] == 40
    try:
        await server.add_equipment(server.EquipmentPayload(name=" "), me); assert False
    except server.HTTPException as e:
        assert e.status_code == 400

    # 3) rules: a type of their own; start + end can't take the whole lesson
    st = await server.create_lesson_type(server.LessonTypePayload(name="Tonificazione", duration_min=30, start_min=3, end_min=3, start_kind="riscaldamento",
                                                                  rules_text="massimo 2 esercizi con lo stesso attrezzo di seguito"), me)
    assert st["activity"] == "funzionale" and st["start_kind"] == "riscaldamento"
    try:
        await server.update_lesson_type(st["id"], server.LessonTypePayload(start_min=15, end_min=15), me); assert False
    except server.HTTPException as e:
        assert e.status_code == 400

    # 4) a lesson: rules of the type + request; only candidates; limits and time checked
    def plan(system):
        ids = re.findall(r"\[(inizio|centrale|fine)\] id=(\S+) \| ([^|]+)", system)
        by_phase = {}
        for ph, i, name in ids:
            by_phase.setdefault(ph, []).append(i)
        blocks = [{"phase": "inizio", "exercise_id": by_phase["inizio"][0], "mode": "tempo", "sets": 1, "seconds": 60}]
        blocks += [{"phase": "centrale", "exercise_id": i, "mode": "tempo", "sets": 9, "seconds": 999} for i in by_phase["centrale"][:6]]
        blocks += [{"phase": "centrale", "exercise_id": "invented", "mode": "tempo", "sets": 2, "seconds": 40}]
        blocks += [{"phase": "fine", "exercise_id": by_phase["fine"][0], "mode": "tempo", "sets": 1, "seconds": 60}]
        return {"title": "Gambe medio", "notes": "ok", "blocks": blocks}
    server._lesson_llm = fake_llm(plan)
    r = await server._generate_lesson(me, "lezione funzionale per 10 persone, livello medio, allenamento gambe")
    L = r["lesson"]
    sysmsg = CALLS[-1][1]
    assert "Partecipanti: 10" in sysmsg and "Livello: medio" in sysmsg and "Squat con due manubri" not in sysmsg   # alto: not for a medium class
    assert L["name"] == "Gambe medio", L["name"]
    assert L["participants"] == 10 and L["level"] == "medio" and L["body_parts"] == ["gambe"] and L["duration_min"] == 40
    phases = [b["phase"] for b in L["blocks"]]
    assert phases[0] == "inizio" and phases[-1] == "fine" and "invented" not in [b["exercise_id"] for b in L["blocks"]]
    by = {e["id"]: e for e in await server.list_exercises(me)}
    for b in L["blocks"]:
        e = by[b["exercise_id"]]
        assert b["seconds"] <= e["timed"]["max_sec"] and b["sets"] <= e["timed"]["max_sets"], b
        if b["phase"] == "centrale":
            assert e["body_part"] == "gambe" and fx.level_ok(e["level"], "medio")
    main = sum(fx.block_seconds(b, L["rest_sec"]) for b in L["blocks"] if b["phase"] == "centrale")
    print("centrale", main, "s of", 30 * 60, "| total", L["total_sec"], "| equipment", L["equipment_needed"])
    assert 0.9 * 1800 <= main <= 1.05 * 1800
    assert all(v <= 40 for v in L["equipment_needed"].values())
    assert r["message"].startswith("🏋️ Lezione creata: Gambe medio") and "Parte centrale" in r["message"] and "Attrezzi da preparare" in r["message"]
    # a change asked in the chat: the same lesson rebuilt with the request + the change, star kept
    await server.update_lesson_template(L["id"], {"favorite": True}, me)
    n_before = len(await server.list_lesson_templates(me))
    r2 = await server._generate_lesson(me, "fallo per 15 persone", replace_id=L["id"])
    L2 = r2["lesson"]
    assert r2["replaced"] and L2["id"] == L["id"] and L2["favorite"] and L2["participants"] == 15 and L2["created_at"] == L["created_at"]
    assert "Modifiche richieste: fallo per 15 persone" in L2["request"] and "Partecipanti: 15" in CALLS[-1][1]
    assert len(await server.list_lesson_templates(me)) == n_before and r2["message"].startswith("🏋️ Lezione modificata")
    L = L2
    # changed by hand: blocks kept in their limits, totals recomputed
    b0 = dict(L["blocks"][1]); b0["sets"] = 99
    ed = await server.update_lesson_template(L["id"], {"name": "Mia", "blocks": [L["blocks"][0], b0, {"exercise_id": "nope"}, L["blocks"][-1]]}, me)
    assert ed["name"] == "Mia" and len(ed["blocks"]) == 3 and ed["blocks"][1]["sets"] <= by[b0["exercise_id"]]["timed"]["max_sets"]
    assert ed["total_sec"] == sum(fx.block_seconds(b, ed["rest_sec"]) for b in ed["blocks"]) < L["total_sec"]
    # 25 people: the two-dumbbell exercises can't be done by all, they are left out and said
    async def read25(system, prompt, current, model, feature="creazione_lezioni"):
        if model == "gpt-4o-mini":
            return json.dumps({"type": "Funzionale", "participants": 25, "level": "alto", "body_parts": ["gambe"]})
        return json.dumps(plan(system))
    server._lesson_llm = read25
    L = (await server._generate_lesson(me, "funzionale per 25 persone livello alto gambe"))["lesson"]
    assert "Squat con due manubri" in L["excluded_equipment"] and all(b["equipment_per_person"] * 25 <= 40 for b in L["blocks"] if b["equipment"] == "manubrio")
    # the model failing: built from the rules alone
    async def broken(system, prompt, current, model, feature="creazione_lezioni"):
        raise RuntimeError("down")
    server._lesson_llm = broken
    L = (await server._generate_lesson(me, "lezione per 8 persone, 30 minuti, braccia, livello alto"))["lesson"]
    assert L["participants"] == 8 and L["duration_min"] == 30 and L["blocks"] and all(by[b["exercise_id"]]["body_part"] == "braccia" for b in L["blocks"] if b["phase"] == "centrale")
    # no exercise possible: said clearly
    try:
        await server._generate_lesson(me, "lezione per 10 persone, schiena"); assert False
    except server.HTTPException as e:
        assert e.status_code == 400 and "schiena" in e.detail, e.detail
    # the vertical chosen in the profile prepares the base too
    other = server.User(**{**U, "user_id": "u_other", "email": "o@x.it", "business_vertical": "fitness"})
    await server._apply_vertical(other, "fitness")
    assert len(await server.db.fitness_equipment.find({"owner_key": "u_other"}).to_list(10)) == 3
    print("ALL OK")
asyncio.run(main())
