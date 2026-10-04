"""Wrong agent check: "salva che il codice del wifi è 1234" sent to Cerca, "quando scade
la patente?" sent to Salva. The chat then suggests the right agent (one tap re-sends the
message there) instead of answering with the wrong one.

It must speak up only when it is SURE, so two gates in a row:
1. a cheap word check (no model call for the vast majority of messages): the message has
   the typical shape of another agent's request - a question to Salva, "salva/annota" or
   "ricordami di" to Cerca, and so on;
2. only then a small model confirms, and its suggestion is used only if it says it is
   certain. Any doubt or error: no suggestion, the chosen agent answers as usual.
"""
import json
import logging
import os
import re
from typing import Optional

import openai

import usage_tracking as ut

logger = logging.getLogger(__name__)

MODEL = "gpt-4o-mini"
AGENTS = {
    "info_request": "Cerca",
    "info_upload": "Salva",
    "task_todo": "Task",
    "journal": "Diario",
}
_FEATURE = {"info_request": "ricerca_informazioni", "info_upload": "caricamento_informazioni",
            "task_todo": "creazione_task", "journal": "diario"}

_QUESTION_START = re.compile(
    r"^(che\s+cosa|cosa|cos'|quando|dove|chi|come|quale|quali|qual|quanto|quanti|quante|perch[eé]|"
    r"mi\s+dici|dimmi|sai|cerca|trova|c'è|ci\s+sono|ho\s+mai|esiste|elenca|mostrami|fammi\s+vedere)\b", re.I)
_SAVE = re.compile(r"\b(salva|salvami|salvalo|salvala|memorizza|annota|annotati|prendi\s+nota|tieni\s+a\s+mente|"
                   r"segnati\s+che|ricordati\s+che|ricorda\s+che)\b", re.I)
_TASK = re.compile(r"\b(ricordami\s+di|ricordami\s+che\s+devo|promemoria|(crea|creami|aggiungi|metti|fissa)\s+(un|il|una)?\s*"
                   r"(task|to-?do|promemoria|appuntamento))\b", re.I)
_LIST = re.compile(r"\b(aggiungi|inserisci|togli|rimuovi|elimina|metti|crea|creami)\b.{0,60}\blist[ae]\b", re.I | re.S)


def _is_question(t: str) -> bool:
    return t.rstrip().endswith("?") or bool(_QUESTION_START.match(t.strip()))


def looks_misplaced(text: str, chosen: str) -> bool:
    """Gate 1: does the message look like another agent's job at all?"""
    t = (text or "").strip()
    if len(t) < 8 or chosen not in AGENTS:
        return False
    q, save, task, lst = _is_question(t), bool(_SAVE.search(t)), bool(_TASK.search(t)), bool(_LIST.search(t))
    if chosen == "info_request":
        return save or task or lst
    if chosen == "info_upload":
        return (q and not save) or task
    if chosen == "task_todo":
        return (q and not task) or (save and not task) or (lst and not task)
    if chosen == "journal":
        return q or task or save or lst
    return False


def _system(chosen: str) -> str:
    return (
        "In un'app ci sono quattro agenti e l'utente ne sceglie uno prima di scrivere:\n"
        "- info_request (Cerca): risponde a DOMANDE, cercando nelle informazioni salvate dall'utente, nei suoi task e "
        "liste, o sul web. Es: 'quando scade la patente?', 'cosa devo fare domani?', 'cosa c'è nella lista della spesa?'.\n"
        "- info_upload (Salva): SALVA informazioni da ricordare (note, fatti, documenti) e modifica o crea le LISTE. "
        "Es: 'il codice del wifi è 1234', 'salva che Marco è allergico alle noci', 'aggiungi il latte alla lista della spesa'.\n"
        "- task_todo (Task): crea task, promemoria e cose da fare, oppure completa/elimina quelli esistenti. "
        "Es: 'ricordami di chiamare Marco domani alle 10', 'devo comprare il regalo per Anna', 'segna come fatto il task palestra'.\n"
        "- journal (Diario): scrive il diario personale dell'utente (la sua giornata, come si sente). "
        "Es: 'oggi è stata una giornata pesante al lavoro'.\n\n"
        f"L'utente ha scelto {chosen} ({AGENTS[chosen]}). Devi dire se ha SBAGLIATO agente, cioè se il messaggio è "
        "chiaramente una richiesta per un altro agente e l'agente scelto non può farla bene.\n"
        "Sii molto prudente: rispondi certain=true SOLO se sei sicuro. Se il messaggio può avere senso anche per "
        "l'agente scelto, se è ambiguo o se è una domanda sui dati dell'utente (che Cerca sa leggere), certain=false.\n"
        "Rispondi SOLO con un JSON: {\"agent\": \"info_request|info_upload|task_todo|journal\", \"certain\": true|false, "
        "\"reason\": \"al massimo 12 parole, in italiano, rivolte all'utente\"}"
    )


async def check(text: str, chosen: str, user_id: Optional[str] = None, channel: str = "web") -> Optional[dict]:
    """None, or {"agent", "label", "reason"} when the user surely picked the wrong agent."""
    if not looks_misplaced(text, chosen):
        return None
    resp = None
    try:
        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=80, temperature=0,
            messages=[{"role": "system", "content": _system(chosen)}, {"role": "user", "content": text[:2000]}],
        )
        raw = resp.choices[0].message.content or ""
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        logger.exception("agent guard failed")
        data = {}
    usage = getattr(resp, "usage", None)
    ut.fire_and_forget_llm_call(
        user_id=user_id, feature=_FEATURE.get(chosen, "altro"), channel=channel, trigger="utente",
        model=getattr(resp, "model", None) or MODEL, endpoint="chat.completions",
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0, cached_input_tokens=0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0, status="ok" if resp is not None else "errore",
    )
    agent = data.get("agent")
    if data.get("certain") is not True or agent not in AGENTS or agent == chosen:
        return None
    return {"agent": agent, "label": AGENTS[agent], "reason": str(data.get("reason") or "").strip()[:160]}
