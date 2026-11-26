"""Tenant isolation probe (organizations must never see each other's data), against a real MongoDB - a THROWAWAY
database: it is wiped at every route. Run from backend/:
    MONGO_URL=mongodb://localhost:27017 DB_NAME=isolation_probe python scripts/isolation_probe.py [route-substring]
Exit code 1 when a leak is found. (tests/test_tenant_isolation.py runs it when ISOLATION_MONGO_URL is set.)

Tenant isolation probe against a real MongoDB. Organization A has data everywhere (every text carries ALFAX); the
administrator of organization B calls EVERY endpoint of the API with A's ids (path and body). A response with A's
data, or A's data changed/deleted, or a new document tied to A's ids = a leak. Each route is also called by A itself
(on a fresh copy of the data) to know whether the probe reached its logic.
Run: MONGO_URL=... DB_NAME=iso probe.py [route-substring]"""
import asyncio, base64, copy, json, os, re, sys, types, typing
from datetime import datetime, timedelta, timezone
BACKEND = os.environ.get("PROBE_BACKEND", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if "probe" not in (os.environ.get("DB_NAME") or "") and "isolation" not in (os.environ.get("DB_NAME") or ""):
    sys.exit("DB_NAME must be a throwaway database whose name contains 'probe' or 'isolation': it is wiped")
sys.path.insert(0, BACKEND)
os.chdir(BACKEND)
os.environ.setdefault("OPENAI_API_KEY", "x")
import server, telegram_bot as tg
import file_store as _fs
server.fstore.store = _fs.MemoryStore()            # (A's file on its QR: its bytes carry the marker)
server.fstore.store.files["fA"] = (b"%PDF-1.4 ALFAX", "doc.pdf", {"qr_id": "qrA"})
import httpx
from fastapi.routing import APIRoute
import llm_integrations as li

MARK = "ALFAX"
ONLY = sys.argv[1] if len(sys.argv) > 1 else ""

# ---------- nothing leaves: the AI echoes what it was given (so A's data reaching B's prompt shows up), no network
class EchoChat:
    def __init__(self, *a, **k): self.sys = k.get("system_message", "") or ""
    def with_model(self, *a, **k): return self
    async def stream_message(self, msg):
        yield li.TextDelta(content=f"ECO: {self.sys[-3000:]} || {getattr(msg, 'text', '')[-3000:]}")
        yield li.StreamDone()
    async def send_message(self, msg):
        return f"ECO: {self.sys[-3000:]} || {getattr(msg, 'text', '')[-3000:]}"
server.LlmChat = EchoChat
class FakeCompletions:
    async def create(self, **k):
        txt = " ".join(str(m.get("content", ""))[-4000:] for m in k.get("messages", []))
        msg = types.SimpleNamespace(content=json.dumps({"answer": "ECO " + txt, "text": "ECO " + txt}))
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=None, model="fake", id="x")
class FakeOpenAI:
    def __init__(self, *a, **k):
        self.chat = types.SimpleNamespace(completions=FakeCompletions())
        self.audio = types.SimpleNamespace(transcriptions=types.SimpleNamespace(create=self._tr))
        self.embeddings = types.SimpleNamespace(create=self._emb)
    async def _tr(self, **k): return types.SimpleNamespace(text="ciao")
    async def _emb(self, **k): return types.SimpleNamespace(data=[types.SimpleNamespace(embedding=[0.0] * 384)])
import openai
openai.AsyncOpenAI = FakeOpenAI
async def _no_net(self, *a, **k): raise httpx.ConnectError("probe: no network")
_real_send = httpx.AsyncClient.send
async def _send(self, request, *a, **k):
    if request.url.host in ("probe",):   # the probe's own calls to the app
        return await _real_send(self, request, *a, **k)
    raise httpx.ConnectError("probe: no network")
httpx.AsyncClient.send = _send
tg.bot_token = lambda: ""
async def no_emb(q): return [0.0] * 384
import embeddings as emb
emb.embed_query = no_emb
async def no_embs(ts): return [[0.0] * 384 for _ in ts]
emb.embed_texts = no_embs

db = server.db
NOW = datetime.now(timezone.utc)
iso = lambda d: d.isoformat()
PNG = "data:image/png;base64," + base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")).decode()

# ---------- the two organizations
A = {"tenant": "ten_A", "org": "org_A", "admin": "uA0", "user": "uA1"}
B = {"tenant": "ten_B", "org": "org_B", "admin": "uB0"}
import verticals as vx
fields, fmap = vx.merge_system_fields([], vx.CLIENTI_FIELDS)
subs_f, smap = vx.merge_system_fields([], vx.COMMESSA_FIELDS)
IDS = dict(qr_id="qrA", code="QRAAAAAAAAAA", file_id="fA", commessa_id="sA", collection_id="cA", item_id="iA", sub_id="sA", log_id="lA", photo_id="phA", activity_id="actA",
           quote_id="qA", ms_id="msA", collab_id="colA", report_id="wrA", entry_id="jA", conv_id="convA", action_id="saA",
           tpl_id="mtA", template_id="wtA", step_id="stA", link_id="lnkA", lesson_id="lsA", exercise_id="exA", eq_id="eqA",
           type_id="ltA", draft_id="rdr_aaaaaaaaaaaa", doc_id="docA", contact_id="ctA", client_id="clA", xid="xA", extra_id="xA",
           device_id="devA", org_id="org_A", team_id="org_A", user_id="uA1", member_user_id="uA1", email="invitato.alfax@ex.it",
           kind="diary", index="0", idx="0", section_id="liste", todo_id="tdA", task_id="tA", commessa="sA", item="iA",
           series_id="serA", report_draft_id="rdr_aaaaaaaaaaaa", client_item_id="iA", hint_commessa_id="sA", list_id="cA",
           report_list_id="cA", target_collection_id="cA", attachment_doc_ids=["docA"], doc_ids=["docA"], extra_ids=["xA"],
           log_ids=["lA"], todo_ids=["jtA"], ids=["stA"])
A_IDS = {"qrA", "qrvA", "fA", "sA", "sA2", "cA", "cA2", "iA", "iA2", "lA", "phA", "actA", "aitA", "qA", "msA", "colA", "wrA", "jA", "convA", "saA", "mtA", "wtA",
         "vtA", "stA", "lnkA", "lsA", "exA", "eqA", "ltA", "rdr_aaaaaaaaaaaa", "docA", "ctA", "clA", "xA", "devA", "org_A", "ten_A",
         "uA0", "uA1", "tdA", "tA", "jtA", "serA", "chA", "nA", "waitA", "linkA", "rphA", "arcA"}


def seed_docs():
    a0, a1, b0 = A["admin"], A["user"], B["admin"]
    D = {
        "tenants": [{"id": "ten_A", "name": f"Impresa {MARK}", "plan": {}}, {"id": "ten_B", "name": "Impresa Bravo"}],
        "organizations": [{"id": "org_A", "name": f"Squadra {MARK}", "tenant_id": "ten_A", "owner_user_id": a0, "code": "CODEA1"},
                          {"id": "org_B", "name": "Squadra Bravo", "tenant_id": "ten_B", "owner_user_id": b0, "code": "CODEB1"}],
        "users": [
            {"user_id": a0, "email": "a0@alfa.it", "name": f"Anna {MARK}", "role": "admin", "org_id": "org_A", "org_ids": ["org_A"], "tenant_id": "ten_A",
             "business_vertical": "artigiano", "onboarded": True, "telegram_chat_id": 111, "home_address": f"Via {MARK} 1", "created_at": iso(NOW)},
            {"user_id": a1, "email": "a1@alfa.it", "name": f"Aldo {MARK}", "role": "user", "org_id": "org_A", "org_ids": ["org_A"], "tenant_id": "ten_A",
             "business_vertical": "artigiano", "onboarded": True, "created_at": iso(NOW)},
            {"user_id": b0, "email": "b0@bravo.it", "name": "Bruno Bravo", "role": "admin", "org_id": "org_B", "org_ids": ["org_B"], "tenant_id": "ten_B",
             "business_vertical": "artigiano", "onboarded": True, "created_at": iso(NOW)}],
        "user_sessions": [{"session_token": "tokA", "user_id": a0, "expires_at": iso(NOW + timedelta(days=5))},
                          {"session_token": "tokB", "user_id": b0, "expires_at": iso(NOW + timedelta(days=5))}],
        "collections": [
            {"id": "cA", "name": "Clienti", "fields": fields, "sub_item_fields": subs_f, "system_key": vx.CLIENTI_KEY, "system_map": fmap,
             "system_sub_map": smap, "visibility": "org", "org_id": "org_A", "user_id": a0, "tenant_id": "ten_A", "created_at": iso(NOW)},
            {"id": "cA2", "name": f"Spese {MARK}", "fields": [{"key": "voce", "label": "Voce"}], "sub_item_fields": [{"key": "n", "label": "N"}],
             "visibility": "private", "user_id": a0, "created_at": iso(NOW)},
            {"id": "cB", "name": "Clienti", "fields": fields, "sub_item_fields": subs_f, "system_key": vx.CLIENTI_KEY, "system_map": fmap,
             "system_sub_map": smap, "visibility": "org", "org_id": "org_B", "user_id": b0, "tenant_id": "ten_B", "created_at": iso(NOW)}],
        "collection_items": [
            {"id": "iA", "collection_id": "cA", "user_id": a0, "org_id": "org_A", "visibility": "org",
             "data": {fmap.get("nome", "nome"): f"Cliente {MARK}", fmap.get("telefono", "telefono"): "333 999 ALFAX"}, "created_at": iso(NOW)},
            {"id": "iA2", "collection_id": "cA2", "user_id": a0, "data": {"voce": f"Spesa {MARK}"}, "created_at": iso(NOW)},
            {"id": "iB", "collection_id": "cB", "user_id": b0, "org_id": "org_B", "visibility": "org", "data": {fmap.get("nome", "nome"): "Cliente Bravo"}}],
        "collection_sub_items": [
            {"id": "sA", "collection_id": "cA", "item_id": "iA", "user_id": a0, "org_id": "org_A",
             "data": {smap.get("titolo", "titolo"): f"Commessa {MARK}", smap.get("stato", "stato"): "in lavorazione", smap.get("codice", "codice"): "2026-001",
                      smap.get("descrizione", "descrizione"): f"Descrizione {MARK}"},
             "links": [{"id": "lnkA", "url": "https://alfax.example/doc", "title": f"Link {MARK}", "by": "Anna"}],
             "client_updates": {"enabled": True}, "created_at": iso(NOW)},
            {"id": "sA2", "collection_id": "cA2", "item_id": "iA2", "user_id": a0, "data": {"n": f"sotto {MARK}"}},
            {"id": "sB", "collection_id": "cB", "item_id": "iB", "user_id": b0, "org_id": "org_B",
             "data": {smap.get("titolo", "titolo"): "Commessa Bravo", smap.get("stato", "stato"): "in lavorazione", smap.get("codice", "codice"): "2026-001"}}],
        "job_logs": [{"id": "lA", "commessa_id": "sA", "org_id": "org_A", "user_id": a0, "author_user_id": a0, "author_name": "Anna",
                      "date": NOW.date().isoformat(), "created_at": iso(NOW), "text": f"Nota {MARK}", "raw_text": f"nota {MARK}",
                      "hours": [{"who": "Anna", "hours": 8, "pending": True}], "materials": [{"name": f"tubo {MARK}", "qty": 2, "unit": "m"}],
                      "problems": [{"text": f"problema {MARK}", "resolved": False}], "photos": [{"id": "phA"}], "embedding": None}],
        "job_photos": [{"id": "phA", "log_id": "lA", "commessa_id": "sA", "user_id": a0, "org_id": "org_A", "mime": "image/png",
                        "data_b64": PNG.split(",", 1)[1]}],
        "job_activities": [{"id": "actA", "commessa_id": "sA", "org_id": "org_A", "date": NOW.date().isoformat(), "description": f"Attività {MARK}",
                            "status": "pianificata", "assignees": [{"id": "uA1", "type": "user", "name": "Aldo"}],
                            "items": [{"id": "aitA", "category": "materiali", "text": f"cosa {MARK}"}], "created_by": a0}],
        "job_todos": [{"id": "jtA", "commessa_id": "sA", "text": f"Da fare {MARK}", "done": False, "due_date": NOW.date().isoformat(), "kind": "attivita"}],
        "job_milestones": [{"id": "msA", "commessa_id": "sA", "collection_id": "cA", "title": f"Tappa {MARK}", "done": False}],
        "job_contacts": [{"id": "ctA", "commessa_id": "sA", "collection_id": "cA", "name": f"Contatto {MARK}", "role": "idraulico"}],
        "job_quotes": [{"id": "qA", "commessa_id": "sA", "status": "confirmed", "version": 1, "data": {"activities": [f"posa {MARK}"], "total": 1000},
                        "confirmed_at": iso(NOW), "created_at": iso(NOW), "data_b64": base64.b64encode(MARK.encode()).decode()}],
        "job_extra_works": [{"id": "xA", "commessa_id": "sA", "work": f"Extra {MARK}", "status": "extra", "amount": 100}],
        "job_waits": [{"id": "waitA", "commessa_id": "sA", "status": "aperta", "text": f"attesa {MARK}", "owner_user_id": a0}],
        "job_economics": [{"commessa_id": "sA", "budget": 12345, "extras": [{"id": "exA", "what": f"spesa {MARK}", "amount": 10}]}],
        "work_reports": [{"id": "wrA", "user_id": a0, "org_id": "org_A", "commessa_id": "sA", "client_item_id": "iA", "template_name": "SAL",
                          "sections": [{"title": "1. Dati", "fields": {"Cliente": f"Cliente {MARK}"}}], "summary": f"riassunto {MARK}",
                          "docx_b64": base64.b64encode(MARK.encode()).decode(), "docx_filename": "r.docx", "version": 1, "created_at": iso(NOW)}],
        "report_drafts": [{"id": "rdr_aaaaaaaaaaaa", "user_id": a0, "messages": [{"text": f"bozza {MARK}"}], "commessa_id": "sA", "status": "open"}],
        "report_photos": [{"id": "rphA", "draft_id": "rdr_aaaaaaaaaaaa", "user_id": a0, "data_b64": PNG.split(",", 1)[1], "caption": MARK}],
        "collaborators": [{"id": "colA", "name": f"Operaio {MARK}", "status": "active", "owner_user_id": a0, "tenant_id": "ten_A", "code": "COLA1",
                           "commesse": ["sA"], "telegram_chat_id": 222, "phone": "333 ALFAX"}],
        "client_links": [{"id": "linkA", "item_id": "iA", "status": "active", "telegram_chat_id": 333}],
        "milestone_templates": [{"id": "mtA", "org_id": "org_A", "tenant_id": "ten_A", "user_id": a0, "name": f"Modello {MARK}", "steps": []}],
        "work_templates": [{"id": "wtA", "user_id": a0, "org_id": "org_A", "visibility": "private", "name": f"Modello {MARK}", "sections": []}],
        "vet_templates": [{"id": "vtA", "user_id": a0, "name": f"Referto {MARK}", "sections": []}],
        "tasks": [{"id": "tA", "user_id": a0, "org_id": "org_A", "visibility": "private", "title": f"Task {MARK}", "due_date": NOW.date().isoformat(),
                   "status": "todo", "created_at": iso(NOW), "series_id": "serA"}],
        "task_series": [{"id": "serA", "user_id": a0, "title": f"Serie {MARK}", "active": True, "rule": {}}],
        "todos": [{"id": "tdA", "user_id": a0, "title": f"To do {MARK}", "status": "da_fare", "description": f"desc {MARK}", "has_cover": True,
                   "steps": [{"id": "stA", "text": f"passo {MARK}", "done": False}], "created_at": iso(NOW)}],
        "todo_covers": [{"todo_id": "tdA", "image": PNG, "user_id": a0}],
        "conversations": [{"conv_id": "convA", "user_id": a0, "action": "info_request", "created_at": iso(NOW), "user_message": f"domanda {MARK}",
                           "messages": [{"role": "user", "content": f"domanda {MARK}"}, {"role": "assistant", "content": f"risposta {MARK}"}]}],
        "journal_entries": [{"id": "jA", "user_id": a0, "date": NOW.date().isoformat(), "raw_text": f"diario {MARK}", "cleaned_text": f"diario {MARK}",
                             "images": [PNG], "created_at": iso(NOW)}],
        "news_items": [{"id": "nA", "user_id": a0, "title": f"Notizia {MARK}", "summary": MARK, "url": "https://alfax.example", "created_at": iso(NOW)}],
        "kb_documents": [{"doc_id": "docA", "user_id": a0, "org_id": "org_A", "name": f"doc {MARK}.pdf", "created_at": iso(NOW)}],
        "kb_chunks": [{"chunk_id": "chA", "doc_id": "docA", "user_id": a0, "text": f"Il preventivo segreto {MARK} vale 9999 euro", "source_name": None,
                       "embedding": [0.0] * 384, "created_at": iso(NOW)}],
        "scheduled_actions": [{"id": "saA", "user_id": a0, "title": f"Azione {MARK}", "enabled": True, "kind": "report", "schedule": {"freq": "daily", "time": "08:00"},
                               "next_run_at": iso(NOW + timedelta(days=1)), "report_instruction": MARK, "delivery": "app"}],
        "clients": [{"id": "clA", "user_id": a0, "org_id": "org_A", "visibility": "private", "name": f"Cliente fitness {MARK}"}],
        "exercises": [{"id": "exA", "owner_key": "org_A", "name": f"Esercizio {MARK}"}],
        "fitness_equipment": [{"id": "eqA", "owner_key": "org_A", "name": f"Attrezzo {MARK}", "qty": 1}],
        "lesson_types": [{"id": "ltA", "owner_key": "org_A", "name": f"Tipo {MARK}"}],
        "qr_codes": [{"id": "qrA", "code": "QRAAAAAAAAAA", "tenant_id": "ten_A", "owner_user_id": a0, "title": f"QR {MARK}", "kind": "cantiere",
                      "text": f"codice cancello {MARK}", "links": [], "commessa_id": "sA", "visibility": "org", "active": True,
                      "files": [{"id": "fA", "name": f"doc {MARK}.pdf", "kind": "pdf", "pages": 1, "size": 9}],
                      "created_at": iso(NOW), "updated_at": iso(NOW), "scans": 0}],
        "qr_code_versions": [{"id": "qrvA", "qr_id": "qrA", "tenant_id": "ten_A", "before": {"text": f"prima {MARK}"}, "edited_at": iso(NOW)}],
        "lesson_templates": [{"id": "lsA", "owner_key": "org_A", "user_id": a0, "name": f"Lezione {MARK}", "exercises": []}],
        "watch_devices": [{"device_id": "devA", "user_id": a0, "name": f"orologio {MARK}"}],
        "team_invites": [{"org_id": "org_A", "email": "invitato.alfax@ex.it", "invited_by": a0}],
        "tenant_invites": [{"tenant_id": "ten_A", "email": "invitato.alfax@ex.it", "invited_by": a0}],
        "archive_files": [{"id": "arcA", "user_id": a0, "status": "saved", "name": f"file {MARK}", "meta": {"log_id": "lA"}}],
        "notify_prefs": [{"user_id": a0, "kind": "diary", "on": True, "channel": "both"}],
    }
    return D


async def reset():
    for c in await db.list_collection_names():
        await db[c].delete_many({})
    for c, docs in seed_docs().items():
        if docs:
            await db[c].insert_many([dict(d) for d in docs])


def _norm(d):
    d = dict(d); d.pop("_id", None)
    return json.dumps(d, sort_keys=True, default=str)


async def snapshot():
    snap = {}
    for c in await db.list_collection_names():
        for d in await db[c].find({}).to_list(None):
            snap[(c, str(d.get("_id")))] = _norm(d)
    return snap


IGN = {"user_sessions", "usage_events", "router_shadow", "llm_calls", "feature_events", "usage_daily", "job_leases"}
A_RX = re.compile(r"\b(" + "|".join(sorted((re.escape(x) for x in A_IDS), key=len, reverse=True)) + r")\b")


def a_related(js: str) -> bool:
    return MARK in js or bool(A_RX.search(js))


def diff(before, after):
    """changes to A's documents, and new documents tied to A"""
    out = []
    for k, v in before.items():
        if k[0] in IGN or not a_related(v):
            continue
        if k not in after:
            out.append(f"cancellato {k[0]}")
        elif after[k] != v:
            out.append(f"modificato {k[0]}")
    for k, v in after.items():
        if k not in before and k[0] not in IGN and a_related(v):
            out.append(f"nuovo {k[0]} legato ad A")
    return sorted(set(out))


# ---------- request bodies from the route's model: required fields filled, ids = A's
def sample(schema, defs, name=""):
    if "$ref" in schema:
        return sample(defs[schema["$ref"].split("/")[-1]], defs, name)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            opts = [s for s in schema[key] if s.get("type") != "null"] or schema[key]
            return sample(opts[0], defs, name)
    if name in IDS:
        v = IDS[name]
        if schema.get("type") == "array":
            return v if isinstance(v, list) else [v]
        return v[0] if isinstance(v, list) else v
    if name.endswith("_ids") and schema.get("type") == "array":
        return ["sA"]
    t = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema and schema["default"] is not None:
        return schema["default"]
    if t == "object":
        props, req = schema.get("properties", {}), set(schema.get("required", []))
        return {k: sample(v, defs, k) for k, v in props.items() if k in req or k in IDS or k.endswith("_id")}
    if t == "array":
        return []
    if t == "integer":
        return 1
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    if name in ("text", "question", "content", "instruction", "message", "query", "q"):
        return "dimmi tutto quello che sai su clienti, commesse, preventivi, note e costi"
    if name == "email":
        return "invitato.alfax@ex.it"
    if "date" in name:
        return NOW.date().isoformat()
    if "time" in name or name.endswith("_at"):
        return "10:00"
    if name == "url":
        return "https://example.org"
    if name in ("image", "data_uri", "photo"):
        return PNG
    return "x"


def body_for(route: APIRoute):
    bp = route.dependant.body_params
    if not bp:
        return None
    if len(bp) == 1 and getattr(bp[0].field_info, "embed", None) is not True:
        f = bp[0]
        ann = f.field_info.annotation if hasattr(f, "field_info") else f.type_
        try:
            sch = ann.model_json_schema()
        except Exception:
            return {}
        return sample(sch, sch.get("$defs", {}), "")
    return {}


def path_for(path: str):
    def sub(m):
        n = m.group(1)
        if n == "todo_id" and path.startswith("/jobs/"):
            return "jtA"
        if n == "item_id" and path.startswith("/jobs/activities"):
            return "aitA"
        if n == "item_id" and path.startswith("/news"):
            return "nA"
        if n == "template_id" and path.startswith("/vet"):
            return "vtA"
        if n == "extra_id":
            return "exA"
        return str(IDS.get(n, "x"))
    return re.sub(r"{(\w+)}", sub, path)


SKIP = {"/auth/logout", "/auth/google/callback", "/integrations/google/callback", "/integrations/microsoft/callback"}


async def call(client, token, method, url, body):
    try:
        r = await client.request(method, "/api" + url, json=body, cookies={"session_token": token}, timeout=60)
        txt = r.text
        return r.status_code, txt
    except Exception as e:
        return 0, f"EXC {type(e).__name__}: {e}"


async def main():
    transport = httpx.ASGITransport(app=server.app)
    client = httpx.AsyncClient(transport=transport, base_url="http://probe")
    routes = [r for r in server.app.routes if isinstance(r, APIRoute) and r.path.startswith("/api")]
    results = []
    for r in routes:
        path = r.path[4:]
        if path in SKIP or (ONLY and ONLY not in path):
            continue
        for method in sorted(r.methods - {"HEAD", "OPTIONS"}):
            url, body = path_for(path), body_for(r)
            # B, the other organization
            await reset()
            before = await snapshot()
            st_b, txt_b = await call(client, "tokB", method, url, body)
            after = await snapshot()
            changes = diff(before, after)
            read_leak = 200 <= st_b < 300 and MARK in txt_b
            # A itself (control: does the call reach the logic?)
            await reset()
            st_a, txt_a = await call(client, "tokA", method, url, body)
            results.append({"m": method, "p": path, "url": url, "b": st_b, "a": st_a, "read": read_leak, "write": changes,
                            "snip": (txt_b[max(0, txt_b.find(MARK) - 120): txt_b.find(MARK) + 60] if read_leak else txt_b[:120])})
    leaks = [x for x in results if x["read"] or x["write"]]
    unreached = [x for x in results if not (200 <= x["a"] < 300) and not (x["read"] or x["write"])]
    print(f"ROUTES PROBED: {len(results)}  LEAKS: {len(leaks)}  NOT REACHED BY A EITHER: {len(unreached)}")
    if os.environ.get("PROBE_DUMP"):   # every answer's status, to compare two runs (e.g. with / without the search index)
        with open(os.environ["PROBE_DUMP"], "w") as f:
            json.dump([{k: x[k] for k in ("m", "p", "a", "b")} for x in results], f, indent=0)
    for x in leaks:
        kind = ("LETTURA " if x["read"] else "") + ("SCRITTURA " + ", ".join(x["write"]) if x["write"] else "")
        print(f"LEAK {x['m']:6s} {x['p']:60s} B={x['b']} A={x['a']} {kind}\n      {x['snip'][:200]!r}")
    if os.environ.get("PROBE_OUT"):
        json.dump(results, open(os.environ["PROBE_OUT"], "w"), indent=1)
    return len(leaks)

if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
