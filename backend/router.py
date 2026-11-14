"""Which agent a chat message is for, without the user choosing it ("scrivi e basta").

Four levels, in order; the first that decides, decides:

1. CONTEXT (no model): mAIPAL is waiting for an answer ("di quale commessa?", "usati o da prendere?",
   a confirmation) -> the same agent; an explicit @tag -> that agent; only photos -> the diary.
2. RULES (no model): the shapes that are never ambiguous - "ricordami di ...", "salva che ...", a plain
   question, "4 ore dai Rossi, posato ..." for an artigiano. Written to be PRECISE: when unsure they say
   nothing and the next level decides (tests/router_golden.jsonl checks they are never wrong).
3. MODEL: a small, fast model with the context (the agent of the conversation, the last messages, the
   trade, the lists, the open commesse) -> intent, confidence, reason, and a second choice. Bounded by a
   timeout: if it doesn't answer, level 4.
4. FALLBACK: the agent of the conversation going on, or the best rule guess - never stuck.

Then the THRESHOLDS: sure -> go; fairly sure -> go, showing "where it went · cambia"; unsure -> ASK
with two buttons. What changes or deletes data (lists, scheduled actions) needs a higher confidence,
otherwise it is asked.

route() only decides; it runs nothing. The same module is meant for the app and Telegram.
"""
import asyncio
import json
import logging
import os
import re
import time
from typing import Optional

import mentions

logger = logging.getLogger(__name__)

MODEL = os.environ.get("ROUTER_MODEL", "gpt-4o-mini")
TIMEOUT_S = float(os.environ.get("ROUTER_TIMEOUT_S", "2.5"))
GO = 0.80        # at or above: go
SHOW = 0.55      # at or above (below GO): go, with "· cambia" shown
RISKY_GO = 0.90  # what changes or deletes data needs this, else asked
RISKY = {"scheduled_action"}

LABELS = {
    "info_request": "Cerca", "info_upload": "Salva", "task_todo": "Task", "journal": "Diario", "job_log": "Diario",
    "work_report": "Report", "vet_report": "Referto", "lesson": "Lezioni", "scheduled_action": "Azioni",
}
WHAT = {   # for the model: what each agent does
    "info_request": "risponde a DOMANDE (sui dati salvati dall'utente, i suoi task, liste, commesse, chi è in cantiere, "
                    "clienti vicini, o in generale/sul web) e a domande su come si usa l'app",
    "info_upload": "SALVA informazioni da ricordare (note, fatti, documenti, numeri, spese e pagamenti personali) e "
                   "AGGIUNGE/MODIFICA/TOGLIE elementi nelle LISTE dell'utente",
    "task_todo": "crea task, promemoria, appuntamenti e cose da fare (con o senza data), o segna fatti / sposta / "
                 "elimina quelli esistenti",
    "journal": "il diario personale: la giornata dell'utente, come si sente, riflessioni",
    "job_log": "il DIARIO DI COMMESSA dell'artigiano: il lavoro fatto in cantiere o da un cliente (cosa è stato fatto, "
               "ore, chi c'era, materiali usati o da prendere, problemi, foto, arrivo/fine in cantiere)",
    "work_report": "il REPORT di un sopralluogo o di un intervento, dettato per intero, da cui si genera un documento",
    "vet_report": "il referto di una visita veterinaria dettato per intero",
    "lesson": "comporre una lezione di fitness (tipo, livello, numero di persone)",
    "scheduled_action": "un COMANDO da eseguire da solo e ripetutamente nel tempo ('ogni venerdì svuota la lista X', "
                        "'ogni lunedì mandami il riepilogo') - NON un promemoria ricorrente (quello è task_todo)",
}


def intents_for(vertical: Optional[str]) -> list:
    """The agents a user of that trade has (as the app's agent row: frontend ChatPage actionsFor)."""
    out = ["info_request", "info_upload", "task_todo"]
    out.append("job_log" if vertical == "artigiano" else "journal")
    if vertical == "artigiano":
        out.append("work_report")
    if not vertical or vertical == "veterinario":
        out.append("vet_report")
    if vertical == "fitness":
        out.append("lesson")
    out.append("scheduled_action")
    return out


def _diary(vertical: Optional[str]) -> str:
    return "job_log" if vertical == "artigiano" else "journal"


def _decision(intent: str, confidence: float, level: str, reason: str = "", second: Optional[str] = None,
              vertical: Optional[str] = None, parts: Optional[list] = None) -> dict:
    """The answer of route(): where to, how sure, and what the chat does with it."""
    risky = intent in RISKY
    go_at = RISKY_GO if risky else GO
    if confidence >= go_at:
        mode = "go"
    elif confidence >= SHOW and not risky:
        mode = "go_show"
    else:
        mode = "ask"
    options = [intent] + ([second] if second and second != intent else [])
    if mode == "ask" and len(options) < 2:
        options.append("info_request" if intent != "info_request" else _diary(vertical))
    return {"intent": intent, "label": LABELS.get(intent, intent), "confidence": round(float(confidence), 2), "level": level,
            "mode": mode, "options": options if mode == "ask" else [intent], "reason": reason[:160], "parts": parts or []}


# ---------------------------------------------------------------- level 1: context
def by_context(text: str, ctx: dict, vertical: Optional[str], has_images: bool) -> Optional[dict]:
    allowed = intents_for(vertical)
    if ctx.get("awaiting") and ctx.get("current_action") in allowed:      # the answer to mAIPAL's question
        return _decision(ctx["current_action"], 1.0, "context", "risposta alla domanda in corso", vertical=vertical)
    main, tags = mentions.split_mentions(text)
    if tags:
        first = tags[0]["agent"]
        agent = {"list_update": "info_upload", "journal": _diary(vertical)}.get(first, first)
        if not main.strip() and agent in allowed:                       # "@task richiamare Rossi": that agent
            return _decision(agent, 1.0, "context", "agente scritto con @", vertical=vertical)
    if has_images and len((text or "").strip()) < 25 and vertical == "artigiano":
        return _decision("job_log", 0.95, "context", "foto dal cantiere", vertical=vertical)
    return None


# ---------------------------------------------------------------- level 2: rules (precise, or nothing)
_Q_START = re.compile(
    r"^(che\s+cosa|cosa|cos'|quando|dove|chi|come\s+(mai|si|faccio|posso|devo|funziona|va)|com'è|quale|quali|qual|quanto|quanti|quante|"
    r"perch[eé]|mi\s+dici|dimmi|sai\s|cerca\s|trova\s|c'è|ci\s+sono|esiste|elenca|mostrami|fammi\s+vedere|mi\s+ricordi\s+(quando|dove|chi|cosa|come|qual))\b",
    re.I)
_SAVE = re.compile(r"^(salva|salvami|memorizza|annota|annotati|prendi\s+nota|tieni\s+a\s+mente|ricordati\s+che|segnati\s+che|registra)\b", re.I)
_TASK = re.compile(
    r"^(ricordami\s+(di|che\s+devo|che\s+dobbiamo|ogni|domani|lunedì|martedì|mercoledì|giovedì|venerdì|sabato|domenica|alle|il|tra|fra|stasera|stamattina)|"
    r"promemoria\b|(crea|creami|aggiungi|metti|fissa|programma)\s+(un|il|una|l')?\s*(task|to-?do|promemoria|appuntamento))", re.I)
_TASK_DONE = re.compile(r"^(segna|segnami)\s+(come\s+)?fatt[oaie]\b|^(sposta|rimanda|posticipa)\s+(il\s+)?(task|promemoria|appuntamento)\b", re.I)
_LIST_EDIT = re.compile(r"^(aggiungi|inserisci|iscrivi|togli|rimuovi|elimina|cancella|cambia|modifica|sposta|metti)\b", re.I)
_WORK_DONE = re.compile(
    r"\b(posat[oaie]|montat[oaie]|installat[oaie]|smontat[oaie]|cablat[oaie]|collegat[oaie]|sostituit[oaie]|riparat[oaie]|"
    r"tirat[oaie]\s+(i\s+)?(cavi|fili)|intonacat[oaie]|stuccat[oaie]|imbiancat[oaie]|piastrellat[oaie]|demolit[oaie]|"
    r"finito\s+(il|la|lo|i|le|gli)\s+(massetto|bagno|cucina|impianto|quadro|lavoro|tetto|pavimento|cappotto|getto)|"
    r"massetto|tracce|intonaco|piastrelle|corrugato|scatol[ae]\s+503|quadro\s+elettrico|lavorato)\b", re.I)
_HOURS = re.compile(r"\b\d+([.,]\d+)?\s*(ore|ora|h)\b|\b(mezza\s+giornata|tutto\s+il\s+giorno|giornata\s+intera)\b", re.I)
# a site: words (any case) or "dai Rossi" with the name capitalised (case sensitive: "da fare" is not a site)
_SITE_WORDS = re.compile(r"\b(cantiere|commessa|dal\s+(signor|sig\.?|cliente)|in\s+via)\b", re.I)
_SITE_NAME = re.compile(r"\b(dai|dal|dalla|dalle|dagli|da|presso)\s+(sig\.?\s+|signor\s+|signora\s+)?[A-Z][a-zà-ù]+")


def _site(t: str) -> bool:
    return bool(_SITE_WORDS.search(t) or _SITE_NAME.search(t))


_ARRIVE = re.compile(r"^(sono\s+arrivat[oa]|arrivat[oa]\s+(in|al|dal|dai|da)|ho\s+finito(\s+(alle|per\s+oggi))?|finito\s+per\s+oggi|inizio\s+(il\s+)?lavoro|"
                     r"stacco|vado\s+via|pausa\s+pranzo|riprendo)\b", re.I)
_RECURRING_COMMAND = re.compile(r"^ogni\s+(giorno|mattina|sera|settimana|mese|luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica)\b"
                                r".{0,60}\b(svuota|cancella|elimina|azzera|manda|mandami|invia|inviami|esporta|genera|aggiorna)\b", re.I | re.S)


def by_rules(text: str, vertical: Optional[str], lists: list) -> Optional[dict]:
    t = (text or "").strip()
    if len(t) < 3:
        return None
    allowed = intents_for(vertical)
    low = t.lower()
    question = t.endswith("?") or bool(_Q_START.match(t))
    if _RECURRING_COMMAND.match(t) and not low.startswith(("ricordami", "promemoria")):
        return _decision("scheduled_action", 0.85, "rules", "comando da ripetere nel tempo", "task_todo", vertical)   # risky: asked
    if _TASK.match(t) or _TASK_DONE.match(t):
        return _decision("task_todo", 0.95, "rules", "promemoria / cosa da fare", vertical=vertical)
    if _SAVE.match(t):
        return _decision("info_upload", 0.95, "rules", "da salvare", vertical=vertical)
    if vertical == "artigiano" and _ARRIVE.match(t):
        return _decision("job_log", 0.92, "rules", "presenza in cantiere", vertical=vertical)
    if question:
        return _decision("info_request", 0.92, "rules", "domanda", vertical=vertical)
    # a list named (whole, or a distinctive word of its name: "pilates" for "Lezioni Pilates")
    named = lambda n: re.search(rf"\b{re.escape(n.lower())}\b", low) or any(
        len(w) >= 5 and re.search(rf"\b{re.escape(w)}\b", low) for w in n.lower().split() if w not in ("lista", "liste", "lezioni", "lezione"))
    if _LIST_EDIT.match(t) and lists and any(named(n) for n in lists if len(n) >= 3):
        return _decision("info_upload", 0.9, "rules", "modifica di una lista", vertical=vertical)
    if vertical == "artigiano" and _HOURS.search(t) and (_WORK_DONE.search(t) or _site(t)):
        return _decision("job_log", 0.92, "rules", "lavoro fatto in cantiere", vertical=vertical)
    if "job_log" in allowed and _WORK_DONE.search(t) and _site(t):
        return _decision("job_log", 0.85, "rules", "lavoro fatto in cantiere", vertical=vertical)
    return None


def guess(text: str, vertical: Optional[str]) -> str:
    """A weak guess when nothing else decides (fallback only, always asked)."""
    t = (text or "").strip().lower()
    if t.endswith("?") or _Q_START.match(t):
        return "info_request"
    if any(w in t for w in ("ricordami", "devo ", "dobbiamo ", "promemoria", "entro ")):
        return "task_todo"
    if vertical == "artigiano":
        return "job_log"   # an artigiano's statement is most often about the work
    return "info_upload"


# ---------------------------------------------------------------- level 3: the model
def _system(vertical: Optional[str], allowed: list, ctx: dict, lists: list, commesse: list) -> str:
    agents = "\n".join(f"- {k} ({LABELS[k]}): {WHAT[k]}" for k in allowed)
    trade = {"artigiano": "un ARTIGIANO (impianti, cantieri, commesse, collaboratori)", "veterinario": "un VETERINARIO",
             "fitness": "un ISTRUTTORE di fitness"}.get(vertical or "", "una persona che usa l'app come assistente personale")
    hist = ctx.get("history") or []
    last = "\n".join(f"{m.get('role')}: {str(m.get('content') or '')[:200]}" for m in hist[-4:])
    return (
        f"Sei il router di mAIPAL, un assistente usato da {trade}. Scegli a quale agente va il messaggio.\n"
        f"Agenti:\n{agents}\n\n"
        "Regole:\n"
        "- Una DOMANDA (anche senza punto di domanda: 'dimmi le ore di Gino', 'chi è in cantiere') è info_request.\n"
        "- Un fatto da ricordare o una spesa personale è info_upload; aggiungere/togliere/cambiare in una lista è info_upload.\n"
        "- Una cosa da FARE in futuro (anche senza data: 'devo comprare il silicone') è task_todo.\n"
        + ("- Per l'artigiano: il RACCONTO del lavoro su un cantiere/commessa (fatto, ore, materiali, problemi) è job_log; "
           "anche 'domani porto 10 scatole 503 dai Rossi' (materiali da prendere per una commessa) e 'sono arrivato'/'ho finito' "
           "sono job_log. Una spesa pagata per i materiali di una commessa è job_log; una spesa personale è info_upload.\n"
           if vertical == "artigiano" else "")
        + "- Se il messaggio continua il discorso della conversazione in corso, resta con quell'agente.\n"
        "- Se contiene DUE richieste diverse (es. un resoconto e un promemoria), indica la principale e la seconda in 'second'.\n"
        "- confidence: 0.95 se è chiarissimo; 0.7 se è probabile ma un'altra lettura è sensata; 0.4 o meno se è ambiguo.\n"
        + (f"\nConversazione in corso con l'agente {ctx['current_action']}. Ultimi messaggi:\n{last}\n" if ctx.get("current_action") else "")
        + (f"\nListe dell'utente: {', '.join(lists[:30])}." if lists else "")
        + (f"\nCommesse aperte: {', '.join(commesse[:30])}." if commesse else "")
        + "\n\nRispondi SOLO con JSON: {\"intent\": \"<agente>\", \"confidence\": 0-1, \"second\": \"<agente o null>\", "
          "\"reason\": \"al massimo 10 parole in italiano\"}"
    )


async def by_model(text: str, vertical: Optional[str], ctx: dict, lists: list, commesse: list,
                   user_id: Optional[str] = None, channel: str = "web", client=None) -> Optional[dict]:
    allowed = intents_for(vertical)
    resp = None
    try:
        import openai
        client = client or openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = await asyncio.wait_for(client.chat.completions.create(
            model=MODEL, max_completion_tokens=90, temperature=0,
            messages=[{"role": "system", "content": _system(vertical, allowed, ctx, lists, commesse)},
                      {"role": "user", "content": (text or "")[:2500]}]), TIMEOUT_S)
        raw = resp.choices[0].message.content or ""
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.warning("router model failed: %s", type(e).__name__)
        data = None
    finally:
        _track(resp, user_id, channel)
    if not data or data.get("intent") not in allowed:
        return None
    try:
        conf = max(0.0, min(1.0, float(data.get("confidence"))))
    except (TypeError, ValueError):
        conf = 0.5
    second = data.get("second") if data.get("second") in allowed else None
    return _decision(data["intent"], conf, "model", str(data.get("reason") or ""), second, vertical)


def _track(resp, user_id, channel) -> None:
    try:
        import usage_tracking as ut
        usage = getattr(resp, "usage", None)
        ut.fire_and_forget_llm_call(
            user_id=user_id, feature="altro", channel=channel, trigger="utente", model=getattr(resp, "model", None) or MODEL,
            endpoint="chat.completions", input_tokens=getattr(usage, "prompt_tokens", 0) or 0, cached_input_tokens=0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0, status="ok" if resp is not None else "errore")
    except Exception:
        pass


# ---------------------------------------------------------------- the whole
async def route(text: str, *, vertical: Optional[str] = None, context: Optional[dict] = None, lists: Optional[list] = None,
                commesse: Optional[list] = None, has_images: bool = False, use_model: bool = True,
                user_id: Optional[str] = None, channel: str = "web", client=None) -> dict:
    """-> {"intent", "label", "confidence", "level": context|rules|model|fallback, "mode": go|go_show|ask,
    "options" (to ask), "reason", "ms"}.

    context: {"current_action": the agent of the conversation going on, "awaiting": mAIPAL asked something,
    "history": [{"role", "content"}...]}."""
    t0 = time.monotonic()
    ctx = context or {}
    out = (by_context(text, ctx, vertical, has_images) or by_rules(text, vertical, lists or []))
    if out is None and use_model:
        out = await by_model(text, vertical, ctx, lists or [], commesse or [], user_id, channel, client)
    if out is None:   # no model (off, slow, broken): the conversation's agent (shown, to be changed), else ASKED
        cur = ctx.get("current_action")
        if cur in intents_for(vertical):
            out = _decision(cur, 0.6, "fallback", "continua la conversazione", vertical=vertical)
        else:
            g = guess(text, vertical)
            other = "info_request" if g != "info_request" else ("job_log" if vertical == "artigiano" else "info_upload")
            out = _decision(g, 0.4, "fallback", "non sono sicuro", other, vertical)
    out["ms"] = int((time.monotonic() - t0) * 1000)
    return out
