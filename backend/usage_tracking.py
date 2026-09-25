"""Centralized usage/cost tracking for LLM calls and feature usage - the "punto unico di
tracciamento" from the usage-tracking spec. Every OpenAI call and every feature invocation
in the app (web + Telegram + scheduled jobs) is recorded here.

Design:
- `track_llm_call` / `track_stt_call` / `track_feature_event` are the three recording
  entry points. `LlmChat`/`OpenAISpeechToText` (llm_integrations.py) call the first two
  automatically when constructed with tracking kwargs; call sites that bypass those
  wrappers (news_service.py, vet_reports.py, list_updates.py - they build their own
  openai.AsyncOpenAI() client) call `track_llm_call` directly right after their own
  `chat.completions.create(...)`.
- Every entry point is best-effort: it NEVER raises and NEVER blocks the caller more than
  a DB write already would. `fire_and_forget_*` schedules the write as a background task
  (via asyncio.create_task) so a slow/failed write can never add latency to - or break -
  the user-facing request, per the spec's "il tracciamento non deve mai rompere la
  richiesta dell'utente".
- No content (prompts/answers) is ever recorded - only metadata (tokens, cost, feature).

Pricing lives in the `llm_pricing` collection (seeded by scripts/seed_llm_pricing.py), not
in code, so a price change never rewrites history: cost is computed once, at write time,
from whatever pricing row is valid on that day, and stored on the row.
"""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ============ Catalogo funzionalità (estendibile aggiungendo una voce qui) ============
FEATURES = {
    "ricerca_informazioni":     {"label": "Ricerca di informazioni",              "category": "generale"},
    "caricamento_informazioni": {"label": "Caricamento di informazioni",          "category": "generale"},
    "creazione_task":           {"label": "Creazione task",                       "category": "generale"},
    "creazione_todo":           {"label": "Creazione to-do",                      "category": "generale"},
    "diario":                   {"label": "Scrittura diario",                     "category": "generale"},
    "invio_news":                {"label": "News personalizzate sugli interessi",  "category": "generale"},
    "creazione_report":         {"label": "Creazione report",                     "category": "verticale"},
    "creazione_lezioni":        {"label": "Creazione lezioni",                    "category": "verticale"},
    # Non nel catalogo originale della specifica: il motore "Modifica liste" non aveva una
    # voce dedicata. Aggiunta qui (unico punto da toccare per estendere il catalogo).
    "gestione_liste":           {"label": "Gestione liste",                       "category": "generale"},
    "azioni_programmate":       {"label": "Azioni programmate",                   "category": "generale"},
    "altro":                    {"label": "Non classificato",                     "category": "sistema"},
}
VALID_FEATURES = set(FEATURES)
VALID_CHANNELS = {"web", "telegram", "sistema"}
VALID_TRIGGERS = {"utente", "automatico"}

_db = None  # impostato da server.py all'avvio via init(db)


def init(db):
    """Chiamata una volta all'avvio dell'app (server.py) per dare a questo modulo accesso
    al database, senza che ogni chiamante debba passare `db` esplicitamente."""
    global _db
    _db = db


def _norm_feature(feature: Optional[str]) -> str:
    return feature if feature in VALID_FEATURES else "altro"


def _norm_channel(channel: Optional[str]) -> str:
    return channel if channel in VALID_CHANNELS else "sistema"


def _norm_trigger(trigger: Optional[str]) -> str:
    return trigger if trigger in VALID_TRIGGERS else "automatico"


# ============ Pricing (cache leggera in-process, 60s) ============
_pricing_cache = {"at": 0.0, "rows": []}
_PRICING_CACHE_TTL_S = 60


async def _pricing_rows():
    now = time.monotonic()
    if now - _pricing_cache["at"] > _PRICING_CACHE_TTL_S:
        _pricing_cache["rows"] = await _db.llm_pricing.find({}, {"_id": 0}).to_list(500)
        _pricing_cache["at"] = now
    return _pricing_cache["rows"]


async def _pricing_for_model(model: Optional[str]) -> Optional[dict]:
    if not model or _db is None:
        return None
    rows = await _pricing_rows()
    today = datetime.now(timezone.utc).date().isoformat()

    def _active(r):
        return r.get("valid_from", "") <= today and (not r.get("valid_to") or r["valid_to"] >= today)

    active = [r for r in rows if _active(r)]
    exact = [r for r in active if r.get("model") == model]
    if exact:
        return exact[0]
    # fallback: prefix match (a pricing row's `model` may be a family prefix, e.g. "gpt-4o"
    # matching a dated snapshot name like "gpt-4o-2024-08-06" the API sometimes echoes back)
    prefix = [r for r in active if model.startswith(r.get("model", "\0"))]
    return prefix[0] if prefix else None


def _compute_token_cost(pricing: dict, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> Optional[float]:
    if pricing.get("input_per_1m_usd") is None or pricing.get("output_per_1m_usd") is None:
        return None
    non_cached = max(0, (input_tokens or 0) - (cached_input_tokens or 0))
    cached_price = pricing.get("cached_input_per_1m_usd")
    cached_cost = (cached_input_tokens or 0) * cached_price if cached_price is not None else (cached_input_tokens or 0) * pricing["input_per_1m_usd"]
    cost = non_cached * pricing["input_per_1m_usd"] + cached_cost + (output_tokens or 0) * pricing["output_per_1m_usd"]
    return round(cost / 1_000_000, 6)


def _compute_minute_cost(pricing: dict, duration_seconds: Optional[float]) -> Optional[float]:
    if duration_seconds is None or pricing.get("per_minute_usd") is None:
        return None
    return round((duration_seconds / 60.0) * pricing["per_minute_usd"], 6)


# ============ llm_calls ============
async def track_llm_call(
    *, user_id: Optional[str], feature: Optional[str], channel: Optional[str], trigger: Optional[str],
    model: Optional[str], endpoint: str,
    input_tokens: int = 0, cached_input_tokens: int = 0, output_tokens: int = 0,
    status: str = "ok", request_id: Optional[str] = None, latency_ms: Optional[int] = None,
    org_id: Optional[str] = None, feature_event_id: Optional[str] = None,
):
    """Records one row in `llm_calls`. A user_id-less call (system/background job with no
    owning user) is recorded with user_id=None, per spec ("per job di sistema senza utente
    usare null e contarli a parte")."""
    if _db is None:
        return
    try:
        pricing = await _pricing_for_model(model)
        cost = _compute_token_cost(pricing, input_tokens, cached_input_tokens, output_tokens) if pricing else None
        if model and not pricing:
            logger.warning(f"[usage] nessun prezzo configurato per il modello {model!r} - cost_usd sarà null")
        await _db.llm_calls.insert_one({
            "id": f"llmc_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "org_id": org_id,
            "feature": _norm_feature(feature),
            "channel": _norm_channel(channel),
            "trigger": _norm_trigger(trigger),
            "model": model,
            "endpoint": endpoint,
            "input_tokens": input_tokens or 0,
            "cached_input_tokens": cached_input_tokens or 0,
            "output_tokens": output_tokens or 0,
            "total_tokens": (input_tokens or 0) + (output_tokens or 0),
            "cost_usd": cost,
            "pricing_version": pricing.get("id") if pricing else None,
            "latency_ms": latency_ms,
            "status": status if status in ("ok", "errore") else "ok",
            "request_id": request_id,
            "feature_event_id": feature_event_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        logger.exception("track_llm_call fallita (solo tracciamento, la richiesta dell'utente non è stata toccata)")


async def track_stt_call(
    *, user_id: Optional[str], feature: Optional[str], channel: Optional[str], trigger: Optional[str],
    model: Optional[str], duration_seconds: Optional[float] = None,
    status: str = "ok", latency_ms: Optional[int] = None, org_id: Optional[str] = None,
):
    """Whisper (audio.transcriptions) bills per minute, not per token - stessa tabella
    llm_calls (endpoint='audio.transcriptions'), ma il costo si calcola dalla durata invece
    che dai token, con una riga dedicata in llm_pricing (campo per_minute_usd)."""
    if _db is None:
        return
    try:
        pricing = await _pricing_for_model(model)
        cost = _compute_minute_cost(pricing, duration_seconds) if pricing else None
        if model and not pricing:
            logger.warning(f"[usage] nessun prezzo configurato per il modello {model!r} - cost_usd sarà null")
        await _db.llm_calls.insert_one({
            "id": f"llmc_{uuid.uuid4().hex[:12]}",
            "user_id": user_id,
            "org_id": org_id,
            "feature": _norm_feature(feature),
            "channel": _norm_channel(channel),
            "trigger": _norm_trigger(trigger),
            "model": model,
            "endpoint": "audio.transcriptions",
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": cost,
            "pricing_version": pricing.get("id") if pricing else None,
            "latency_ms": latency_ms,
            "status": status if status in ("ok", "errore") else "ok",
            "request_id": None,
            "feature_event_id": None,
            "duration_seconds": duration_seconds,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:
        logger.exception("track_stt_call fallita (solo tracciamento, la richiesta dell'utente non è stata toccata)")


# ============ feature_events ============
async def track_feature_event(
    *, user_id: Optional[str], feature: Optional[str], channel: Optional[str], trigger: Optional[str],
    org_id: Optional[str] = None,
) -> Optional[str]:
    """Records one row in `feature_events` - one per feature USE, regardless of how many
    (zero, one, or many) LLM calls it triggers. Returns the new event's id so callers can
    link their llm_calls rows to it via `feature_event_id`, or None on failure."""
    if _db is None or not user_id:
        return None
    try:
        event_id = f"fev_{uuid.uuid4().hex[:12]}"
        await _db.feature_events.insert_one({
            "id": event_id,
            "user_id": user_id,
            "org_id": org_id,
            "feature": _norm_feature(feature),
            "channel": _norm_channel(channel),
            "trigger": _norm_trigger(trigger),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        return event_id
    except Exception:
        logger.exception("track_feature_event fallita (solo tracciamento, la richiesta dell'utente non è stata toccata)")
        return None


def fire_and_forget_llm_call(**kwargs):
    """Schedula track_llm_call senza attenderla, così la scrittura non aggiunge mai
    latenza alla risposta del chiamante. Ogni errore è già gestito dentro track_llm_call."""
    try:
        asyncio.create_task(track_llm_call(**kwargs))
    except Exception:
        logger.exception("impossibile schedulare track_llm_call")


def fire_and_forget_stt_call(**kwargs):
    try:
        asyncio.create_task(track_stt_call(**kwargs))
    except Exception:
        logger.exception("impossibile schedulare track_stt_call")


def fire_and_forget_feature_event(**kwargs):
    try:
        asyncio.create_task(track_feature_event(**kwargs))
    except Exception:
        logger.exception("impossibile schedulare track_feature_event")
