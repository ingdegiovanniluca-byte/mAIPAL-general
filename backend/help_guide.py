"""Help: answers about mAIPAL itself ("come creo una lista?", "cosa sai fare?"), from the guide
in help/mAIPAL-help.md - one "## " section per feature, each with a metadata line saying which
page it explains and which verticals see it (see the comment at the top of the guide).

Three ways in, all in the web app (not Telegram, for now):
- the chat in Help mode (avatar menu -> Help, or "Chiedi a Help" under a page's "i");
- the "i" next to a section's title, which shows that page's sections (GET /help/sections);
- a question to Cerca that is clearly about the app: is_about_app() says so, and the turn is
  answered from the guide instead of the user's own data. Like agent_guard, two gates: a cheap
  word check first (no model call for most messages), then a small model confirms - any doubt
  and Cerca answers as usual, so the user's data questions are never hijacked.

The guide is small: it is read from disk, re-read only when the file changes, and each answer
gets the overview, the sections of the page the user came from and the best-matching ones.
"""
import json
import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import openai

import usage_tracking as ut

logger = logging.getLogger(__name__)

GUIDE_PATH = Path(__file__).parent / "help" / "mAIPAL-help.md"
MODEL = "gpt-4o-mini"
FEATURE = "help"
OVERVIEW_ID = "panoramica"


@dataclass
class Section:
    id: str
    title: str
    body: str
    path: Optional[str] = None
    verticals: List[str] = field(default_factory=lambda: ["tutti"])

    def applies(self, vertical: Optional[str]) -> bool:
        """"tutti", "artigiano", "veterinario, nessuno" (nessuno = no vertical chosen), "!artigiano"."""
        for v in self.verticals:
            if v == "tutti" or (v == "nessuno" and not vertical) or (vertical and v == vertical):
                return True
            if v.startswith("!") and v[1:] != (vertical or ""):
                return True
        return False


_META_RE = re.compile(r"^<!--\s*(.*?)\s*-->\s*$")
_cache: dict = {"mtime": None, "sections": []}


def parse(text: str) -> List[Section]:
    out: List[Section] = []
    text = re.sub(r"\A\s*<!--.*?-->\s*", "", text, flags=re.S)   # the maintainers' note on top
    for chunk in re.split(r"^## ", text, flags=re.M)[1:]:
        lines = chunk.strip("\n").split("\n")
        title, rest = lines[0].strip(), lines[1:]
        meta = {}
        if rest and _META_RE.match(rest[0].strip()):
            for pair in _META_RE.match(rest[0].strip()).group(1).split("·"):
                if ":" in pair:
                    k, v = pair.split(":", 1)
                    meta[k.strip().lower()] = v.strip()
            rest = rest[1:]
        sid = meta.get("id") or _norm(title).replace(" ", "-")
        verts = [v.strip().lower() for v in (meta.get("verticale") or "tutti").split(",") if v.strip()]
        out.append(Section(id=sid, title=title, body="\n".join(rest).strip(), path=meta.get("path") or None, verticals=verts))
    return out


def all_sections() -> List[Section]:
    """The guide's sections, re-read only when the file changed."""
    try:
        mtime = GUIDE_PATH.stat().st_mtime
    except OSError:
        logger.error(f"help guide missing: {GUIDE_PATH}")
        return []
    if _cache["mtime"] != mtime:
        _cache["sections"] = parse(GUIDE_PATH.read_text(encoding="utf-8"))
        _cache["mtime"] = mtime
    return _cache["sections"]


def sections_for(vertical: Optional[str]) -> List[Section]:
    return [s for s in all_sections() if s.applies(vertical)]


def for_path(path: Optional[str], vertical: Optional[str]) -> List[Section]:
    """The sections explaining a page (/dashboard/liste -> Liste, and Clienti for an artigiano)."""
    p = (path or "").rstrip("/")
    return [s for s in sections_for(vertical) if s.path and p and (p == s.path or p.startswith(s.path + "/"))]


# ---- choosing the sections for a question ----

_STOP = set("""il lo la i gli le un uno una di a da in con su per tra fra e o ma se che chi cosa come dove quando
quale quali qual quanto perche non mi ti si ci vi ne del dello della dei degli delle al allo alla ai agli alle dal
dalla dai nel nella nei nelle sul sulla sui sulle col coi è e' sono ho hai ha posso puoi può devo faccio fare fa
questo questa quello quella mio mia tuo tua suo sua mai anche ancora poi solo già piu più molto tutto tutti""".split())


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _stems(s: str) -> List[str]:
    """Words of 3+ letters, stopwords out, cut to 5 letters ("liste"/"lista" -> "list")."""
    words = re.findall(r"[a-z0-9@/-]{3,}", _norm(s))
    return [w[:5] if len(w) > 5 else w.rstrip("aeio") or w for w in words if w not in _STOP]


def _score(sec: Section, stems: List[str], idf: dict) -> float:
    """Words of the question found in the section (more in its title), rare words weighing more."""
    title, counts = set(_stems(sec.title)), {}
    for w in _stems(sec.body):
        counts[w] = counts.get(w, 0) + 1
    return sum(idf.get(w, 0) * (3 * (w in title) + min(counts.get(w, 0), 3)) for w in set(stems))


def pick(question: str, vertical: Optional[str], path: Optional[str] = None, k: int = 4) -> List[Section]:
    """Overview + the page's sections + the k best matches, in the guide's order."""
    secs = sections_for(vertical)
    stems = _stems(question)
    df: dict = {}
    for sec in secs:
        for w in set(_stems(sec.title + " " + sec.body)):
            df[w] = df.get(w, 0) + 1
    idf = {w: math.log(1 + len(secs) / n) for w, n in df.items()}
    scored = sorted(((_score(sec, stems, idf), n, sec) for n, sec in enumerate(secs) if sec.id != OVERVIEW_ID), key=lambda x: (-x[0], x[1]))
    chosen = {OVERVIEW_ID} | {sec.id for sec in for_path(path, vertical)} | {sec.id for sc, _, sec in scored[:k] if sc > 0}
    return [sec for sec in secs if sec.id in chosen]


def context(question: str, vertical: Optional[str], path: Optional[str] = None) -> str:
    secs = sections_for(vertical)
    picked = pick(question, vertical, path)
    index = "\n".join(f"- {s.title}" for s in secs)
    full = "\n\n".join(f"## {s.title}\n{s.body}" for s in picked)
    return f"INDICE DELLA GUIDA (tutte le sezioni):\n{index}\n\nSEZIONI PIÙ PERTINENTI:\n{full}"


def system_prompt(user_name: str, vertical: Optional[str], today: str) -> str:
    vert = {"artigiano": "Artigiano", "veterinario": "Veterinario", "fitness": "Fitness"}.get(vertical or "", "nessuno")
    who = user_name or "l'utente"
    return (
        f"Oggi è {today}. Sei Help, la guida di mAIPAL (assistente personale AI) per {who}, "
        f"che ha il verticale: {vert}. Rispondi alle domande su COME SI USA mAIPAL e su COSA PUÒ FARE, "
        "usando SOLO la GUIDA che ricevi insieme alla domanda.\n"
        "Regole:\n"
        "- Rispondi in italiano, breve e pratico: prima la risposta, poi se servono i passi numerati.\n"
        "- Indica sempre DOVE si trova la funzione (es. \"Impostazioni → Verticale\", \"popup del profilo\", "
        "\"Chat → agente Task\") e, quando aiuta, un esempio di frase da scrivere.\n"
        "- Non inventare funzioni, menu o pulsanti che la guida non descrive. Se la guida non ne parla, dì che "
        "mAIPAL per ora non lo fa (o che non hai l'informazione) e proponi l'alternativa più vicina che la guida descrive.\n"
        "- Se la domanda riguarda i dati dell'utente (es. 'cosa c'è nella mia lista della spesa?'), spiega che per "
        "quello deve chiedere all'agente Cerca.\n"
        "- Testo semplice: puoi andare a capo e usare elenchi con \"-\" o \"1.\", ma NON usare asterischi, #, "
        "tabelle, JSON o blocchi di codice (la chat li mostrerebbe così come sono)."
    )


def user_message(question: str, vertical: Optional[str], path: Optional[str] = None) -> str:
    where = f"\nL'utente è nella pagina {path}.\n" if path else ""
    return f"GUIDA DI mAIPAL:\n{context(question, vertical, path)}\n{where}\nDOMANDA:\n{question}"


# ---- is a Cerca question about the app? ----

_APP = re.compile(r"\b(maipal|l'?app|applicazione|piattaforma)\b", re.I)
# about mAIPAL whatever else the message says
_CAPABILITY = re.compile(r"\b((che\s+)?cosa\s+(sai|puoi)\s+fare|come\s+(ti\s+uso|ti\s+posso\s+usare|funzioni)|cosa\s+fai)\b", re.I)
# a message that is only "help" / "aiuto" / "guida"
_ONLY_HELP = re.compile(r"^\W*(help|aiuto|guida)\W*$", re.I)
# about the app only when it names one of its features ("come funziona il contratto?" is not)
_HOW_IT_WORKS = re.compile(r"\b(come\s+funzion\w*|a\s+cosa\s+serv\w*|cosa\s+(fa|significa|vuol\s+dire))\b", re.I)
_HOWTO = re.compile(
    r"\b(come\s+(faccio|posso|si\s+\w+|devo|creo|aggiungo|cambio|collego|scollego|elimino|cancello|imposto|attivo|"
    r"disattivo|sposto|modifico|condivido|installo|scarico|vedo|trovo|apro|uso|metto|tolgo|scelgo|seleziono|rinomino)|"
    r"dove\s+(trovo|si\s+trova|si\s+trovano|sono|posso|vedo|cambio|imposto|metto)|"
    r"(si\s+può|si\s+puo|è\s+possibile|e'\s+possibile|riesco\s+a|posso)|"
    r"(c'è|c'e|esiste)\s+(un|una)\s+(modo|funzione|tasto|pulsante|sezione|opzione|impostazione))\b", re.I)
_FEATURE = re.compile(
    r"\b(task|to-?do|list[ae]|diario|commess[ae]|report|referto|azion[ei]\s+programmat[ae]|azion[ei]|agent[ei]|"
    r"telegram|drive|onedrive|outlook|calendar|calendario|orologio|watch|notific\w+|promemoria|cartell[ae]|"
    r"impostazioni|verticale|tema|scuro|chiaro|microfono|cronologia|chat|sezion[ei]|menu|profilo|team|news|"
    r"documenti|base\s+di\s+conoscenza|allegat\w+|tag|stella|preferit\w+|attribut\w+|camp[oi]|account|"
    r"installa\w*|abbonamento|password|lingua|pallino|widget)\b", re.I)


def looks_about_app(text: str) -> Optional[str]:
    """Gate 1. "sure": asks about mAIPAL / what it can do; "maybe": a how-to about one of its
    features (could also be a question on the user's data); None: not about the app."""
    t = (text or "").strip()
    if len(t) < 4 or len(t) > 600:
        return None
    how = _HOWTO.search(t) or _HOW_IT_WORKS.search(t)
    if _ONLY_HELP.match(t) or _CAPABILITY.search(t) or (_APP.search(t) and (how or _FEATURE.search(t))):
        return "sure"
    if how and _FEATURE.search(t):
        return "maybe"
    return None


_CONFIRM_SYSTEM = (
    "mAIPAL è un'app-assistente personale: chat con agenti (Cerca, Salva, Task, Diario, Azioni), sezioni Task, To-Do, "
    "Diario, News, Liste, Documenti, Azioni, Impostazioni, collegamenti a Drive/OneDrive/Telegram/orologio.\n"
    "L'utente ha scritto all'agente Cerca, che risponde usando i SUOI dati (note, documenti, task, liste). "
    "Devi dire se il messaggio chiede invece COME SI USA L'APP o cosa può fare (help=true), oppure chiede "
    "un'informazione sui propri dati o di cultura generale (help=false).\n"
    "Esempi help=true: 'come creo una lista?', 'dove cambio il tema scuro?', 'posso collegare outlook?', "
    "'come faccio a condividere un task con un collega?'.\n"
    "Esempi help=false: 'cosa c'è nella lista della spesa?', 'quando devo chiamare il fornitore?', "
    "'come faccio la pasta alla carbonara?', 'dove ho messo il contratto?', 'quante ore abbiamo fatto dai Rossi?'.\n"
    "Sii prudente: certain=true solo se sei sicuro. Rispondi SOLO con un JSON: {\"help\": true|false, \"certain\": true|false}"
)


async def is_about_app(text: str, user_id: Optional[str] = None) -> bool:
    """Gate 1, then (for "maybe") gate 2: a small model must be certain it is about the app."""
    gate = looks_about_app(text)
    if gate != "maybe":
        return gate == "sure"
    resp, data = None, {}
    try:
        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=30, temperature=0,
            messages=[{"role": "system", "content": _CONFIRM_SYSTEM}, {"role": "user", "content": text[:600]}],
        )
        m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        logger.exception("help check failed")
    usage = getattr(resp, "usage", None)
    ut.fire_and_forget_llm_call(
        user_id=user_id, feature=FEATURE, channel="web", trigger="utente",
        model=getattr(resp, "model", None) or MODEL, endpoint="chat.completions",
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0, cached_input_tokens=0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0, status="ok" if resp is not None else "errore",
    )
    return data.get("help") is True and data.get("certain") is True
