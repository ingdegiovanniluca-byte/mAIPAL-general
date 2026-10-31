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
        "MAI inventare: ogni informazione deve essere scritta dall'utente.\n"
        "Rispondi SOLO con JSON: {\"kind\": \"nota|domanda|non_chiara\", \"doubt\": \"\", \"date\": \"\", \"text\": \"\", "
        "\"hours\": [], \"materials\": [], \"problems\": [], \"times\": {\"start\": null, \"end\": null}, "
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
        "client": str(parsed.get("client") or "").strip(),
        "commessa": str(parsed.get("commessa") or "").strip(),
    }


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


def _mat_key(m: dict) -> tuple:
    return (" ".join((m.get("name") or "").lower().split()), (m.get("unit") or "").lower().strip("."))


def totals(logs: list) -> dict:
    """Hours (total and per person), materials summed by name+unit, problems with their day."""
    by_person, mats, problems, pending = {}, {}, [], []
    for lg in logs:
        for h in lg.get("hours") or []:
            by_person[h["who"]] = round(by_person.get(h["who"], 0) + float(h.get("hours") or 0), 2)
        for h in lg.get("hours_pending") or []:   # written in a note by a collaborator: apart until approved
            pending.append({"log_id": lg.get("id"), "date": lg.get("date"), "who": h["who"], "hours": float(h.get("hours") or 0),
                            "review": lg.get("hours_review") or {}})
        for m in lg.get("materials") or []:
            k = _mat_key(m)
            cur = mats.setdefault(k, {"name": m["name"], "unit": m.get("unit") or "", "qty": None})
            if m.get("qty") is not None:
                cur["qty"] = round((cur["qty"] or 0) + float(m["qty"]), 3)
        for p in lg.get("problems") or []:
            problems.append({"date": lg.get("date"), "text": p, "log_id": lg.get("id")})
    pending_by = {}
    for x in pending:
        pending_by[x["who"]] = round(pending_by.get(x["who"], 0) + x["hours"], 2)
    return {"hours_total": round(sum(by_person.values()), 2), "by_person": by_person,
            "pending": pending, "pending_by_person": pending_by, "hours_pending_total": round(sum(pending_by.values()), 2),
            "materials": sorted(mats.values(), key=lambda x: x["name"].lower()), "problems": problems,
            "entries": sum(1 for lg in logs if not lg.get("kind")),   # state changes are not entries
            "first_day": min((lg.get("date") for lg in logs if lg.get("date")), default=None),
            "last_day": max((lg.get("date") for lg in logs if lg.get("date")), default=None)}


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
    mats, unpriced_mats = [], []
    for m in tot["materials"]:
        p = (prices or {}).get(price_key(m["name"], m.get("unit") or ""))
        price = p.get("price") if isinstance(p, dict) else p
        cost = round(m["qty"] * float(price), 2) if (price is not None and m.get("qty") is not None) else None
        if cost is None:
            unpriced_mats.append(m["name"])
        mats.append({**m, "key": price_key(m["name"], m.get("unit") or ""), "price": price, "cost": cost})
    extras = [x for x in (extras or []) if x.get("amount") is not None]
    labor_total = round(sum(x["cost"] for x in labor if x["cost"] is not None), 2)
    materials_total = round(sum(x["cost"] for x in mats if x["cost"] is not None), 2)
    extras_total = round(sum(float(x["amount"]) for x in extras), 2)
    cost_total = round(labor_total + materials_total + extras_total, 2)
    out = {"labor": labor, "materials": mats, "extras": extras, "labor_total": labor_total, "materials_total": materials_total,
           "extras_total": extras_total, "cost_total": cost_total, "budget": budget, "margin": None, "used_pct": None,
           "unpriced_hours": round(unpriced_hours, 2), "unpriced_materials": unpriced_mats,
           "complete": not unpriced_hours and not unpriced_mats}
    if budget:
        out["margin"] = round(float(budget) - cost_total, 2)
        out["used_pct"] = round(cost_total / float(budget) * 100, 1)
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
                     for m in materials)


def _ctx_line(lg: dict) -> str:
    who = lg.get("author_name") or ""
    if lg.get("kind"):   # a change of state, a report made
        return f"- {lg.get('date')} · {lg.get('text')}"
    return f"- {lg.get('date')} · {who}: {search_text(lg)}" + (f" ({len(lg['photos'])} foto)" if lg.get("photos") else "")


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
