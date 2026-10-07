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
import help_guide as hg, agent_guard as ag
U["business_vertical"] = "artigiano"
prompts = []
class FakeChat:
    def __init__(self, *a, **k): self.sys = k.get("system_message", ""); self.feature = k.get("feature")
    def with_model(self, *a): return self
    async def stream_message(self, msg):
        prompts.append({"system": self.sys, "text": msg.text, "feature": self.feature})
        yield TextDelta(content="Risposta.")
        yield StreamDone()
    async def send_message(self, msg): return '{"topics": {}}'
server.LlmChat = FakeChat
kb_calls = []
async def fake_kb(*a, **k):
    kb_calls.append(a); return []
server.retrieve_kb = fake_kb
confirm = {"answer": True}
async def fake_about(text, user_id=None):
    gate = hg.looks_about_app(text)
    return gate == "sure" or (gate == "maybe" and confirm["answer"])
server.help_guide.is_about_app = fake_about

async def run(payload):
    resp = await server.chat_stream(payload, server.User(**U))
    out = []
    async for chunk in resp.body_iterator:
        for line in (chunk.decode() if isinstance(chunk, bytes) else chunk).splitlines():
            if line.strip(): out.append(J.loads(line))
    return out

async def main():
    me = server.User(**U)
    # 1) the guide: sections per vertical and per page
    ids = [s.id for s in hg.sections_for("artigiano")]
    assert "diario-commessa" in ids and "diario" not in ids and "referto" not in ids and "fitness" not in ids
    assert "referto" in [s.id for s in hg.sections_for(None)] and "diario" in [s.id for s in hg.sections_for("veterinario")]
    r = await server.help_sections("/dashboard/liste", me)
    assert [s["id"] for s in r["sections"]] == ["liste", "clienti-commesse"] and r["sections"][0]["body"]
    r = await server.help_sections("/dashboard/journal", me)
    assert [s["id"] for s in r["sections"]] == ["diario-commessa"]
    assert (await server.help_section("telegram", me))["title"] == "Telegram"
    try:
        await server.help_section("fitness", me); assert False   # not for an artigiano
    except server.HTTPException as e:
        assert e.status_code == 404
    # 2) gate 1
    for t, want in [("cosa sai fare?", "sure"), ("aiuto", "sure"), ("come collego telegram a maipal?", "sure"),
                    ("come creo una lista?", "maybe"), ("dove cambio il tema scuro?", "maybe"),
                    ("cosa c'è nella lista della spesa?", None), ("come funziona il contratto di Rossi?", None),
                    ("mi serve aiuto con il preventivo", None), ("come faccio la carbonara?", None),
                    ("quando devo chiamare il fornitore?", None)]:
        assert hg.looks_about_app(t) == want, (t, hg.looks_about_app(t))
    # 3) the chat in Help mode: the guide, no personal data, marked as Help
    ev = await run(server.ChatRequest(action="help", content="come creo una nuova commessa?", page="/dashboard/liste"))
    assert ev[0] == {"type": "help"} and ev[-1]["type"] == "done"
    p = prompts[-1]
    assert "Sei Help" in p["system"] and "GUIDA DI mAIPAL" in p["text"] and "## Clienti e commesse" in p["text"] and "/dashboard/liste" in p["text"]
    assert "## Diario\n" not in p["text"] and p["feature"] == "help" and not kb_calls
    conv = db.conversations.docs[-1]
    assert conv["action"] == "help" and conv["messages"][-1].get("help") is True
    # a follow-up in the same Help chat stays Help
    ev = await run(server.ChatRequest(action="info_request", content="e come la elimino?", conv_id=conv["conv_id"]))
    assert ev[0] == {"type": "help"} and "Sei Help" in prompts[-1]["system"]
    # 4) Cerca: a question about the app is answered by Help...
    ev = await run(server.ChatRequest(action="info_request", content="come posso collegare l'orologio?"))
    assert ev[0] == {"type": "help"} and "Sei Help" in prompts[-1]["system"] and not kb_calls
    assert db.conversations.docs[-1]["action"] == "info_request"
    # ...a question on the user's data is not
    ev = await run(server.ChatRequest(action="info_request", content="cosa c'è nella lista della spesa?"))
    assert all(e["type"] != "help" for e in ev) and "Sei Help" not in prompts[-1]["system"] and len(kb_calls) == 1
    # ...and a how-to the model is not sure about stays with Cerca
    confirm["answer"] = False
    ev = await run(server.ChatRequest(action="info_request", content="come faccio a trovare il numero di Mario nella lista clienti?"))
    assert all(e["type"] != "help" for e in ev) and len(kb_calls) == 2
    # 5) gate 2 with the model: only a certain yes
    class Msg:
        def __init__(s, c): s.message = type("M", (), {"content": c})()
    def client(reply):
        class C:
            def __init__(s, api_key=None):
                s.chat = type("X", (), {})(); s.chat.completions = type("Y", (), {})()
                async def create(**k):
                    if isinstance(reply, Exception): raise reply
                    return type("R", (), {"choices": [Msg(reply)], "usage": None, "model": "m"})()
                s.chat.completions.create = create
        return C
    import importlib
    real = importlib.reload(hg)   # the module's own is_about_app (patched above on server's reference)
    real.openai.AsyncOpenAI = client('{"help": true, "certain": true}')
    assert await real.is_about_app("come creo una lista?") is True
    real.openai.AsyncOpenAI = client('{"help": true, "certain": false}')
    assert await real.is_about_app("come creo una lista?") is False
    real.openai.AsyncOpenAI = client(RuntimeError("down"))
    assert await real.is_about_app("come creo una lista?") is False
    assert await real.is_about_app("cosa sai fare?") is True          # sure: no model needed
    assert await real.is_about_app("quanto ho speso a settembre?") is False
    # 6) the wrong-agent check leaves Help's questions alone
    assert not ag.looks_misplaced("come aggiungo un elemento alla lista?", "info_request")
    assert ag.looks_misplaced("aggiungi il latte alla lista della spesa", "info_request")
    print("ALL OK")
asyncio.run(main())
