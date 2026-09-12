"""Generates a personalized daily news digest for a user via Claude's web search tool,
based on their profession/sector/verticals/interests (already collected at onboarding)."""
import json
import logging
import os
import re
from datetime import datetime, timezone

import anthropic

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-5"
MAX_ROUNDS = 4  # bounded retries on stop_reason == "pause_turn"


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

    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages = [{"role": "user", "content": prompt}]
    resp = None
    for _ in range(MAX_ROUNDS):
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=4096,
            tools=[{"type": "web_search_20260209", "name": "web_search"}],
            messages=messages,
        )
        if resp.stop_reason != "pause_turn":
            break
        messages = [{"role": "user", "content": prompt}, {"role": "assistant", "content": resp.content}]

    if resp is None:
        return []

    text = "".join(b.text for b in resp.content if b.type == "text")
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
