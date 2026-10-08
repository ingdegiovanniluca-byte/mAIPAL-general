import asyncio, os, sys, json
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import agent_guard as ag, usage_tracking as ut
ut.fire_and_forget_llm_call = lambda **k: None

# gate 1: (text, chosen, expected looks_misplaced)
cases = [
    ("salva che il codice del wifi è 1234", "info_request", True),
    ("ricordami di chiamare Marco domani alle 10", "info_request", True),
    ("aggiungi il latte alla lista della spesa", "info_request", True),
    ("quando scade la patente?", "info_request", False),
    ("cosa devo fare domani", "info_request", False),
    ("quando scade la patente?", "info_upload", True),
    ("il codice del wifi è 1234", "info_upload", False),
    ("Marco è allergico alle noci", "info_upload", False),
    ("aggiungi il latte alla lista della spesa", "info_upload", False),
    ("ricordami di comprare il latte", "info_upload", True),
    ("chiamare il commercialista lunedì", "task_todo", False),
    ("ricordami di chiamare Marco domani", "task_todo", False),
    ("quali task ho domani?", "task_todo", True),
    ("segna come fatto il task palestra", "task_todo", False),
    ("oggi è stata una giornata pesante", "journal", False),
    ("mi sento stanco ma contento", "journal", False),
    ("cosa ho scritto nel diario ieri?", "journal", True),
    ("ok", "info_request", False),
    # a spending told to Cerca, which only reads: for Salva
    ("oggi ho speso 50 euro di benzina", "info_request", True),
    ("registra una spesa di oggi sulla benzina", "info_request", True),
    ("pagato il meccanico 120 €", "info_request", True),
    ("quanto ho speso a ottobre?", "info_request", False),
    ("dammi il totale delle spese di ottobre", "info_request", False),
]
bad = [(t, c, e) for t, c, e in cases if ag.looks_misplaced(t, c) != e]
for b in bad: print("GATE WRONG:", b)
assert not bad

class Msg:
    def __init__(s, c): s.message = type("M", (), {"content": c})()
class Resp:
    def __init__(s, c): s.choices = [Msg(c)]; s.usage = None; s.model = "gpt-4o-mini"
calls = []
def fake_client(reply):
    class C:
        def __init__(s, api_key=None):
            s.chat = type("X", (), {})(); s.chat.completions = type("Y", (), {})()
            async def create(**k):
                calls.append(k)
                if isinstance(reply, Exception): raise reply
                return Resp(reply)
            s.chat.completions.create = create
    return C

async def main():
    ag.openai.AsyncOpenAI = fake_client(json.dumps({"agent": "info_upload", "certain": True, "reason": "Vuoi salvare un'informazione."}))
    r = await ag.check("salva che il codice del wifi è 1234", "info_request")
    print(r); assert r == {"agent": "info_upload", "label": "Salva", "reason": "Vuoi salvare un'informazione."}
    n = len(calls)
    assert await ag.check("quando scade la patente?", "info_request") is None and len(calls) == n, "no model call when gate is closed"
    ag.openai.AsyncOpenAI = fake_client(json.dumps({"agent": "info_upload", "certain": False}))
    assert await ag.check("salva che il codice del wifi è 1234", "info_request") is None
    ag.openai.AsyncOpenAI = fake_client(json.dumps({"agent": "info_request", "certain": True}))
    assert await ag.check("salva che il codice del wifi è 1234", "info_request") is None   # same agent
    ag.openai.AsyncOpenAI = fake_client(RuntimeError("down"))
    assert await ag.check("salva che il codice del wifi è 1234", "info_request") is None
    ag.openai.AsyncOpenAI = fake_client("non so")
    assert await ag.check("salva che il codice del wifi è 1234", "info_request") is None
    import list_updates as lu
    assert lu.looks_like_note("registra questa spesa di 30 euro al supermercato") and not lu.looks_like_note("registra il latte nella lista della spesa")
    print("ALL OK")
asyncio.run(main())
