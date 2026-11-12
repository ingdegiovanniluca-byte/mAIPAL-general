"""Diario di commessa (verticale artigiano): what was done on a job, day by day.

A dictated or written entry ("oggi io e Gino 4 ore dai Rossi, posati 20 metri di corrugato,
manca una scatola 503") becomes a clean text plus the facts the rapporto d'intervento needs:
hours per person, materials with quantity and unit, problems. The model only reads what was
said - never invents quantities or hours. Which commessa it belongs to is decided by the
caller (server.py), deterministically where possible.
"""
import json
import logging
import os
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import openai

import usage_tracking as ut

logger = logging.getLogger(__name__)

MODEL = "gpt-4o"
FEATURE = "diario"
LOCAL_TZ = ZoneInfo("Europe/Rome")
IT_WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]


def today_local() -> date:
    return datetime.now(LOCAL_TZ).date()


def _track(resp, user_id: Optional[str], channel: str, status: str = "ok"):
    usage = getattr(resp, "usage", None) if resp is not None else None
    ut.fire_and_forget_llm_call(
        user_id=user_id, feature=FEATURE, channel=channel, trigger="utente",
        model=(getattr(resp, "model", None) if resp is not None else None) or MODEL, endpoint="chat.completions",
        input_tokens=(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0, cached_input_tokens=0,
        output_tokens=(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
        status=status, request_id=getattr(resp, "id", None) if resp is not None else None,
    )


def _num(v) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v))
    return float(m.group(0).replace(",", ".")) if m else None


def _fmt_num(x: Optional[float]) -> str:
    if x is None:
        return ""
    return str(int(x)) if float(x).is_integer() else f"{x:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def clean_hours(rows, speaker: str) -> list:
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        h = _num(r.get("hours"))
        if h is None or h <= 0 or h > 24 * 7:
            continue
        who = str(r.get("who") or "").strip() or speaker
        if who.lower() in ("io", "me", "il sottoscritto"):
            who = speaker
        out.append({"who": who[:60], "hours": round(h, 2)})
    return out


MAT_STATUS = ("usato", "da_prendere", "dubbio")


def clean_materials(rows) -> list:
    """[{name, qty, unit, status, for_date}] - status: used on site, to take/buy later, or not
    clear (asked); for_date: the day it is needed (only for the ones to take)."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not str(r.get("name") or "").strip():
            continue
        st = str(r.get("status") or "usato").strip().lower().replace(" ", "_")
        out.append({"name": str(r["name"]).strip()[:120], "qty": _num(r.get("qty")),
                    "unit": str(r.get("unit") or "").strip()[:20], "status": st if st in MAT_STATUS else "usato",
                    "for_date": str(r.get("for_date") or "")[:10] or None, "who": str(r.get("who") or "").strip()[:60]})
    return out


def mat_label(m: dict) -> str:
    return " ".join(x for x in (_fmt_num(m.get("qty")), m.get("unit") or "", m["name"]) if x).strip()


# ---- materials used vs to take: "domani porto 10 scatole 503" is not material used. The model
# says it; the words around the material confirm it (a plan word wins over the model's "usato",
# a use word over its "da_prendere"; neither: the model's call).
_PLAN_CUE = re.compile(
    r"\b(domani|dopodomani|stasera|prossim\w*|porto|portiamo|portare|porta|porti|prendo|prendiamo|prendere|prendi|"
    r"comprar\w*|compro|compriamo|ordin\w*|serv(e|ono|ira|iranno|irebbe|irebbero)|bisogna|occorr\w*|ricord\w*|"
    r"procurar\w*|recuperar\w*|da\s+prendere|da\s+portare|da\s+comprare|da\s+ordinare)\b")
_USE_CUE = re.compile(
    r"\b(posat\w*|montat\w*|usat\w*|utilizzat\w*|messo|messi|messa|messe|installat\w*|consumat\w*|stes[oaie]|"
    r"gettat\w*|applicat\w*|fissat\w*|collegat\w*|murat\w*|cambiat\w*|sostituit\w*|finit[oaie]|impiegat\w*)\b")
_CLAUSE_SPLIT = re.compile(r"[.;!?\n,]+|\s+(?:e|ma|poi)\s+(?=domani|dopodomani|stasera|poi|porto|portiamo|prendo|prendiamo|compro|ordino)")


def material_status(m: dict, raw: str) -> str:
    """The status of a material from the words of the part of the message that names it."""
    names = _words(m.get("name") or "")
    if not names:
        return m.get("status") or "usato"
    for clause in _CLAUSE_SPLIT.split(_norm(raw)):
        if not clause or not any(_said(w, set(_words(clause))) for w in names[:2]):
            continue
        plan, use = bool(_PLAN_CUE.search(clause)), bool(_USE_CUE.search(clause))
        if plan and not use:
            return "da_prendere"
        if use and not plan:
            return "usato"
    whole = _norm(raw)   # its own part says nothing: the whole message, if it is all about later
    if _PLAN_CUE.search(whole) and not _USE_CUE.search(whole):
        return "da_prendere"
    return m.get("status") or "usato"


def without_plans(text: str, planned: list) -> str:
    """The text without its parts about the materials to take ("domani porto 10 scatole 503"):
    what is left is what was done; "" when the message was only about those."""
    names = [w for m in planned for w in _words(m.get("name") or "")[:2]]
    keep = []
    for part in re.split(r"(?<=[.;!?])\s+|[;\n]+|,\s+", text or ""):
        p = part.strip(" .,;")
        if not p:
            continue
        words = set(_words(p))
        if any(_said(w, words) for w in names):
            continue
        if _PLAN_CUE.search(_norm(p)) and len(words) <= 3:   # "e anche per domani"
            continue
        keep.append(p)
    out = ", ".join(keep).strip()
    return (out[0].upper() + out[1:] + ("" if out.endswith((".", "!", "?")) else ".")) if out else ""


def plan_date(m: dict, raw: str, day: date) -> str:
    """The day a material to take is needed: the one said (not past), "dopodomani", else tomorrow."""
    try:
        d = date.fromisoformat(str(m.get("for_date") or "")[:10])
        if day <= d <= day + timedelta(days=60):
            return d.isoformat()
    except ValueError:
        pass
    n = _norm(raw)
    return (day + timedelta(days=2 if re.search(r"\bdopodomani\b", n) else 0 if re.search(r"\b(stasera|oggi pomeriggio)\b", n) else 1)).isoformat()


# "solo per me", "ricordalo solo a me", "non dirlo agli altri": a material to take that stays the
# writer's (otherwise the colleagues of their company on that commessa see it too)
_ONLY_ME = re.compile(r"\bsolo (?:per|a) me\b|\bsolo (?:io|mio|mia)\b|\bpromemoria personale\b"
                      r"|\bnon (?:lo |la |li |le )?(?:dire|dirlo|mandare|mandarlo|mostrare|mostrarlo|condividere|condividerlo|avvisare)"
                      r"(?:la|li|le)? (?:a |agli |ai |alle )?(?:altri|colleghi|ragazzi|compagni)\b")


def only_for_me(raw: str) -> bool:
    return bool(_ONLY_ME.search(_norm(raw or "")))


def clean_problems(rows) -> list:
    return [str(p).strip()[:300] for p in (rows if isinstance(rows, list) else []) if str(p or "").strip()]


# ---- an entry holds only what the user said ----
# The agent Diario only WRITES entries: a question ("com'è messa la commessa dei Rossi?") is
# not saved, an entry it can't understand is not saved either (it asks instead), and what is
# saved is checked against the user's own words, so nothing invented ever lands in the diary.

KINDS = ("nota", "domanda", "non_chiara")
# "descrizione attività: …", "il lavoro consiste in …": the commessa's description (only its
# owner or an administrator writes it - never a collaborator)
_DESCRIPTION_START = re.compile(
    r"^\s*(?:(?:la\s+)?descrizione\s+(?:dell[ae']?\s*|dei\s+|delle\s+)?(?:attivit[aà]|lavori|lavoro|commessa|intervento|opere)"
    r"|attivit[aà]\s+da\s+(?:svolgere|eseguire)|oggetto\s+(?:dei\s+lavori|della\s+commessa|dell'intervento)"
    r"|il\s+lavoro\s+(?:consiste|prevede)|l'(?:attivit[aà]|intervento)\s+(?:consiste|prevede))\b\s*[:.,-]?\s*", re.I)
_DESCRIPTION_ADD = re.compile(r"^\s*(?:aggiungi|aggiungere|integra)\b.{0,40}\bdescrizione\b\s*[:.,-]?\s*", re.I)


def description_said(text: str) -> Optional[dict]:
    """A message that explicitly sets the commessa's description -> {"text", "mode": sostituisci|aggiungi}."""
    def rest(t: str) -> str:   # "… per i Rossi: rifacimento del bagno" -> "rifacimento del bagno" (the client finds the commessa)
        t = re.sub(r"^(?:per|del|della|dei|degli|delle|di|da)\s+[^:\n]{1,60}:\s*", "", t.strip(), flags=re.I)
        return re.sub(r"^(?:è|e'|sono)\b\s*(?:questa|questo|la seguente|le seguenti|questi|queste)?\s*:?\s*", "", t, flags=re.I).strip()
    m = _DESCRIPTION_ADD.match(text or "")
    if m and len(rest(text[m.end():])) >= 3:
        return {"text": rest(text[m.end():]), "mode": "aggiungi"}
    m = _DESCRIPTION_START.match(text or "")
    if m and len(rest(text[m.end():])) >= 8:
        # "il lavoro consiste in …" keeps its words; "descrizione attività: …" only what follows
        keep = re.match(r"\s*(?:il\s+lavoro|l'(?:attivit|intervento))", text, re.I)
        return {"text": (text.strip() if keep else rest(text[m.end():])), "mode": "sostituisci"}
    return None
_STOP = set("""il lo la i gli le un uno una di a da in con su per tra fra e o ma se che chi cosa come dove quando
del dello della dei degli delle al allo alla ai agli alle dal dalla dai nel nella nei nelle sul sulla sui sulle
è e' sono ho hai ha abbiamo hanno siamo era stato stata stati fatto fatta fatti non mi ti si ci vi ne anche poi
oggi ieri domani questo questa quello quella io noi tu lui lei loro più già molto tutto tutti ogni""".split())
_QUESTION_START = re.compile(
    r"^(che\s+cosa|cosa|cos'|quando|dove|chi|come|quale|quali|qual|quanto|quanti|quante|perch[eé]|"
    r"mi\s+dici|dimmi|sai|c'è|ci\s+sono|abbiamo|hai|com'è|com'e)\b", re.I)
_NUM_WORDS = {"una": 1, "un": 1, "uno": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7,
              "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "mezza": 0.5, "mezzo": 0.5}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _words(s: str) -> list:
    return [w for w in re.findall(r"[a-z0-9]+", _norm(s)) if len(w) >= 3 and w not in _STOP]


def _said(word: str, said: set) -> bool:
    """A word of the saved entry is in what the user said - the same word, the same root
    (posati/posato) or the same word misspelled (corugato/corrugato)."""
    if word in said or word.isdigit():
        return word in said
    from difflib import SequenceMatcher
    return any(w[:5] == word[:5] or SequenceMatcher(None, w, word).ratio() >= 0.8 for w in said)


def grounded(text: str, raw: str, min_share: float = 0.7) -> bool:
    words = _words(text)
    said = set(_words(raw))
    if not words:
        return True
    return sum(1 for w in words if _said(w, said)) / len(words) >= min_share


def is_plain_question(raw: str) -> bool:
    """One sentence that asks something, with nothing reported ("cosa abbiamo fatto dai Rossi?")."""
    t = " ".join((raw or "").split())
    parts = [p for p in re.split(r"(?<=[.!?])\s+", t) if p.strip()]
    return len(parts) == 1 and (t.endswith("?") or bool(_QUESTION_START.match(t)))


def _hours_said(h: float, raw: str) -> bool:
    """The hours were said: the number itself, in words, or a time range ("dalle 8 alle 12")."""
    n = _norm(raw)
    nums = {float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", n)}
    nums |= {float(v) for k, v in _NUM_WORDS.items() if re.search(rf"\b{k}\b", n)}
    if h in nums or (h % 1 == 0.5 and (h - 0.5) in nums and re.search(r"\be\s+mezz", n)):
        return True
    return bool(re.search(r"\bdall[ae']\s*\d|\bmezza\s+giornata|\bgiornata\s+intera|\btutto\s+il\s+giorno", n))


# what stops or slows the works, said in a note: an absence (ill, injured), the weather, the site
# stopped, a delivery not arrived, a delay. A problem even when the model wrote it in its own words
# (dropped as not said) or missed it: the writer's own sentence is kept.
_IMPEDIMENT = re.compile(
    r"\bnon (?:sono|siamo|e|è|era|erano) (?:potut|riuscit|andat|venut|passat)\w*|\bstat[oaie] mal[ei]\b|\bsto male\b|\bmalat\w*|"
    r"\binfluenza\b|\bfebbre\b|\binfortun\w*|\bferit[oaie]\b|\bricoverat\w*|\bassent[ei]\b|\bassenza\b|"
    r"\bmaltempo\b|\bpioggia\b|\bpiove\w*|\bneve\b|\bnevica\w*|\bgrandine\b|"
    r"\b(?:cantiere|lavori) (?:e |è )?(?:fermo|fermi|chiuso|bloccat\w*|sospes\w*)\b|"
    r"\bnon (?:e|è|sono) (?:ancora )?arrivat\w*|\bin ritardo\b")


def _sentences(raw: str) -> list:
    return [x.strip(" ,-") for x in re.split(r"(?<=[.!?;])\s+|\n+", raw or "") if x.strip(" ,-")]


def impediment_problems(problems: list, raw: str) -> list:
    """The problems kept, plus each sentence of the note that says the work was stopped or
    slowed (absence, weather, site stopped, delays) when no problem kept already tells it."""
    out = list(problems)
    for sent in _sentences(raw):
        if not _IMPEDIMENT.search(_norm(sent)):
            continue
        covered = any(grounded(p, sent, 0.5) or grounded(sent, p, 0.5) for p in out)
        if not covered:
            t = sent.rstrip(".;")
            out.append((t[0].upper() + t[1:])[:300])
    return out


def ground(parsed: dict, raw: str) -> dict:
    """Keeps only what the user said: the cleaned-up text if it holds to their words (else
    their own words), hours that were said, materials and problems named in the message."""
    out = dict(parsed)
    if not grounded(out.get("text") or "", raw):
        out["text"] = " ".join((raw or "").split())
    said = set(_words(raw))
    out["hours"] = [h for h in out.get("hours") or [] if _hours_said(float(h["hours"]), raw)]
    out["materials"] = [m for m in out.get("materials") or [] if any(_said(w, said) for w in _words(m["name"]))]
    out["problems"] = impediment_problems([p for p in out.get("problems") or [] if grounded(p, raw, 0.5)], raw)
    return out


# ---- times of arrival / end said in a note ("ho finito alle 17.10", "dalle 8 alle 17", "ho sbagliato
# l'orario di fine: 17.10"): what a forgotten 📍 or a wrong end is corrected with. Only what was
# written counts - the model's reading is kept when its numbers are in the message, else the
# message's own words are read.

_CLOCK = r"(?:(?:alle|ore|le|dalle|verso le)\s+(?:ore\s+)?(\d{1,2})(?:[:.,h](\d{2}))?|(\d{1,2})[:.](\d{2}))\b"
_RANGE = re.compile(r"\bdall[ae']\s*(\d{1,2})(?:[:.,h](\d{2}))?\s+(?:alle|a)\s+(\d{1,2})(?:[:.,h](\d{2}))?\b")
# between the words and the time only filler ("ho finito alle 17", "il fine cantiere era 18.10"), so that
# "ho finito il massetto alle 12" is not an end of the day
_GAP = r"(?:\s*(?:[,:;-]|\.{1,3}|\b(?:era|erano|e|di|lavorare|in|cantiere|oggi|ieri|stamattina|stasera|invece|realmente|veramente|corretto|giusto)\b))*\s*"
_END_AT = re.compile(r"\b(?:(?:orario|ora) di (?:fine|uscita)|fine (?:del )?(?:cantiere|lavori|lavoro|giornata|turno)|(?:ho|abbiamo) finito|"
                     r"finit[oaie] di lavorare|uscit[oaie]|andat[oaie] via|staccat[oaie]|stacco|smess[oaie])" + _GAP + _CLOCK)
_START_AT = re.compile(r"\b(?:(?:orario|ora) di (?:inizio|arrivo|entrata)|inizio (?:del )?(?:cantiere|lavori|lavoro|giornata|turno)|"
                       r"(?:sono|siamo) arrivat[oaie]|arrivat[oaie]|(?:ho|abbiamo) (?:iniziato|cominciato|attaccato)|entrat[oaie])" + _GAP + _CLOCK)


def _hhmm(h, m) -> Optional[str]:
    try:
        h, m = int(h), int(m or 0)
    except (TypeError, ValueError):
        return None
    return f"{h:02d}:{m:02d}" if 0 <= h <= 23 and 0 <= m <= 59 else None


def _clock_of(match, base: int = 1) -> Optional[str]:
    g = match.groups()[base - 1:base + 3]
    return _hhmm(g[0], g[1]) if g[0] else _hhmm(g[2], g[3])


def _clock_said(hhmm: str, raw: str) -> bool:
    h, m = int(hhmm[:2]), int(hhmm[3:])
    n = _norm(raw)
    if m:
        return bool(re.search(rf"\b0?{h}\s*[:.,h]\s*{m:02d}\b", n))
    return bool(re.search(rf"\b0?{h}(?:[:.,h]00)?\b", n))


def clock_times(model_times, raw: str) -> dict:
    """{"start": "HH:MM"|None, "end": "HH:MM"|None}: the times of arrival and end written in the note."""
    out = {"start": None, "end": None}
    mt = model_times if isinstance(model_times, dict) else {}
    for k in out:
        v = str(mt.get(k) or "").strip().replace(".", ":")
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
        hm = _hhmm(m.group(1), m.group(2)) if m else None
        if hm and _clock_said(hm, raw):
            out[k] = hm
    if out["start"] or out["end"]:
        return out
    n = _norm(raw)
    r = _RANGE.search(n)
    if r:
        return {"start": _hhmm(r.group(1), r.group(2)), "end": _hhmm(r.group(3), r.group(4))}
    e, st = _END_AT.search(n), _START_AT.search(n)
    return {"start": _clock_of(st) if st else None, "end": _clock_of(e) if e else None}


def valid_day(s, fallback: date) -> str:
    """The entry's day: what the model computed if it's a real, not-future date, else today."""
    try:
        d = date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return fallback.isoformat()
    if d > fallback or d < fallback - timedelta(days=366):
        return fallback.isoformat()
    return d.isoformat()


async def interpret(text: str, speaker: str, team: list, known: Optional[dict] = None,
                    user_id: Optional[str] = None, channel: str = "web", photos: int = 0) -> dict:
    """-> {"kind": nota|domanda|non_chiara, "doubt": str, "date", "text", "hours": [{who, hours}],
    "materials": [{name, qty, unit}], "problems": [...], "client": str, "commessa": str}"""
    today = today_local()
    team_s = ", ".join(t for t in team if t and t != speaker) or "nessuno registrato"
    job_s = (f"La voce riguarda la commessa «{known.get('title')}» del cliente {known.get('client')}.\n"
             if known and known.get("title") else "")
    if photos:   # the description of photos just sent ("in questa foto…", "qui abbiamo…") is an entry
        job_s += (f"Il messaggio descrive {'la foto' if photos == 1 else f'le {photos} foto'} del cantiere appena "
                  "mandat" + ("a" if photos == 1 else "e") + ": se racconta cosa si vede o il lavoro fotografato è una \"nota\".\n")
    system = (
        "Sei l'assistente di un'impresa artigiana (impianti, edilizia, manutenzioni). Ricevi una voce del "
        "DIARIO DI COMMESSA: cosa è stato fatto in cantiere. Oggi è "
        f"{IT_WEEKDAYS[today.weekday()]} {today.isoformat()}. Chi scrive è {speaker} (\"io\" = {speaker}); "
        f"colleghi del team: {team_s}.\n{job_s}\n"
        "Compiti:\n"
        "0. \"kind\": cosa ha scritto l'utente.\n"
        "   - \"nota\": racconta lavori fatti o da fare, ore, materiali, problemi, cose successe in cantiere, "
        "anche solo materiali da prendere o portare (\"domani porto 10 scatole 503\"), anche solo l'orario di arrivo "
        "o di fine in cantiere, un'assenza (\"oggi non sono potuto andare in cantiere, sono stato male\") "
        "o la correzione di un orario segnato male (\"ho finito alle 17.10\", \"ho sbagliato "
        "l'orario di fine, era 17.10\", \"ieri dalle 8 alle 17\").\n"
        "   - \"domanda\": CHIEDE informazioni invece di raccontare (\"com'è messa la commessa dei Rossi?\", "
        "\"cosa abbiamo fatto ieri?\", \"quante ore abbiamo fatto?\", \"mancano materiali?\").\n"
        "   - \"non_chiara\": non si capisce cosa annotare (troppo vaga, frasi senza senso, saluti, \"ok\", "
        "\"sì\") oppure manca un'informazione indispensabile per capirla.\n"
        "   Con \"domanda\" o \"non_chiara\" lascia vuoti tutti gli altri campi. Con \"non_chiara\" scrivi in "
        "\"doubt\" una domanda breve per chiarire (es. \"Cosa avete fatto e da quale cliente?\").\n"
        "1. \"text\": il testo sistemato (grammatica, punteggiatura, termini tecnici corretti), stessa persona "
        "e stessi fatti. NON aggiungere nulla che non sia detto. NON metterci i materiali da prendere/portare/"
        "comprare/ordinare (vanno solo in materials con status da_prendere): se il messaggio parla solo di quelli, "
        "\"text\" è vuoto.\n"
        "2. \"date\": il giorno a cui si riferisce (\"ieri\", \"lunedì\", \"il 3\") in formato YYYY-MM-DD; se non "
        "lo dice, oggi.\n"
        "3. \"hours\": ore lavorate PER PERSONA, [{\"who\": nome, \"hours\": numero}]. \"Io e Gino 4 ore\" = 4 "
        "a testa (due righe). \"Dalle 8 alle 12\" = 4. Un collega senza nome: \"who\": \"collega\". Se le ore "
        "non sono dette: [] (MAI stimarle).\n"
        "4. \"materials\": materiali nominati, [{\"name\", \"qty\": numero o null, \"unit\": \"m|pz|kg|l|"
        "sacchi|...\" o \"\", \"status\", \"for_date\"}]. Solo quelli detti, con le quantità dette; niente attrezzi. "
        "\"status\": \"usato\" se è stato usato/posato/montato (già successo); \"da_prendere\" se va preso, portato, "
        "comprato o ordinato per dopo (\"domani porto\", \"serve\", \"da prendere\"); \"dubbio\" se non si capisce "
        "(es. solo un elenco di materiali senza verbo). \"for_date\": per i da_prendere il giorno in cui servono "
        "(YYYY-MM-DD, \"domani\" = il giorno dopo oggi), altrimenti null. \"who\": per i da_prendere chi li deve prendere "
        "se è detto (\"ricorda a Mario di prendere…\" -> \"Mario\", \"Gino porta…\" -> \"Gino\"), altrimenti \"\".\n"
        "5. \"problems\": problemi, imprevisti, cose mancanti o da rifare, frasi brevi. Sono problemi anche le ASSENZE e "
        "tutto ciò che ferma o rallenta i lavori: qualcuno che non è potuto andare in cantiere (malattia, infortunio, "
        "motivi personali), maltempo, cantiere fermo, consegne non arrivate, cliente assente, ritardi. Scrivili con le parole "
        f"di chi scrive (\"non sono potuto andare in cantiere perché sono stato male\" -> \"{speaker} non è potuto andare in "
        "cantiere perché stava male\"), non con un riassunto (\"assenza per malattia\"). Nessuno: [].\n"
        "6. \"client\" e \"commessa\": il cliente e i lavori/cantiere come li nomina il testo (\"dai Rossi\" -> "
        "\"Rossi\"), stringa vuota se non li nomina.\n"
        "7. \"times\": gli orari di arrivo/inizio (\"start\") e di fine/uscita (\"end\") in cantiere di chi scrive, "
        "come \"HH:MM\", solo se scritti (\"ho finito alle 17.10\" -> end \"17:10\"; \"dalle 8 alle 17\" -> start "
        "\"08:00\", end \"17:00\"); altrimenti null. Il giorno va in \"date\" (\"ieri\" -> ieri).\n"
        "8. \"expenses\": le SPESE sostenute per la commessa con il loro importo SCRITTO nel messaggio (acquisti, noleggi, "
        "trasporti: \"comprato nastro 8 €\" -> {\"description\": \"nastro\", \"amount\": 8, \"supplier\": \"\"}), con il fornitore se detto. "
        "Senza importo scritto non è una spesa. Se la spesa è il costo di un materiale usato (\"montato un interruttore da 50 A, costo 50 €\"), "
        "mettilo in \"materials\" E in \"expenses\" con lo stesso nome. Nessuna: [].\n"
        "MAI inventare: ogni informazione deve essere scritta dall'utente.\n"
        "Rispondi SOLO con JSON: {\"kind\": \"nota|domanda|non_chiara\", \"doubt\": \"\", \"date\": \"\", \"text\": \"\", "
        "\"hours\": [], \"materials\": [], \"problems\": [], \"expenses\": [], \"times\": {\"start\": null, \"end\": null}, "
        "\"client\": \"\", \"commessa\": \"\"}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=2048, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
        )
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    parsed = json.loads(m.group(0)) if m else {}
    kind = str(parsed.get("kind") or "nota").strip().lower().replace(" ", "_")
    mats = clean_materials(parsed.get("materials"))
    for m in mats:
        m["status"] = material_status(m, text)
        m["for_date"] = plan_date(m, text, today) if m["status"] == "da_prendere" else None
    only_plan = bool(mats) and all(m["status"] == "da_prendere" for m in mats) \
        and not str(parsed.get("text") or "").strip() and not parsed.get("hours") and not parsed.get("problems")
    return {
        "kind": kind if kind in KINDS else "nota",
        "doubt": str(parsed.get("doubt") or "").strip()[:200],
        "date": valid_day(parsed.get("date"), today),
        "text": "" if only_plan else (str(parsed.get("text") or "").strip() or text.strip()),
        "hours": clean_hours(parsed.get("hours"), speaker),
        "materials": mats,
        "problems": clean_problems(parsed.get("problems")),
        "times": clock_times(parsed.get("times"), text),
        "expenses": clean_expenses(parsed.get("expenses"), text),
        "client": str(parsed.get("client") or "").strip(),
        "commessa": str(parsed.get("commessa") or "").strip(),
    }


# ---- a new commessa said in a message: "Nuova commessa per Mario Rossi, rifacimento bagno in via
# Garibaldi 5 a Torino, inizio 10 novembre" (RF-CRE-02). Only what is written; asked when missing.
# "crea una commessa …", "creami una commessa", "mi crei una nuova commessa", "per Luca D crea commessa …", "nuova commessa",
# "commessa nuova", "nuovo cantiere per …" - anywhere in the message. Never "apri LA commessa del bagno" (an existing one)
# and never a question on how to do it ("come si crea una commessa?").
_NEW_COMMESSA = re.compile(
    r"\b(?:(?:crea|creami|creare|crei|creiamo|creeresti|apri|aprimi|aprire|apriamo|aggiungi|aggiungimi|aggiungere|inserisci|inserire|"
    r"registra|registrami|registrare|fammi|metti)\s+(?:(?:una|un|un'|nuova|nuovo|altra|anche|ancora|subito|pure)\s+){0,3}"
    r"(?:commessa|cantiere)\b"
    r"|\bnuova\s+commessa\b|\bcommessa\s+nuova\b|\bnuovo\s+(?:cantiere|lavoro)\s+per\b)", re.I)
_HOW_TO = re.compile(r"^\s*(?:come|dove|quando|perch[eé]|cosa|che\s+cosa|si\s+pu[oò]|posso\s+sapere)\b", re.I)


def new_commessa_said(text: str) -> bool:
    t = text or ""
    return bool(_NEW_COMMESSA.search(t)) and not _HOW_TO.match(t)


async def read_new_commessa(text: str, user_id: Optional[str] = None, channel: str = "web") -> dict:
    """-> {"client", "title", "address", "start", "end", "value", "description"} - only what the
    message says (dates YYYY-MM-DD, value a number written in it), "" / None otherwise."""
    today = today_local()
    system = (
        "Sei l'assistente di un'impresa artigiana. Il messaggio chiede di creare una NUOVA COMMESSA. "
        f"Oggi è {IT_WEEKDAYS[today.weekday()]} {today.isoformat()}. Estrai SOLO ciò che è scritto:\n"
        "\"client\": il cliente (persona o azienda) come scritto; \"title\": il nome breve dei lavori (es. \"Rifacimento bagno\"); "
        "\"address\": l'indirizzo del cantiere; \"start\" e \"end\": date di inizio e fine previste in YYYY-MM-DD (\"10 novembre\" -> "
        "la prossima data con quel giorno); \"value\": il valore/importo in euro come numero se scritto; \"description\": "
        "i dettagli dei lavori se ce ne sono oltre al nome. Ciò che manca: stringa vuota (value null). MAI inventare.\n"
        "Rispondi SOLO con JSON: {\"client\": \"\", \"title\": \"\", \"address\": \"\", \"start\": \"\", \"end\": \"\", \"value\": null, \"description\": \"\"}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(model=MODEL, max_completion_tokens=800, response_format={"type": "json_object"},
                                                    messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    p = json.loads(m.group(0)) if m else {}
    said = set(_words(text))

    def grounded_name(v: str) -> str:
        v = " ".join(str(v or "").split())[:120]
        words = _words(v)
        return v if words and sum(1 for w in words if _said(w, said)) / len(words) >= 0.6 else ""

    def day(v) -> str:
        try:
            d = date.fromisoformat(str(v or "")[:10])
        except ValueError:
            return ""
        return d.isoformat() if today - timedelta(days=366) <= d <= today + timedelta(days=3 * 366) else ""

    value = p.get("value")
    try:
        value = round(float(str(value).replace(",", ".")), 2) if value not in (None, "") else None
    except (TypeError, ValueError):
        value = None
    if value is not None and (value <= 0 or not amount_in_text(value, text)):
        value = None
    return {"client": grounded_name(p.get("client")), "title": grounded_name(p.get("title")),
            "address": grounded_name(p.get("address")), "start": day(p.get("start")), "end": day(p.get("end")),
            "value": value, "description": " ".join(str(p.get("description") or "").split())[:1000]}


# ---- the commessa's description from a document: a site-survey report or a quote ----
DOC_KINDS = ("preventivo", "sopralluogo", "altro")


def amount_in_text(amount: float, raw: str) -> bool:
    """The amount is written in the document (12.500,00 / 12500,00 / 12,500.00 / 12500)."""
    try:
        cents = round(float(amount) * 100)
    except (TypeError, ValueError):
        return False
    if cents <= 0:
        return False
    for m in re.finditer(r"\d[\d.,' ]*\d|\d", raw or ""):
        tok = m.group(0).replace(" ", "").replace("'", "")
        for dec, th in ((",", "."), (".", ",")):
            t = tok.replace(th, "")
            if t.count(dec) > 1:
                continue
            try:
                if round(float(t.replace(dec, ".")) * 100) == cents:
                    return True
            except ValueError:
                pass
    return False


async def read_document(text: str, commessa: dict, user_id: Optional[str] = None, channel: str = "web") -> dict:
    """-> {"kind": preventivo|sopralluogo|altro, "description": str, "amount": float|None,
    "amount_basis": "imponibile"|"totale"|""} - the activities to carry out, from the document's
    own words; the quote's amount only when written in it (the taxable one, without VAT, when both)."""
    system = (
        "Sei l'assistente di un'impresa artigiana. Ricevi il testo di un documento caricato nel diario della commessa "
        f"«{commessa.get('title')}» del cliente {commessa.get('client_name')}: di solito un PREVENTIVO o un REPORT DI SOPRALLUOGO.\n"
        "Compiti:\n"
        "1. \"kind\": \"preventivo\" (offerta con voci e prezzi), \"sopralluogo\" (report/verbale di sopralluogo), altrimenti \"altro\".\n"
        "2. \"description\": la DESCRIZIONE DELLE ATTIVITÀ DA SVOLGERE sulla commessa, scritta in modo chiaro per chi lavora: "
        "una frase introduttiva sull'oggetto dei lavori, poi l'elenco delle lavorazioni (una per riga, che inizia con \"- \"), "
        "con le quantità e le specifiche scritte nel documento. Per un sopralluogo: lo stato rilevato in breve e i lavori da fare. "
        "NIENTE prezzi, importi, sconti, condizioni di pagamento, IVA, dati fiscali o di contatto. Solo cose scritte nel documento, "
        "MAI inventare. Al massimo 1500 caratteri.\n"
        "3. \"amount\": solo per un preventivo, il valore complessivo dei lavori come numero (es. 12500.50): l'IMPONIBILE "
        "(totale senza IVA) se è indicato, altrimenti il totale indicato. null se non c'è un totale chiaro o non è un preventivo. "
        "\"amount_basis\": \"imponibile\" o \"totale\" (vuoto se amount è null).\n"
        "Rispondi SOLO con JSON: {\"kind\": \"\", \"description\": \"\", \"amount\": null, \"amount_basis\": \"\"}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=2048, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": (text or "")[:30000]}],
        )
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    parsed = json.loads(m.group(0)) if m else {}
    kind = str(parsed.get("kind") or "").strip().lower()
    kind = kind if kind in DOC_KINDS else "altro"
    amount = parsed.get("amount")
    try:
        amount = round(float(str(amount).replace(",", ".")), 2) if amount not in (None, "", 0) else None
    except (TypeError, ValueError):
        amount = None
    if amount is not None and (amount <= 0 or not amount_in_text(amount, text)):   # never a figure not written there
        amount = None
    basis = str(parsed.get("amount_basis") or "").strip().lower()
    return {"kind": kind, "description": str(parsed.get("description") or "").strip()[:4000],
            "amount": amount, "amount_basis": (basis if basis in ("imponibile", "totale") else "totale") if amount else ""}


# ---- the quote, read (AUT-PRE-01): totals, items, dates and deadlines, activities, materials ----
async def read_quote(text: str, commessa: dict, user_id: Optional[str] = None, channel: str = "web") -> dict:
    """-> {"total", "taxable", "vat", "items": [{description, amount}], "start", "end", "validity",
    "payments": [str], "activities": [str], "materials": [str], "description"} - amounts only when
    written in the document, dates only real ones; what is missing stays empty (asked, never guessed)."""
    today = today_local()
    system = (
        "Sei l'assistente di un'impresa artigiana. Ricevi il testo di un PREVENTIVO per la commessa "
        f"«{commessa.get('title')}» del cliente {commessa.get('client_name')}. Oggi è {today.isoformat()}. Estrai SOLO ciò che è scritto:\n"
        "\"total\": totale complessivo (numero) come scritto; \"taxable\": imponibile senza IVA (numero) se scritto; \"vat\": importo IVA se scritto;\n"
        "\"items\": TUTTE le voci [{\"description\": testo breve, \"qty\": quantità della voce come numero se scritta altrimenti null, "
        "\"unit\": unità come scritta (ml, m, mq, pz, cad, kg, ore, h…) o \"\", \"unit_price\": prezzo unitario se scritto o null, "
        "\"amount\": importo della voce o null}];\n"
        "\"start\", \"end\": date di inizio e fine lavori (YYYY-MM-DD) se scritte; \"validity\": data di scadenza/validità dell'offerta "
        "(YYYY-MM-DD; \"valida 30 giorni\" -> calcola da oggi) se scritta;\n"
        "\"payments\": acconti e condizioni di pagamento, frasi brevi;\n"
        "\"activities\": le attività/lavorazioni da svolgere, una frase breve ciascuna, nell'ordine;\n"
        "\"materials\": materiali indicati, frasi brevi;\n"
        "\"materials_planned\": TUTTI i materiali e i componenti da fornire o posare, compresi quelli dentro le voci (es. \"Fornitura e posa "
        "corrugato Ø25 ml 120\" -> {\"name\": \"corrugato Ø25\", \"qty\": 120, \"unit\": \"ml\"}), come [{\"name\": nome del materiale, "
        "\"qty\": quantità come numero ESATTAMENTE come scritta altrimenti null, \"unit\": unità come scritta o \"\"}]; non la manodopera;\n"
        "\"labor_hours\": le ore uomo / ore di manodopera totali previste, come numero, SOLO se sono scritte come ore; altrimenti null;\n"
        "\"labor\": le righe sulla manodopera come scritte (es. \"manodopera: 2 operai per 5 giorni\", \"ore di manodopera 40\"), altrimenti [];\n"
        "\"warranty\": la garanzia come scritta (es. \"garanzia 2 anni su materiali e manodopera\"), altrimenti vuoto;\n"
        "\"maintenance\": le manutenzioni o i controlli periodici previsti dopo i lavori, ciascuno con la frequenza come scritta "
        "(es. \"manutenzione annuale della caldaia\", \"verifica semestrale dell'impianto di allarme\"), altrimenti [];\n"
        "\"description\": la descrizione delle attività da svolgere per chi lavora: una frase sull'oggetto e l'elenco delle "
        "lavorazioni (righe che iniziano con \"- \"), senza prezzi. Ciò che manca: vuoto o null. MAI inventare.\n"
        "\"optionals\": le voci FACOLTATIVE non comprese nel totale (\"OPTIONAL: kit luci +€250\") come [{\"description\", \"amount\"}];\n"
        "\"options\": SOLO se il documento propone SOLUZIONI ALTERNATIVE tra cui il cliente sceglie (\"soluzione 1\" / \"soluzione 2\", "
        "\"opzione A\" / \"opzione B\", \"in alternativa\"), una per soluzione, nell'ordine: [{\"name\": il nome come scritto (es. \"Soluzione 1\"), "
        "\"title\": cosa propone in poche parole, \"total\": il totale DI QUELLA soluzione, \"taxable\": il suo imponibile se scritto, "
        "\"items\": le sue voci (come sopra), \"materials_planned\": i suoi materiali (come sopra), \"activities\": le sue attività, "
        "\"optionals\": le sue voci facoltative}]. In quel caso NON sommare le soluzioni: \"total\" e \"taxable\" generali solo se il documento "
        "ha un totale unico, altrimenti null; \"items\" e \"materials_planned\" generali vuoti. Nessuna alternativa: [].\n"
        "Rispondi SOLO con JSON: {\"total\": null, \"taxable\": null, \"vat\": null, \"items\": [], \"start\": \"\", \"end\": \"\", "
        "\"validity\": \"\", \"payments\": [], \"activities\": [], \"materials\": [], \"materials_planned\": [], \"labor_hours\": null, \"labor\": [], \"warranty\": \"\", \"maintenance\": [], \"description\": \"\", \"optionals\": [], \"options\": []}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(model=MODEL, max_completion_tokens=8000, response_format={"type": "json_object"},
                                                    messages=[{"role": "system", "content": system}, {"role": "user", "content": (text or "")[:30000]}])
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    p = json.loads(m.group(0)) if m else {}

    def money(v):
        try:
            v = round(float(str(v).replace(",", ".")), 2) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None
        return v if v and v > 0 and amount_in_text(v, text) else None

    def day(v):
        try:
            d = date.fromisoformat(str(v or "")[:10])
        except ValueError:
            return ""
        return d.isoformat() if today - timedelta(days=400) <= d <= today + timedelta(days=3 * 366) else ""

    def lines(v, n=40):
        return [" ".join(str(x).split())[:200] for x in (v if isinstance(v, list) else []) if str(x or "").strip()][:n]

    warranty = " ".join(str(p.get("warranty") or "").split())[:200]
    warranty = warranty if warranty and grounded(warranty, text, 0.6) else ""
    maintenance = [{"text": x, "every_months": months_every(x)} for x in lines(p.get("maintenance"), 10) if grounded(x, text, 0.6)]
    def clean_items(rows):
        out = []
        for it in rows if isinstance(rows, list) else []:
            if isinstance(it, dict) and str(it.get("description") or "").strip():
                q = _num(it.get("qty"))
                q = q if q is not None and q > 0 and _qty_in_text(q, text) else None
                out.append({"description": " ".join(str(it["description"]).split())[:200], "qty": q,
                            "unit": unit_norm(it.get("unit")) if q is not None else "", "unit_price": money(it.get("unit_price")),
                            "amount": money(it.get("amount"))})
        return out[:60]

    def clean_optionals(rows):   # only with their amount written
        out = []
        for o in rows if isinstance(rows, list) else []:
            desc = " ".join(str((o or {}).get("description") or "").split())[:160] if isinstance(o, dict) else ""
            if desc and grounded(desc, text, 0.6):
                out.append({"description": desc, "amount": money(o.get("amount"))})
        return out[:10]

    items = clean_items(p.get("items"))
    # the alternative solutions ("soluzione 1 / 2"): each with its own total, items and materials; the client chooses one
    options = []
    for o in p.get("options") if isinstance(p.get("options"), list) else []:
        if not isinstance(o, dict):
            continue
        name = " ".join(str(o.get("name") or "").split())[:80] or f"Soluzione {len(options) + 1}"
        opt = {"name": name, "title": " ".join(str(o.get("title") or "").split())[:160], "total": money(o.get("total")),
               "taxable": money(o.get("taxable")), "items": clean_items(o.get("items")),
               "materials_planned": clean_planned_materials(o.get("materials_planned"), text), "activities": lines(o.get("activities")),
               "optionals": clean_optionals(o.get("optionals"))}
        if opt["total"] or opt["taxable"] or opt["items"] or opt["materials_planned"]:
            options.append(opt)
    options = options[:6] if len(options) >= 2 else []
    # the man-hours: as written, else the items priced in hours added up (both from the document)
    in_hours = [it["qty"] for it in items if it.get("qty") and it.get("unit") in HOUR_UNITS]
    lh = _num(p.get("labor_hours"))
    if lh is not None and not (lh > 0 and (_qty_in_text(lh, text) or (in_hours and abs(sum(in_hours) - lh) < 0.01))):
        lh = None
    if lh is None and in_hours:
        lh = round(sum(in_hours), 2)
    if options:   # nothing of one solution counted as the whole quote's
        total = money(p.get("total"))
        total = total if total and not any(abs(total - (o["total"] or 0)) < 0.01 for o in options) else None
        return {"total": total, "taxable": None, "vat": None, "items": [], "options": options, "optionals": [],
                "start": day(p.get("start")), "end": day(p.get("end")), "validity": day(p.get("validity")),
                "payments": lines(p.get("payments"), 10), "activities": lines(p.get("activities")), "materials": [],
                "materials_planned": [], "labor_hours": lh, "labor": [x for x in lines(p.get("labor"), 10) if grounded(x, text, 0.6)],
                "warranty": warranty, "warranty_months": warranty_months(warranty), "maintenance": maintenance,
                "description": str(p.get("description") or "").strip()[:4000]}
    return {"total": money(p.get("total")), "taxable": money(p.get("taxable")), "vat": money(p.get("vat")), "items": items[:60],
            "options": [], "optionals": clean_optionals(p.get("optionals")),
            "start": day(p.get("start")), "end": day(p.get("end")), "validity": day(p.get("validity")),
            "payments": lines(p.get("payments"), 10), "activities": lines(p.get("activities")), "materials": lines(p.get("materials")),
            "materials_planned": clean_planned_materials(p.get("materials_planned"), text),
            "labor_hours": lh, "labor": [x for x in lines(p.get("labor"), 10) if grounded(x, text, 0.6)],
            "warranty": warranty, "warranty_months": warranty_months(warranty), "maintenance": maintenance,
            "description": str(p.get("description") or "").strip()[:4000]}


def apply_option(d: dict, idx: int) -> dict:
    """The quote with the solution chosen: its total, items, materials, activities and optionals."""
    opts = d.get("options") or []
    if not 0 <= idx < len(opts):
        raise ValueError("no such solution")
    o = opts[idx]
    return {**d, "total": o.get("total"), "taxable": o.get("taxable"), "vat": None, "items": o.get("items") or [],
            "materials_planned": o.get("materials_planned") or [], "activities": o.get("activities") or d.get("activities") or [],
            "optionals": o.get("optionals") or [], "chosen_option": idx, "chosen_option_name": o.get("name") or f"Soluzione {idx + 1}"}


def option_line(o: dict, i: int) -> str:
    """ "1) Soluzione 1 — sbarra FAAC 615: totale 2.650 € +IVA, 8 voci · optional: kit luci asta 250 €" """
    money = (f"imponibile {_eur(o['taxable'])}" if o.get("taxable") else f"totale {_eur(o['total'])}" if o.get("total") else "totale non scritto")
    bits = [money] + ([f"{len(o['items'])} voci"] if o.get("items") else [])
    out = f"{i + 1}) {o.get('name') or f'Soluzione {i + 1}'}" + (f" — {o['title']}" if o.get("title") else "") + ": " + ", ".join(bits)
    if o.get("optionals"):
        out += " · optional: " + "; ".join(x["description"] + (f" {_eur(x['amount'])}" if x.get("amount") else "") for x in o["optionals"])
    return out


# how often, from the words (never guessed): "annuale" 12, "semestrale" 6, "ogni 3 mesi" 3, "ogni due anni" 24
_NUM_WORDS = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6, "sette": 7, "otto": 8, "nove": 9,
              "dieci": 10, "undici": 11, "dodici": 12, "diciotto": 18, "ventiquattro": 24, "trentasei": 36}
_EVERY_WORD = [(re.compile(r"\bmensil\w*", re.I), 1), (re.compile(r"\bbimestral\w*", re.I), 2), (re.compile(r"\btrimestral\w*", re.I), 3),
               (re.compile(r"\bquadrimestral\w*", re.I), 4), (re.compile(r"\bsemestral\w*", re.I), 6),
               (re.compile(r"\bbiennal\w*", re.I), 24), (re.compile(r"\btriennal\w*", re.I), 36),
               (re.compile(r"\bannual\w*|\bannuo\b|\bogni\s+anno\b|\ball'anno\b", re.I), 12)]
_EVERY_N = re.compile(r"\bogni\s+(\d{1,2}|[a-z]+)\s+(mes[ei]|ann[oi])\b", re.I)


def _n_of(w: str) -> Optional[int]:
    return int(w) if w.isdigit() else _NUM_WORDS.get(w.lower())


def months_every(text: str) -> Optional[int]:
    m = _EVERY_N.search(text or "")
    if m and _n_of(m.group(1)):
        return _n_of(m.group(1)) * (12 if m.group(2).lower().startswith("ann") else 1)
    for rx, months in _EVERY_WORD:
        if rx.search(text or ""):
            return months
    return None


_WARRANTY_N = re.compile(r"\b(\d{1,2}|[a-z]+)\s+(mes[ei]|ann[oi])\b", re.I)


def warranty_months(text: str) -> Optional[int]:
    """The warranty's length from the words only: "2 anni" 24, "24 mesi" 24, "biennale" 24."""
    m = _WARRANTY_N.search(text or "")
    if m and _n_of(m.group(1)):
        return _n_of(m.group(1)) * (12 if m.group(2).lower().startswith("ann") else 1)
    if re.search(r"\bbiennal\w*", text or "", re.I):
        return 24
    if re.search(r"\bannual\w*", text or "", re.I):
        return 12
    return None


# ---- the materials a quote foresees, against the ones the diary says were used ----
_MAT_LINE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(m2|m²|mq|m3|m³|mc|ml|mtl|mt|m|cm|mm|kg|g|lt|l|pz|cad|n°|pezzi|pezzo|nr|n\.?|sacchi|sacco|rotoli|rotolo|"
                       r"confezioni|conf|scatole|scatola|barre|barra|metri|metro|litri|litro|chili|chilo)?\.?\s+(?:di\s+)?(.+)$", re.I)
_UNIT_ALIAS = {"ml": "m", "mt": "m", "mtl": "m", "cad": "pz", "n°": "pz", "nr.": "pz", "ora": "ore", "hh": "ore", "h": "ore",
               "m²": "mq", "m2": "mq", "m³": "mc", "m3": "mc", "metri": "m", "metro": "m", "litri": "l", "litro": "l", "lt": "l",
               "pezzi": "pz", "pezzo": "pz", "nr": "pz", "n": "pz", "n.": "pz", "chili": "kg", "chilo": "kg", "sacco": "sacchi",
               "rotolo": "rotoli", "scatola": "scatole", "barra": "barre", "conf": "confezioni"}


def unit_norm(u: str) -> str:
    u = (u or "").strip().lower().rstrip(".") if u else ""
    return _UNIT_ALIAS.get(u, _UNIT_ALIAS.get(u + ".", u))


HOUR_UNITS = ("ore", "h", "hh", "ora")


def _qty_in_text(q: float, text: str) -> bool:
    """A quantity read is kept only if that number is written in the document (also as 1.200 or 1.200,00)."""
    t = (text or "").replace(" ", "").replace("\u00a0", "")
    t = re.sub(r"(?<=\d)[.'](?=\d{3}(?:\D|$))", "", t)        # thousands separators
    s = f"{q:g}"
    before, after = r"(?<!\d)(?<!\d[.,])", r"(?!\d)(?![.,]\d)"     # not part of another number
    if "." in s:   # 2.5: "2,5", "2,50", "2.5"
        return bool(re.search(rf"{before}(?:{re.escape(s)}|{re.escape(s.replace('.', ','))})0*{after}", t))
    return bool(re.search(rf"{before}{re.escape(s)}(?:[.,]0+)?{after}", t))   # 12: "12", "12,00", "n. 12" - never "120" or "1,2"


def clean_planned_materials(rows, text: str) -> list:
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        name = " ".join(str(r.get("name") or "").split()).strip(" .-•")[:120]
        if not name or not grounded(name, text, 0.6):
            continue
        q = _num(r.get("qty"))
        q = q if q is not None and q > 0 and _qty_in_text(q, text) else None
        out.append({"name": name, "qty": q, "unit": unit_norm(r.get("unit")) if q is not None else ""})
    return out[:60]


_LABOR_ITEM = re.compile(r"\b(?:manodopera|installazion\w*|montaggio|posa\s+in\s+opera|collaud\w*|trasport\w*|smaltiment\w*|"
                         r"sopralluog\w*|progettazion\w*|pratich\w*|assistenza|garanzia|manutenzion\w*|totale|sconto|iva)\b", re.I)


def planned_materials(d: dict) -> list:
    """The quote's planned materials: as read (with quantities), else from its lines ("20 m corrugato 25"),
    else its items with a quantity that are things (not hours, not installation or transport)."""
    if d.get("materials_planned"):
        return d["materials_planned"]
    if not d.get("materials"):
        from_items = [{"name": it["description"], "qty": it["qty"], "unit": it.get("unit") or ""} for it in d.get("items") or []
                      if it.get("qty") and (it.get("unit") or "") not in HOUR_UNITS and not _LABOR_ITEM.search(it.get("description") or "")]
        if from_items:
            return from_items
    out = []
    for line in d.get("materials") or []:
        m = _MAT_LINE.match(str(line))
        if m:
            out.append({"name": m.group(3).strip(" .-"), "qty": float(m.group(1).replace(",", ".")), "unit": unit_norm(m.group(2) or "")})
        elif str(line).strip():
            out.append({"name": str(line).strip(), "qty": None, "unit": ""})
    return out


def _same_material(a: str, b: str) -> bool:
    return grounded(a, b, 0.6) or grounded(b, a, 0.6)


def compare_materials(planned: list, used: list) -> dict:
    """Planned vs used (the diary's totals): per planned material the quantity used (same unit), what is
    left or over; the used ones the quote did not foresee. Nothing estimated: only the two sides written."""
    rows, taken = [], set()
    for p in planned:
        hits = [i for i, u in enumerate(used) if i not in taken and _same_material(p["name"], u["name"])]
        same_unit = [i for i in hits if unit_norm(used[i].get("unit")) == (p.get("unit") or "") or not p.get("unit")]
        taken.update(hits)
        used_qty = round(sum(float(used[i].get("qty") or 0) for i in same_unit), 2) if same_unit else 0.0
        other_units = [f"{_fmt_num(used[i].get('qty'))} {used[i].get('unit') or ''}".strip() for i in hits if i not in same_unit]
        row = {"name": p["name"], "unit": p.get("unit") or (used[same_unit[0]].get("unit") if same_unit else ""),
               "planned": p.get("qty"), "used": used_qty, "other_units": other_units, "used_names": [used[i]["name"] for i in hits]}
        if p.get("qty"):
            row["left"] = round(p["qty"] - used_qty, 2)
            row["pct"] = round(used_qty / p["qty"] * 100)
            row["status"] = "oltre" if used_qty > p["qty"] + 1e-9 else "completo" if abs(used_qty - p["qty"]) < 1e-9 else \
                "da_usare" if used_qty == 0 and not hits else "in_uso"
        else:
            row["status"] = "usato" if hits else "da_usare"
        rows.append(row)
    unplanned = [{"name": u["name"], "qty": u.get("qty"), "unit": u.get("unit") or ""} for i, u in enumerate(used) if i not in taken]
    return {"rows": rows, "unplanned": unplanned}


def spread_due_dates(n: int, start: date, end: date, add_workdays, workdays_between) -> list:
    """n steps spread over the working days from start to end, in order (the last one on the end)."""
    total = max(0, workdays_between(start, end))
    return [add_workdays(start, round(total * (i + 1) / n)) for i in range(n)]


def quote_detail_lines(d: dict, with_money: bool = False) -> list:
    """The quote's content as diary lines (read by the commessa's chat, its reports and searches)."""
    out = []
    if d.get("options") and d.get("chosen_option") is None:
        out.append("Soluzioni alternative (da scegliere): " + " | ".join(option_line(o, i) for i, o in enumerate(d["options"])))
    elif d.get("options"):
        out.append(f"Soluzione scelta: {d.get('chosen_option_name')} (alternative: "
                   + "; ".join(o.get("name") or "" for i, o in enumerate(d["options"]) if i != d["chosen_option"]) + ")")
    if d.get("optionals"):
        out.append("Optional (non compresi): " + "; ".join(x["description"] + (f" {_eur(x['amount'])}" if x.get("amount") else "") for x in d["optionals"]))
    if d.get("items"):
        out.append("Voci: " + "; ".join(i["description"] + (f" ({_eur(i['amount'])})" if with_money and i.get("amount") else "")
                                       for i in d["items"][:40]))
    if d.get("activities"):
        out.append("Attività previste: " + "; ".join(d["activities"][:30]))
    planned = planned_materials(d)
    if planned:
        out.append("Materiali previsti: " + "; ".join(" ".join(x for x in (_fmt_num(m["qty"]) if m.get("qty") else "", m.get("unit") or "", m["name"]) if x)
                                                     for m in planned[:30]))
    dates = [x for x in (f"inizio {d['start']}" if d.get("start") else "", f"fine {d['end']}" if d.get("end") else "") if x]
    if dates:
        out.append("Date: " + ", ".join(dates))
    if d.get("payments"):
        out.append("Pagamenti: " + "; ".join(d["payments"]))
    if d.get("labor_hours"):
        out.append(f"Ore uomo previste: {_fmt_num(d['labor_hours'])} h")
    if d.get("labor"):
        out.append("Manodopera: " + "; ".join(d["labor"]))
    if d.get("warranty"):
        out.append(f"Garanzia: {d['warranty']}")
    if d.get("maintenance"):
        out.append("Manutenzione prevista: " + "; ".join(m["text"] for m in d["maintenance"]))
    return out


# ---- the survey, organized (AUT-SOP-02) ----
SURVEY_KEYS = [("date_participants", "Data e partecipanti"), ("state", "Stato di fatto e misure"), ("requests", "Lavori richiesti dal cliente"),
               ("issues", "Criticità e vincoli"), ("materials", "Materiali ipotizzati")]


async def survey_summary(entries: list, commessa: dict, user_id: Optional[str] = None, channel: str = "web") -> dict:
    """The survey's notes (text, transcriptions of handwritten notes, documents) -> the section in
    order: {date_participants, state, requests, issues, materials} - only what is written."""
    material = "\n\n".join(f"[{e.get('date') or ''} · {e.get('author') or ''}] {e.get('text') or ''}" for e in entries)[:24000]
    system = (
        "Sei l'assistente di un'impresa artigiana. Ricevi le note di SOPRALLUOGO della commessa "
        f"«{commessa.get('title')}» del cliente {commessa.get('client_name')} (testi, trascrizioni di appunti, documenti). "
        "Riorganizzale SENZA aggiungere nulla in queste parti, testo breve o elenchi con \"- \":\n"
        "\"date_participants\": data/e del sopralluogo e chi era presente; \"state\": stato di fatto e misure; "
        "\"requests\": lavori richiesti dal cliente; \"issues\": criticità e vincoli; \"materials\": materiali ipotizzati. "
        "Una parte senza informazioni: stringa vuota. MAI inventare misure, nomi o date.\n"
        "Rispondi SOLO con JSON: {\"date_participants\": \"\", \"state\": \"\", \"requests\": \"\", \"issues\": \"\", \"materials\": \"\"}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(model=MODEL, max_completion_tokens=2000, response_format={"type": "json_object"},
                                                    messages=[{"role": "system", "content": system}, {"role": "user", "content": material}])
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    p = json.loads(m.group(0)) if m else {}
    return {k: str(p.get(k) or "").strip()[:3000] for k, _label in SURVEY_KEYS}


_SURVEY_SAID = re.compile(r"\bsopralluog\w*|\brilievo\b|\brilievi\b|\bmisure\s+prese\b", re.I)


def survey_said(text: str) -> bool:
    return bool(_SURVEY_SAID.search(text or ""))


# ---- the quote's outcome, said (RF-PRE-03): "il preventivo dei Rossi è stato accettato",
# "preventivo bagno perso per il prezzo", "il cliente ci pensa ancora" ----
_QUOTE = re.compile(r"\bpreventiv\w*|\bofferta\b", re.I)
_ACCEPTED = re.compile(r"\b(?:accettat\w*|approvat\w*|confermat\w*|firmat\w*|ok\s+dal\s+cliente|ha\s+detto\s+di\s+s[iì])\b", re.I)
_LOST = re.compile(r"\b(?:pers[oa]|rifiutat\w*|non\s+(?:è\s+stato\s+|e'\s+stato\s+)?accettat\w*|non\s+(?:lo\s+)?accetta|"
                   r"ha\s+rinunciat\w*|rinuncia|scartat\w*|non\s+se\s+ne\s+fa\s+(?:più\s+)?niente)\b", re.I)
_WAITING = re.compile(r"\b(?:in\s+attesa|ci\s+(?:sta\s+)?pens\w*|deve\s+(?:ancora\s+)?decidere|non\s+ha\s+ancora\s+deciso)\b", re.I)
_LOST_CATS = [("prezzo", re.compile(r"\b(?:prezz\w*|car[oaie]\b|costos\w*|costa\s+troppo|budget|economic\w*)", re.I)),
              ("tempi", re.compile(r"\b(?:temp[oi]|tardi|lung[hi]+|data|urgen\w*|attes[ae])\b", re.I)),
              ("concorrente", re.compile(r"\b(?:concorren\w*|altra\s+ditta|altr[oaie]\s+(?:impres\w*|artigian\w*|elettricist\w*|idraulic\w*))", re.I)),
              ("rinuncia_cliente", re.compile(r"\b(?:rinunci\w*|non\s+(?:lo\s+)?fa\s+più|non\s+se\s+ne\s+fa)", re.I))]


def quote_outcome_said(text: str) -> Optional[dict]:
    """-> {"outcome": accettato | perso | in_attesa, "category": prezzo|tempi|concorrente|rinuncia_cliente|altro|"",
    "reason": the words after "per/perché"} or None (not about a quote's outcome)."""
    t = text or ""
    if not _QUOTE.search(t):
        return None
    if _LOST.search(t):
        cat = next((k for k, rx in _LOST_CATS if rx.search(t)), "")
        m = re.search(r"\b(?:per(?:ché|che)?|motivo:?)\s+(.{3,200})$", t, re.I)
        return {"outcome": "perso", "category": cat, "reason": (m.group(1).strip(" .") if m else "")}
    if _ACCEPTED.search(t):
        return {"outcome": "accettato", "category": "", "reason": ""}
    if _WAITING.search(t):
        return {"outcome": "in_attesa", "category": "", "reason": ""}
    return None


# ---- planned activities (specifica 3.5, RF-SVO-01, AUT-SVO-01) ----
ITEM_CATEGORIES = ("materiali", "attrezzi", "dpi", "documenti")
_CAT_WORDS = [("dpi", re.compile(r"\b(?:dpi|casco|caschi|guant\w+|scarpe\s+antinfortunistiche|imbrago|imbraghi|occhiali|mascherin\w+|cuffi\w+|giubbin\w+)\b", re.I)),
              ("attrezzi", re.compile(r"\b(?:flex|smerigliatric\w+|trapan\w+|avvitator\w+|scal[ae]\b|ponteggi\w*|martell\w+|pinz\w+|chiav[ei]\b|livell\w+|"
                                      r"betoniera|demolitor\w+|tassellator\w+|sega|seghetto|cacciavit\w+|metro\b|attrezz\w+|utensil\w+|carotatric\w+)\b", re.I)),
              ("documenti", re.compile(r"\b(?:document\w+|dico|certificat\w+|progett\w+|disegn\w+|planimetri\w+|schem\w+|permess\w+|modul\w+|bolla|bolle|fattur\w+)\b", re.I))]


def item_category(text: str) -> str:
    """The category of something to bring (Materiali / Attrezzi / DPI / Documenti)."""
    for cat, rx in _CAT_WORDS:
        if rx.search(text or ""):
            return cat
    return "materiali"


_PLAN_SAID = re.compile(r"^\s*(?:pianifica|programma|organizza|metti\s+in\s+programma|pianificare)\b", re.I)
_DONE_WORDS = re.compile(r"\b(?:fatt[oaie]|finit[oaie]|terminat[oaie]|completat[oaie]|concluso|conclusa|smontat\w*|montat\w*|posat\w*|"
                         r"installat\w*|rifatt\w*|demolit\w*|sostituit\w*|eseguit\w*|realizzat\w*|chius[oa])\b", re.I)


def plan_said(text: str) -> bool:
    return bool(_PLAN_SAID.match(text or ""))


def activity_done(text: str, descriptions: list) -> list:
    """The planned activities a note says were carried out ("smontati i sanitari" -> "smontaggio
    sanitari"): a word of doing and most of the activity's words. -> indexes."""
    if not _DONE_WORDS.search(text or ""):
        return []
    said = set(_words(text))
    out = []
    for i, d in enumerate(descriptions):
        words = _words(d)
        if words and sum(1 for w in words if _said(w, said) or any(w[:5] == x[:5] for x in said if len(x) >= 5)) / len(words) >= 0.5:
            out.append(i)
    return out


async def read_activity(text: str, people: list, user_id: Optional[str] = None, channel: str = "web") -> dict:
    """"Pianifica smontaggio sanitari il 12/11 alle 8 con Gino e Marco, portare i flessibili" ->
    {"description", "date", "start", "end", "assignees": [names among `people`], "items": [str], "info"}."""
    today = today_local()
    system = (
        "Sei l'assistente di un'impresa artigiana. Il messaggio PIANIFICA un'attività di cantiere. "
        f"Oggi è {IT_WEEKDAYS[today.weekday()]} {today.isoformat()}. Persone che possono essere assegnate: {', '.join(people) or 'nessuna'}.\n"
        "Estrai SOLO ciò che è scritto: \"description\": l'attività in breve; \"date\": il giorno (YYYY-MM-DD; \"domani\", \"il 12\", \"giovedì\"); "
        "\"start\" e \"end\": orari HH:MM se scritti; \"assignees\": i nomi delle persone assegnate SCELTI dall'elenco; "
        "\"items\": materiale, attrezzi, DPI o documenti da portare, uno per elemento; \"info\": altre informazioni utili. MAI inventare.\n"
        "Rispondi SOLO con JSON: {\"description\": \"\", \"date\": \"\", \"start\": \"\", \"end\": \"\", \"assignees\": [], \"items\": [], \"info\": \"\"}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(model=MODEL, max_completion_tokens=800, response_format={"type": "json_object"},
                                                    messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    p = json.loads(m.group(0)) if m else {}
    try:
        d = date.fromisoformat(str(p.get("date") or "")[:10])
        day = d.isoformat() if today - timedelta(days=1) <= d <= today + timedelta(days=366) else ""
    except ValueError:
        day = ""
    def hhmm(v):
        mm = re.fullmatch(r"(\d{1,2})[:.](\d{2})", str(v or "").strip())
        return f"{int(mm.group(1)):02d}:{mm.group(2)}" if mm and int(mm.group(1)) < 24 and int(mm.group(2)) < 60 and _clock_said(f"{int(mm.group(1)):02d}:{mm.group(2)}", text) else ""
    names = {n.lower(): n for n in people}
    return {"description": " ".join(str(p.get("description") or "").split())[:200], "date": day, "start": hhmm(p.get("start")), "end": hhmm(p.get("end")),
            "assignees": [names[str(x).lower()] for x in (p.get("assignees") or []) if str(x).lower() in names],
            "items": [" ".join(str(x).split())[:160] for x in (p.get("items") or []) if str(x or "").strip()][:20],
            "info": " ".join(str(p.get("info") or "").split())[:500]}


def _mat_key(m: dict) -> tuple:
    return (" ".join((m.get("name") or "").lower().split()), (m.get("unit") or "").lower().strip("."))


# ---- the phase of the commessa the hours were worked in: the state it was in that day (survey, quote,
# works, after the delivery), or what the note says ("2 ore per preparare il preventivo"), or set by hand
WORK_PHASES = [("sopralluogo", "Sopralluogo"), ("preventivo", "Preventivo"), ("lavorazione", "Lavorazione"), ("post", "Dopo la consegna")]
PHASE_LABEL = dict(WORK_PHASES)
_STATO_PHASE = {"nuova": "sopralluogo", "sopralluogo": "sopralluogo", "preventivo inviato": "preventivo", "persa": "preventivo",
                "in lavorazione": "lavorazione", "sospesa": "lavorazione", "completata": "post", "archiviata": "post"}
_PHASE_WORDS = [(re.compile(r"\b(?:per|fare|fatto|preparar\w*|preparat\w*|scriver\w*|scritto|stesura|redatto|redigere|calcolar\w*|calcolat\w*|"
                            r"computo)\s+(?:il\s+|del\s+|un\s+|al\s+|lo\s+)?(?:nuovo\s+)?preventiv", re.I), "preventivo"),
                (re.compile(r"\b(?:fatto|per|al|il|un|nel|durante\s+il)\s+sopralluog\w*|\bsopralluog\w*\s+(?:dal|dai|da|presso|fatto)", re.I), "sopralluogo")]


def phase_of_stato(stato: str) -> str:
    s = " ".join((stato or "").lower().replace("_", " ").split())
    s = {"preventivo": "preventivo inviato", "in corso": "in lavorazione", "chiusa": "completata"}.get(s, s) or "nuova"
    return _STATO_PHASE.get(s, "lavorazione")


def phase_from_words(text: str) -> Optional[str]:
    for rx, ph in _PHASE_WORDS:
        if rx.search(text or ""):
            return ph
    return None


def totals(logs: list) -> dict:
    """Hours (total, per person, per phase of the commessa), materials summed by name+unit, problems with their day."""
    by_person, mats, problems, pending = {}, {}, [], []
    by_phase, by_phase_person = {}, {}
    for lg in logs:
        for h in lg.get("hours") or []:
            by_person[h["who"]] = round(by_person.get(h["who"], 0) + float(h.get("hours") or 0), 2)
            ph = lg.get("phase") or "lavorazione"
            by_phase[ph] = round(by_phase.get(ph, 0) + float(h.get("hours") or 0), 2)
            pp = by_phase_person.setdefault(ph, {})
            pp[h["who"]] = round(pp.get(h["who"], 0) + float(h.get("hours") or 0), 2)
        for h in lg.get("hours_pending") or []:   # written in a note by a collaborator: apart until approved
            pending.append({"log_id": lg.get("id"), "date": lg.get("date"), "who": h["who"], "hours": float(h.get("hours") or 0),
                            "review": lg.get("hours_review") or {}})
        for m in lg.get("materials") or []:
            k = _mat_key(m)
            cur = mats.setdefault(k, {"name": m["name"], "unit": m.get("unit") or "", "qty": None})
            if m.get("qty") is not None:
                cur["qty"] = round((cur["qty"] or 0) + float(m["qty"]), 3)
        for i, p in enumerate(lg.get("problems") or []):
            st = (lg.get("problem_status") or {}).get(str(i)) or {}
            problems.append({"date": lg.get("date"), "text": p, "log_id": lg.get("id"), "idx": i,
                             "status": st.get("status") or "aperta", "severity": (lg.get("problem_severity") or {}).get(str(i)) or "media",
                             "resolved_at": st.get("at"), "resolved_by": st.get("by"), "author": lg.get("author_name")})
    pending_by = {}
    for x in pending:
        pending_by[x["who"]] = round(pending_by.get(x["who"], 0) + x["hours"], 2)
    return {"hours_total": round(sum(by_person.values()), 2), "by_person": by_person,
            "by_phase": {k: by_phase[k] for k, _l in WORK_PHASES if by_phase.get(k)},
            "by_phase_person": {k: by_phase_person[k] for k, _l in WORK_PHASES if k in by_phase_person},
            "pending": pending, "pending_by_person": pending_by, "hours_pending_total": round(sum(pending_by.values()), 2),
            "materials": sorted(mats.values(), key=lambda x: x["name"].lower()), "problems": problems,
            "entries": sum(1 for lg in logs if not lg.get("kind")),   # state changes are not entries
            "first_day": min((lg.get("date") for lg in logs if lg.get("date")), default=None),
            "last_day": max((lg.get("date") for lg in logs if lg.get("date")), default=None)}


# ---- extra works: done on the site, not in the quote (to be approved and billed) ----
EXTRA_MIN_WORDS = 4


def extra_candidate(text: str) -> bool:
    """A note worth checking: some words of work, not a question."""
    t = " ".join((text or "").split())
    return len(_words(t)) >= EXTRA_MIN_WORDS and not is_plain_question(t)


def covered_by(work: str, scope: list) -> Optional[str]:
    """The quote's line that already holds this work (most of its words in it), or None."""
    for line in scope or []:
        if grounded(work, line, 0.75):
            return line
    return None


async def find_extras(note: str, scope: list, commessa: dict, user_id: Optional[str] = None, channel: str = "web") -> list:
    """The works DONE in a diary note that neither the quote's items and activities nor the
    commessa's description cover. Conservative (in doubt: not extra); each work in the note's
    own words (grounded), never one already in the scope. -> [{"work", "why"}]"""
    if not extra_candidate(note) or not scope:
        return []
    system = (
        "Sei l'assistente di un'impresa artigiana. Ricevi (1) le voci e le attività del PREVENTIVO e la descrizione dei lavori "
        f"della commessa «{commessa.get('title')}» e (2) una NOTA del diario di cantiere.\n"
        "Trova nella nota i LAVORI ESEGUITI che NON rientrano in nessuna voce o attività del preventivo né nella descrizione: lavori "
        "aggiuntivi, varianti chieste dal cliente, imprevisti risolti con lavoro in più.\n"
        "Regole:\n- solo lavori GIÀ FATTI (non da fare, non problemi, non materiali da comprare o portare, non presenze);\n"
        "- se un lavoro può rientrare in una voce, anche detta con altre parole o come parte di essa, NON è extra;\n"
        "- nel dubbio NON è extra;\n- \"work\": il lavoro con le parole della nota, breve; \"why\": in una frase perché non rientra.\n"
        "Rispondi SOLO con JSON: {\"extras\": [{\"work\": \"...\", \"why\": \"...\"}]}"
    )
    user = "PREVENTIVO E DESCRIZIONE:\n" + "\n".join(f"- {x}" for x in scope[:120]) + f"\n\nNOTA DEL DIARIO:\n{note[:4000]}"
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(model=MODEL, max_completion_tokens=800, response_format={"type": "json_object"},
                                                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    p = json.loads(m.group(0)) if m else {}
    out = []
    for e in p.get("extras") or []:
        if not isinstance(e, dict):
            continue
        work = " ".join(str(e.get("work") or "").split()).strip(" .-•")[:200]
        if not work or not grounded(work, note, 0.6) or covered_by(work, scope) or any(grounded(work, o["work"], 0.8) for o in out):
            continue
        out.append({"work": work[0].upper() + work[1:], "why": " ".join(str(e.get("why") or "").split())[:200]})
    return out[:5]


# ---- quotes from history: the commesse like this one, and what they really cost ----
_SIM_STOP = set("""della delle dello degli nella nelle negli sulla sulle con per tra fra dal dai dalla anche come lavori lavoro
commessa cliente casa via piano rifacimento""".split())


def _sim_words(text: str) -> set:
    return {w for w in _words(text) if len(w) >= 4 and w not in _SIM_STOP}


def similar_by_words(target: str, candidates: list, n: int = 6) -> list:
    """The candidates sharing most meaningful words with the target (no model). -> ids"""
    tw = _sim_words(target)
    if not tw:
        return []
    scored = []
    for c in candidates:
        cw = _sim_words(c.get("text") or "")
        common = {w for w in tw if _said(w, cw)}
        score = len(common) / len(tw)
        if score >= 0.2:
            scored.append((score, c["id"]))
    return [i for _s, i in sorted(scored, key=lambda x: -x[0])[:n]]


async def pick_similar(target: str, candidates: list, user_id: Optional[str] = None, channel: str = "web") -> list:
    """The candidates that are the same kind of work as the target (same type of job, comparable
    size), chosen by the model among the given ones only. -> ids (at most 8)"""
    if not candidates or not (target or "").strip():
        return []
    system = (
        "Sei l'assistente di un'impresa artigiana. Ricevi una COMMESSA NUOVA e l'elenco delle commesse passate dell'impresa "
        "(id: descrizione). Scegli solo quelle che sono lo STESSO TIPO DI LAVORO (es. rifacimento bagno con rifacimento bagno, "
        "impianto elettrico di un appartamento con impianto elettrico di un appartamento) e di dimensione paragonabile, se si capisce. "
        "Nel dubbio non sceglierla. Usa SOLO gli id dell'elenco. Rispondi SOLO con JSON: {\"ids\": [\"...\"]}"
    )
    user = f"COMMESSA NUOVA:\n{target[:3000]}\n\nCOMMESSE PASSATE:\n" + "\n".join(f"{c['id']}: {(c.get('text') or '')[:400]}" for c in candidates[:120])
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(model=MODEL, max_completion_tokens=500, response_format={"type": "json_object"},
                                                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    p = json.loads(m.group(0)) if m else {}
    valid = {c["id"] for c in candidates}
    return list(dict.fromkeys(str(i) for i in p.get("ids") or [] if str(i) in valid))[:8]


def median(xs: list) -> Optional[float]:
    xs = sorted(float(x) for x in xs if x is not None)
    if not xs:
        return None
    k = len(xs) // 2
    return round(xs[k] if len(xs) % 2 else (xs[k - 1] + xs[k]) / 2, 2)


def forecast(budget: Optional[float], cost_now: float, progress: Optional[float], hist_cost: Optional[float] = None) -> Optional[dict]:
    """The cost and margin at the end: today's cost / the progress (from 15% on), else what the
    similar commesse cost (never less than spent). -> {"cost", "margin", "margin_pct", "basis"} or None"""
    if not budget:
        return None
    if progress is not None and progress >= 0.999:
        cost, basis = cost_now, "lavori conclusi"
    elif progress is not None and progress >= 0.15 and cost_now > 0:
        cost, basis = cost_now / progress, "andamento"
    elif hist_cost:
        cost, basis = max(cost_now, hist_cost), "storico"
    else:
        return None
    cost = round(cost, 2)
    margin = round(float(budget) - cost, 2)
    return {"cost": cost, "margin": margin, "margin_pct": round(margin / float(budget) * 100, 1), "basis": basis}


# ---- costs and margin ----
# Hours x the person's hourly cost (or the default one), materials x their unit price, plus
# the other costs entered by hand (scaffolding hire, disposal...), against the quote. The rates
# and prices live on the Clienti list (the same for every commessa), the quote and the other
# costs on the commessa. Anything without a price is counted apart, never guessed.

def price_key(name: str, unit: str = "") -> str:
    return "|".join(_mat_key({"name": name, "unit": unit}))


def economics(logs: list, rates: Optional[dict] = None, default_rate: Optional[float] = None,
              prices: Optional[dict] = None, extras: Optional[list] = None, budget: Optional[float] = None) -> dict:
    tot = totals(logs)
    rates = {k.lower(): float(v) for k, v in (rates or {}).items() if v is not None}
    labor, unpriced_hours = [], 0.0
    for who, h in sorted(tot["by_person"].items(), key=lambda x: x[0].lower()):
        rate = rates.get(who.lower(), default_rate)
        cost = round(h * rate, 2) if rate is not None else None
        if cost is None:
            unpriced_hours += h
        labor.append({"who": who, "hours": h, "rate": rate, "own_rate": who.lower() in rates, "cost": cost})
    paid = {}   # what the notes say a material cost ("interruttore 50 A, 50 €"): that, not the price list
    for lg in logs:
        for m in lg.get("materials") or []:
            if m.get("paid") is not None:
                k = price_key(m["name"], m.get("unit") or "")
                q, a = paid.get(k, (0.0, 0.0))
                paid[k] = (q + float(m.get("qty") or 0), a + float(m["paid"]))
    mats, unpriced_mats = [], []
    for m in tot["materials"]:
        key = price_key(m["name"], m.get("unit") or "")
        p = (prices or {}).get(key)
        price = p.get("price") if isinstance(p, dict) else p
        if key in paid:
            pq, pa = paid[key]
            rest = max(0.0, float(m.get("qty") or 0) - pq)
            cost = round(pa + (rest * float(price) if rest and price is not None else 0), 2)
            if rest and price is None:
                unpriced_mats.append(m["name"])
            mats.append({**m, "key": key, "price": price, "cost": cost, "paid": round(pa, 2)})
            continue
        cost = round(m["qty"] * float(price), 2) if (price is not None and m.get("qty") is not None) else None
        if cost is None:
            unpriced_mats.append(m["name"])
        mats.append({**m, "key": key, "price": price, "cost": cost})
    extras = [x for x in (extras or []) if x.get("amount") is not None]
    labor_by_phase = []   # what each phase cost in labour (the survey, the quote, the works, after the delivery)
    for ph, label in WORK_PHASES:
        people = tot["by_phase_person"].get(ph) or {}
        if not people:
            continue
        hrs = round(sum(people.values()), 2)
        costs = [round(h * rates.get(who.lower(), default_rate), 2) if rates.get(who.lower(), default_rate) is not None else None
                 for who, h in people.items()]
        labor_by_phase.append({"phase": ph, "label": label, "hours": hrs, "cost": round(sum(c for c in costs if c is not None), 2),
                               "complete": all(c is not None for c in costs)})
    labor_total = round(sum(x["cost"] for x in labor if x["cost"] is not None), 2)
    materials_total = round(sum(x["cost"] for x in mats if x["cost"] is not None), 2)
    extras_total = round(sum(float(x["amount"]) for x in extras), 2)
    cost_total = round(labor_total + materials_total + extras_total, 2)
    out = {"labor": labor, "labor_by_phase": labor_by_phase, "materials": mats, "extras": extras, "labor_total": labor_total, "materials_total": materials_total,
           "extras_total": extras_total, "cost_total": cost_total, "budget": budget, "margin": None, "used_pct": None,
           "unpriced_hours": round(unpriced_hours, 2), "unpriced_materials": unpriced_mats,
           "complete": not unpriced_hours and not unpriced_mats}
    if budget:
        out["margin"] = round(float(budget) - cost_total, 2)
        out["used_pct"] = round(cost_total / float(budget) * 100, 1)
    return out


def expenses_on_materials(materials: list, expenses: list) -> tuple:
    """ "usato un interruttore da 50 A, costo 50 €": the 50 € is what that material cost, kept on it
    ("paid"), not an expense too (it would be counted twice). -> (materials, the other expenses)"""
    mats = [dict(m) for m in materials or []]
    left = []
    for x in expenses or []:
        i = next((i for i, m in enumerate(mats) if m.get("paid") is None and _same_material(m["name"], x["description"])), None)
        if i is None:
            left.append(x)
            continue
        mats[i]["paid"] = x["amount"]
        if x.get("supplier"):
            mats[i]["supplier"] = x["supplier"]
    return mats, left


def clean_expenses(rows, raw: str) -> list:
    """The expenses of a note: only with an amount written in it (never guessed)."""
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        desc = " ".join(str(r.get("description") or "").split())[:120]
        try:
            amount = round(float(str(r.get("amount")).replace(",", ".")), 2)
        except (TypeError, ValueError):
            continue
        if not desc or amount <= 0 or not amount_in_text(amount, raw):
            continue
        out.append({"description": desc, "amount": amount, "supplier": " ".join(str(r.get("supplier") or "").split())[:120]})
    return out


_SOLVED = re.compile(r"\b(?:risolt\w*|sistemat\w*|riparat\w*|aggiustat\w*|sbloccat\w*|ripres\w*|(?:è|e'|sono)\s+arrivat\w*|"
                     r"arrivat\w*\s+(?:il|la|i|le|lo|gli)\b|consegnat\w*|non\s+(?:c'è|ce)\s+più|tutto\s+ok|a\s+posto|risolve)", re.I)


def problems_resolved(text: str, open_problems: list) -> list:
    """The open problems a note says are solved ("risolto il problema del miscelatore", "è
    arrivato il materiale"): a word of solution and most of the problem's words. -> indexes."""
    if not _SOLVED.search(text or ""):
        return []
    said = set(_words(text))
    out = []
    for i, p in enumerate(open_problems):
        words = [w for w in _words(p) if w not in {"manca", "mancano", "problema", "problemi", "non", "arrivato", "arrivata"}]
        if words and sum(1 for w in words if _said(w, said)) / len(words) >= 0.5:
            out.append(i)
    return out


def _eur(x: Optional[float]) -> str:
    if x is None:
        return "—"
    s = f"{abs(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if x < 0 else "") + "€ " + (s[:-3] if s.endswith(",00") else s)


def economics_line(e: dict) -> str:
    """One line for the AI answers and the weekly summary."""
    parts = [f"costi {_eur(e['cost_total'])} (manodopera {_eur(e['labor_total'])}, materiali {_eur(e['materials_total'])}"
             + (f", altre spese {_eur(e['extras_total'])}" if e["extras_total"] else "") + ")"]
    if len(e.get("labor_by_phase") or []) > 1:
        parts.append("manodopera per fase: " + ", ".join(f"{x['label']} {_fmt_num(x['hours'])} h {_eur(x['cost'])}" for x in e["labor_by_phase"]))
    if e.get("budget"):
        parts.append(f"preventivo {_eur(e['budget'])}, margine {_eur(e['margin'])} ({e['used_pct']:.0f}% del preventivo speso)")
    if not e["complete"]:
        miss = []
        if e["unpriced_hours"]:
            miss.append(f"{_fmt_num(e['unpriced_hours'])} h senza tariffa")
        if e["unpriced_materials"]:
            n = len(e["unpriced_materials"])
            miss.append(f"{n} material{'e' if n == 1 else 'i'} senza prezzo")
        parts.append("non conteggiati: " + ", ".join(miss))
    return "; ".join(parts)


def hours_line(hours: list) -> str:
    if not hours:
        return ""
    tot = sum(h["hours"] for h in hours)
    parts = ", ".join(f"{h['who']} {_fmt_num(h['hours'])} h" for h in hours)
    return parts if len(hours) == 1 else f"{parts} (totale {_fmt_num(tot)} h)"


def materials_line(materials: list) -> str:
    return ", ".join(" ".join(x for x in (_fmt_num(m.get("qty")), m.get("unit") or "", m["name"]) if x).strip()
                     + (f" ({_eur(m['paid'])})" if m.get("paid") is not None else "") for m in materials)


def unplanned_materials(materials: list, planned: list) -> list:
    """The materials of a note the quote didn't foresee (by name, like the plan's comparison)."""
    return [m for m in materials or [] if not any(_same_material(p["name"], m["name"]) for p in planned or [])]


def _ctx_line(lg: dict) -> str:
    who = lg.get("author_name") or ""
    if lg.get("kind"):   # a change of state, a report made
        return f"- {lg.get('date')} · {lg.get('text')}"
    return (f"- {lg.get('date')} · {who}: {search_text(lg)}" + (f" ({len(lg['photos'])} foto)" if lg.get("photos") else "")
            + (f" [fase: {PHASE_LABEL.get(lg['phase'], lg['phase'])}]" if lg.get("phase") and lg.get("hours") else ""))


async def answer(commessa: dict, logs: list, reports: list, question: str, history: list,
                 user_id: Optional[str] = None, channel: str = "web") -> dict:
    """The commessa's chat: an answer from its card, diary and reports only. -> {"answer",
    "is_entry": true when the message is not a question but something done to write down}"""
    tot = totals(logs)
    per = ", ".join(f"{k} {_fmt_num(v)} h" for k, v in tot["by_person"].items())
    card = "\n".join(x for x in [
        f"Commessa: {commessa.get('title')}", f"Cliente: {commessa.get('client_name')}",
        f"Telefono cliente: {commessa.get('client_phone')}" if commessa.get("client_phone") else "",
        f"Email cliente: {commessa.get('client_email')}" if commessa.get("client_email") else "",
        f"Indirizzo cantiere: {commessa.get('address')}" if commessa.get("address") else "",
        f"Stato: {commessa.get('stato')}", f"Inizio: {commessa.get('data_inizio')}" if commessa.get("data_inizio") else "",
        f"Fine: {commessa.get('data_fine')}" if commessa.get("data_fine") else "",
        f"Descrizione: {commessa.get('descrizione')}" if commessa.get("descrizione") else "",
        f"Economia: {commessa.get('economics_line')}" if commessa.get("economics_line") else "",
        f"Milestone: {commessa.get('milestones_line')}" if commessa.get("milestones_line") else "",
        f"Contatti utili: {commessa.get('contacts_line')}" if commessa.get("contacts_line") else "",
        f"Attività da fare (To Do): {commessa.get('todos_line')}" if commessa.get("todos_line") else "",
    ] if x)
    pend = ", ".join(f"{k} {_fmt_num(v)} h" for k, v in tot["pending_by_person"].items())
    totals_s = (f"Voci di diario: {tot['entries']}. Ore totali: {_fmt_num(tot['hours_total'])} h" + (f" ({per})" if per else "")
                + (f". Ore per fase della commessa: " + ", ".join(f"{PHASE_LABEL[k]} {_fmt_num(v)} h" for k, v in tot["by_phase"].items())
                   if tot.get("by_phase") else "")
                + (f". Ore da approvare, NON comprese nel totale: {_fmt_num(tot['hours_pending_total'])} h ({pend})" if pend else "")
                + ". Materiali: " + (materials_line(tot["materials"]) or "nessuno") + ".")
    diary = "\n".join(_ctx_line(lg) for lg in logs) or "(nessuna voce)"
    reps = []
    for r in reports:
        filled = "; ".join(f"{f}: {v}" for sec in r.get("sections") or [] for f, v in sec["fields"].items() if v)
        reps.append(f"- {r.get('template_name')} del {(r.get('created_at') or '')[:10]}: {filled[:2500]}")
    today = today_local()
    system = (
        "Sei l'assistente di un'impresa artigiana e rispondi su UNA commessa, usando SOLO i dati qui sotto (scheda, "
        "diario, report). Se un dato non c'è, dillo chiaramente: non inventare ore, materiali, date o importi. Le ore \"da "
        "approvare\" sono scritte da un collaboratore in una nota e non sono ancora conteggiate: tienile separate e dillo. Fai i conti "
        "quando servono (ore per persona, per periodo, materiali sommati). Risposte brevi e concrete, in italiano. "
        f"Oggi è {IT_WEEKDAYS[today.weekday()]} {today.isoformat()}.\n\n"
        f"SCHEDA\n{card}\n\nTOTALI\n{totals_s}\n\nDIARIO (dal più vecchio)\n{diary}\n\n"
        f"REPORT\n{chr(10).join(reps) or '(nessuno)'}\n\n"
        "Se il messaggio dell'utente NON è una domanda ma il racconto di lavoro fatto da registrare (es. 'oggi posati 10 "
        "metri di tubo'), rispondi brevemente che puoi salvarlo nel diario e metti is_entry a true.\n"
        "Rispondi SOLO con JSON: {\"answer\": \"...\", \"is_entry\": false}"
    )
    msgs = [{"role": "system", "content": system}]
    for h in history or []:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            msgs.append({"role": h["role"], "content": str(h["content"])[:2000]})
    msgs.append({"role": "user", "content": question})
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(model=MODEL, max_completion_tokens=1200,
                                                    response_format={"type": "json_object"}, messages=msgs)
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    parsed = json.loads(m.group(0)) if m else {}
    return {"answer": str(parsed.get("answer") or "Non ho trovato la risposta nel diario di questa commessa.").strip(),
            "is_entry": bool(parsed.get("is_entry"))}


def search_text(log: dict) -> str:
    """One line with everything a question may be about (for Cerca)."""
    bits = [log.get("text") or ""]
    if log.get("hours"):
        bits.append("Ore: " + hours_line(log["hours"]) + ".")
    if log.get("hours_pending"):
        bits.append("Ore da approvare (scritte nella nota, non ancora conteggiate): " + hours_line(log["hours_pending"]) + ".")
    if log.get("hours_replaced_by"):
        bits.append("Ore sostituite da una correzione approvata.")
    if log.get("materials"):
        bits.append("Materiali: " + materials_line(log["materials"]) + ".")
    if log.get("problems"):
        bits.append("Problemi: " + "; ".join(log["problems"]) + ".")
    return " ".join(b for b in bits if b)
