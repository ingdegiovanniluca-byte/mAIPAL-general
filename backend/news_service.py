"""Generates a personalized daily news digest for a user via OpenAI's web search tool,
based on their profession/sector/verticals/interests (already collected at onboarding)."""
import json
import logging
import os
import re
from datetime import datetime, timezone

import openai

import usage_tracking as ut

logger = logging.getLogger(__name__)

MODEL = "gpt-4o"


def _track(resp, user_id, status: str = "ok"):
    """This module builds its own openai client and uses the Responses API (not Chat
    Completions, for web_search_preview) - so it calls usage_tracking directly, right after
    client.responses.create(...). Always trigger=automatico: the daily digest is generated
    by a background job, never directly requested by the user in the moment (per the
    usage-tracking spec, this is why it must NOT count as a "giorno attivo")."""
    usage = getattr(resp, "usage", None) if resp is not None else None
    cached = 0
    details = getattr(usage, "input_tokens_details", None) if usage else None
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    ut.fire_and_forget_llm_call(
        user_id=user_id, feature="invio_news", channel="sistema", trigger="automatico",
        model=(getattr(resp, "model", None) if resp is not None else None) or MODEL,
        endpoint="responses",
        input_tokens=(getattr(usage, "input_tokens", 0) or 0) if usage else 0,
        cached_input_tokens=cached,
        output_tokens=(getattr(usage, "output_tokens", 0) or 0) if usage else 0,
        status=status, request_id=getattr(resp, "id", None) if resp is not None else None,
    )


def _profile_description(user: dict) -> str:
    bits = []
    if user.get("profession"):
        bits.append(f"professione: {user['profession']}")
    if user.get("sector"):
        bits.append(f"settore: {user['sector']}")
    if user.get("verticals"):
        bits.append(f"ambiti di lavoro: {', '.join(user['verticals'])}")
    if user.get("interests"):
        bits.append(f"interessi personali: {', '.join(user['interests'])}")
    return "; ".join(bits) or "nessun profilo specifico indicato: cerca notizie generali di attualità italiana"


def _preference_block(prefs: dict | None) -> str:
    prefs = prefs or {}
    lines = []
    if prefs.get("liked_sources"):
        lines.append(
            "L'utente ha apprezzato in passato notizie provenienti da queste fonti: "
            f"{', '.join(prefs['liked_sources'])}. Se trovi contenuti recenti e pertinenti da queste fonti, dai loro priorità."
        )
    if prefs.get("disliked_sources"):
        lines.append(
            "L'utente ha segnalato come poco interessanti notizie provenienti da queste fonti: "
            f"{', '.join(prefs['disliked_sources'])}. Evitale, a meno che non ci sia nulla di meglio sull'argomento."
        )
    return ("\n" + "\n".join(lines)) if lines else ""


def _context_block(context: dict | None) -> str:
    context = context or {}
    lines = []
    tasks = context.get("tasks") or []
    if tasks:
        items = "; ".join(f"\"{t['title']}\" ({t['when']})" for t in tasks[:15])
        lines.append(
            f"Impegni pianificati dall'utente per oggi/questa settimana: {items}. "
            "Se uno di questi riguarda un argomento su cui ci sono notizie recenti utili (es. una scadenza, "
            "un adempimento, un evento di settore), includi anche quella notizia."
        )
    todos = context.get("todos") or []
    if todos:
        items = "; ".join(f"\"{t}\"" for t in todos[:15])
        lines.append(
            f"Attività aperte nella lista to-do dell'utente: {items}. "
            "Se pertinenti, considera anche queste come indizio di cosa può interessargli in questo momento."
        )
    return ("\n" + "\n".join(lines)) if lines else ""


async def generate_news_for_user(user: dict, prefs: dict | None = None, context: dict | None = None) -> list[dict]:
    """Returns a list of {title, summary, url, source} dicts, or [] on failure/no results.
    `prefs` (optional) is {"liked_sources": [...], "disliked_sources": [...]} learned from
    the user's past like/dislike feedback, used to steer source selection.
    `context` (optional) is {"tasks": [{"title","when"}], "todos": [...]} - the user's open
    tasks for today/this week and open to-dos, used as an extra relevance signal."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    profile_desc = _profile_description(user)

    prompt = (
        f"Oggi è {today}. Cerca sul web 4-6 notizie pubblicate nelle ultime 24-48 ore rilevanti per "
        f"questa persona ({profile_desc}). Dai priorità a notizie di lavoro/settore, poi agli interessi "
        "personali. Per ognuna scrivi un riassunto breve (2-3 frasi) in italiano e includi il link diretto "
        "alla fonte originale. Evita più notizie sullo stesso identico fatto."
        f"{_preference_block(prefs)}"
        f"{_context_block(context)}\n"
        "Rispondi SOLO con una lista JSON valida, senza alcun testo prima o dopo, in questo formato esatto: "
        '[{"title": "...", "summary": "...", "url": "https://...", "source": "nome testata"}, ...]'
    )

    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.responses.create(
            model=MODEL,
            max_output_tokens=4096,
            tools=[{"type": "web_search_preview"}],
            input=prompt,
        )
    except Exception:
        _track(None, user.get("user_id"), status="errore")
        raise
    _track(resp, user.get("user_id"))

    text = resp.output_text or ""
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        logger.warning(f"news generation: no JSON list found in response: {text[:300]!r}")
        return []
    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning(f"news generation: failed to parse JSON: {text[:300]!r}")
        return []

    cleaned = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        url = (it.get("url") or "").strip()
        if not title or not url:
            continue
        cleaned.append({
            "title": title[:200],
            "summary": (it.get("summary") or "").strip()[:600],
            "url": url,
            "source": (it.get("source") or "").strip()[:100],
        })
    return cleaned
