"""Azioni programmate: comandi ricorrenti scritti a parole dall'utente ("ogni venerdì
all'una di notte svuota la lista lezioni di pilates", "ogni domenica a mezzanotte calcola la
spesa della settimana e mandamela su Telegram") che restano attivi finché l'utente non li
disattiva o cancella.

Same design philosophy as list_updates.py / vet_reports.py: the LLM only turns the sentence
into a structured intent (what to do + a schedule in a small fixed vocabulary). Everything
that must be exact - when the next run is, which dates "la settimana passata" covers, sums
of amounts - is computed deterministically in Python, never left to the model.

Kinds of action (kept deliberately small - "azioni semplici basate su dati a disposizione"):
- list_update: a Liste edit (clear, add, delete, update...) - resolved and applied by the
  same engine as the chat's "modifica lista".
- report:      read the user's own data for a period and send back a short summary /
               calculation (sums are computed here, see fill_totals).
- message:     a fixed reminder text.
- create_task: create a task due on the day of the run.
"""
import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import openai

import usage_tracking as ut

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("Europe/Rome")
MODEL = "gpt-4o"
FEATURE = "azioni_programmate"
MAX_ACTIVE_PER_USER = 20

KINDS = {"list_update", "report", "message", "create_task"}
FREQS = {"daily", "weekly", "monthly", "once"}
PERIODS = {"none", "today", "yesterday", "this_week", "last_week", "last_7_days", "this_month", "last_month", "last_30_days"}

IT_WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
IT_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
             "settembre", "ottobre", "novembre", "dicembre"]


def _track(resp, user_id: Optional[str], channel: str, trigger: str = "utente", status: str = "ok"):
    usage = getattr(resp, "usage", None) if resp is not None else None
    details = getattr(usage, "prompt_tokens_details", None) if usage else None
    ut.fire_and_forget_llm_call(
        user_id=user_id, feature=FEATURE, channel=channel, trigger=trigger,
        model=(getattr(resp, "model", None) if resp is not None else None) or MODEL,
        endpoint="chat.completions",
        input_tokens=(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
        cached_input_tokens=(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0,
        output_tokens=(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
        status=status, request_id=getattr(resp, "id", None) if resp is not None else None,
    )


# ======================= schedule (deterministic) =======================
def _norm_time(v) -> Optional[str]:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", str(v or ""))
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    if hh == 24 and mm == 0:
        hh = 0
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def normalize_schedule(raw) -> Optional[dict]:
    """Validates the model's schedule into one of:
    {"freq": "daily", "time"}, {"freq": "weekly", "weekdays": [0..6], "time"} (0 = lunedì),
    {"freq": "monthly", "day_of_month": 1..31 | -1 (ultimo giorno), "time"},
    {"freq": "once", "date": "YYYY-MM-DD", "time"}. None if anything is missing/invalid."""
    if not isinstance(raw, dict):
        return None
    freq = raw.get("freq")
    t = _norm_time(raw.get("time"))
    if freq not in FREQS or not t:
        return None
    if freq == "daily":
        return {"freq": "daily", "time": t}
    if freq == "weekly":
        try:
            days = sorted({int(d) for d in (raw.get("weekdays") or [])})
        except (TypeError, ValueError):
            return None
        days = [d for d in days if 0 <= d <= 6]
        if not days:
            return None
        if len(days) == 7:
            return {"freq": "daily", "time": t}
        return {"freq": "weekly", "weekdays": days, "time": t}
    if freq == "monthly":
        try:
            dom = int(raw.get("day_of_month"))
        except (TypeError, ValueError):
            return None
        if dom != -1 and not (1 <= dom <= 31):
            return None
        return {"freq": "monthly", "day_of_month": dom, "time": t}
    try:
        d = date.fromisoformat(str(raw.get("date"))[:10])
    except ValueError:
        return None
    return {"freq": "once", "date": d.isoformat(), "time": t}


def _last_day(y: int, m: int) -> int:
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return (nxt - timedelta(days=1)).day


def _day_matches(schedule: dict, d: date) -> bool:
    f = schedule["freq"]
    if f == "daily":
        return True
    if f == "weekly":
        return d.weekday() in schedule["weekdays"]
    if f == "monthly":
        last = _last_day(d.year, d.month)
        dom = schedule["day_of_month"]
        target = last if dom == -1 else min(dom, last)  # "il 31" -> ultimo giorno nei mesi più corti
        return d.day == target
    return d.isoformat() == schedule["date"]


def next_run_after(schedule: dict, after: datetime, tz: ZoneInfo = LOCAL_TZ) -> Optional[datetime]:
    """First run strictly after `after` (aware datetime), as an aware UTC datetime; None
    when a one-off schedule is already in the past. Times are local (Europe/Rome), so a
    "ogni giorno alle 9" stays at 9 across daylight-saving changes."""
    hh, mm = map(int, schedule["time"].split(":"))
    start = after.astimezone(tz).date()
    if schedule["freq"] == "once":
        d = date.fromisoformat(schedule["date"])
        cand = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(timezone.utc)
        return cand if cand > after else None
    for i in range(0, 400):
        d = start + timedelta(days=i)
        if not _day_matches(schedule, d):
            continue
        cand = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz).astimezone(timezone.utc)
        if cand > after:
            return cand
    return None


def _join_it(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " e " + words[-1]


def schedule_label(schedule: dict) -> str:
    """Human description, e.g. "Ogni venerdì alle 01:00". A 00:00 run is spelled out as the
    midnight between two days, since "domenica a mezzanotte" is exactly where people differ."""
    t = schedule["time"]
    midnight = t == "00:00"

    def at(days_before: list[str] = None) -> str:
        if midnight and days_before:
            return f"a mezzanotte (fine di {_join_it(days_before)})"
        return "a mezzanotte" if midnight else f"alle {t}"

    f = schedule["freq"]
    if f == "daily":
        return f"Ogni giorno {at()}"
    if f == "weekly":
        days = schedule["weekdays"]
        if midnight:
            prev = [IT_WEEKDAYS[(d - 1) % 7] for d in days]
            return f"Ogni {_join_it([IT_WEEKDAYS[d] for d in days])} alle 00:00, cioè {at(prev)}"
        if days == [0, 1, 2, 3, 4]:
            return f"Dal lunedì al venerdì {at()}"
        if days == [5, 6]:
            return f"Ogni sabato e domenica {at()}"
        return f"Ogni {_join_it([IT_WEEKDAYS[d] for d in days])} {at()}"
    if f == "monthly":
        dom = schedule["day_of_month"]
        when = "l'ultimo giorno" if dom == -1 else (f"il giorno {dom}" + (" (o l'ultimo giorno, nei mesi più corti)" if dom > 28 else ""))
        return f"Ogni mese {when} {at()}"
    d = date.fromisoformat(schedule["date"])
    return f"Una volta sola, {IT_WEEKDAYS[d.weekday()]} {d.day} {IT_MONTHS[d.month - 1]} {d.year} {at()}"


def period_range(period: str, run_local: datetime) -> Optional[tuple[date, date, str]]:
    """Calendar dates (inclusive) a report refers to, relative to the LOCAL moment it runs.
    A run at Monday 00:00 ("domenica a mezzanotte") gives last_week = the Mon-Sun just ended."""
    d = run_local.date()
    monday = d - timedelta(days=d.weekday())
    fmt = lambda x: f"{x.day} {IT_MONTHS[x.month - 1]}"
    if period == "today":
        return d, d, f"oggi ({fmt(d)})"
    if period == "yesterday":
        y = d - timedelta(days=1)
        return y, y, f"ieri ({fmt(y)})"
    if period == "this_week":
        return monday, d, f"questa settimana (dal {fmt(monday)} al {fmt(d)})"
    if period == "last_week":
        s, e = monday - timedelta(days=7), monday - timedelta(days=1)
        return s, e, f"la settimana passata (dal {fmt(s)} al {fmt(e)})"
    if period == "last_7_days":
        s, e = d - timedelta(days=7), d - timedelta(days=1)
        return s, e, f"gli ultimi 7 giorni (dal {fmt(s)} al {fmt(e)})"
    if period == "this_month":
        s = d.replace(day=1)
        return s, d, f"questo mese (dal {fmt(s)} al {fmt(d)})"
    if period == "last_month":
        e = d.replace(day=1) - timedelta(days=1)
        s = e.replace(day=1)
        return s, e, f"il mese scorso ({IT_MONTHS[s.month - 1]} {s.year})"
    if period == "last_30_days":
        s, e = d - timedelta(days=30), d - timedelta(days=1)
        return s, e, f"gli ultimi 30 giorni (dal {fmt(s)} al {fmt(e)})"
    return None


PERIOD_PREVIEW = {
    "today": "il giorno dell'esecuzione", "yesterday": "il giorno prima dell'esecuzione",
    "this_week": "la settimana in corso", "last_week": "la settimana precedente (lunedì-domenica)",
    "last_7_days": "i 7 giorni precedenti", "this_month": "il mese in corso",
    "last_month": "il mese precedente", "last_30_days": "i 30 giorni precedenti",
}


# ======================= totals (deterministic math) =======================
def _to_number(v) -> Optional[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = re.sub(r"[^\d,.\-]", "", str(v or ""))
    if not s or s in "-.,":
        return None
    if "," in s and "." in s:
        # the right-most separator is the decimal one: 1.234,50 / 1,234.50
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def format_number_it(x: float) -> str:
    """12.5 -> '12,50', 1234 -> '1.234', 1234.5 -> '1.234,50'."""
    neg = x < 0
    x = abs(round(x, 2))
    whole = int(x)
    cents = round((x - whole) * 100)
    if cents == 100:
        whole, cents = whole + 1, 0
    s = f"{whole:,}".replace(",", ".")
    if cents:
        s += f",{cents:02d}"
    return ("-" if neg else "") + s


def fill_totals(message: str, totals) -> str:
    """The report model never does arithmetic itself: it writes {{T1}}, {{T2}}... in the text
    and lists the values to add up for each; the sums are computed here."""
    sums = {}
    for t in totals if isinstance(totals, list) else []:
        if not isinstance(t, dict) or not t.get("key"):
            continue
        nums = [n for n in (_to_number(v) for v in (t.get("values") or [])) if n is not None]
        sums[str(t["key"]).strip("{} ")] = format_number_it(sum(nums))
    return re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", lambda m: sums.get(m.group(1), "?"), message or "")


# ======================= LLM: interpret the command =======================
async def interpret_command(text: str, catalog: list[dict], now_local: datetime, telegram_linked: bool,
                            user_id: Optional[str] = None, channel: str = "web") -> dict:
    """Free text -> structured draft. `catalog`: the user's lists as [{"name", "has_sub_items"}]."""
    lists_desc = "; ".join(
        f"\"{c['name']}\"" + (" (i suoi Campi contengono Elementi annidati)" if c.get("has_sub_items") else "")
        for c in catalog[:60]
    ) or "nessuna"
    today = now_local.date()
    system = (
        "Interpreti comandi con cui l'utente programma un'AZIONE RICORRENTE da eseguire automaticamente in un'app "
        "di assistenza personale (liste, task, note, diario, Telegram). "
        f"Adesso è {IT_WEEKDAYS[today.weekday()]} {today.isoformat()} ore {now_local.strftime('%H:%M')} (Europe/Rome). "
        f"Liste dell'utente: {lists_desc}. Telegram collegato: {'sì' if telegram_linked else 'no'}.\n\n"
        "Tipi di azione possibili ('kind'):\n"
        "- list_update: modificare una lista (svuotarla, aggiungere/togliere/modificare Campi o Elementi). In "
        "'list_request' riscrivi SOLO l'istruzione di modifica, senza la parte temporale, con il nome esatto della "
        "lista (es. 'elimina tutti gli elementi di tutti i campi della lista Lezioni Pilates'). Struttura delle liste: "
        "Lista -> Campi (es. le lezioni) -> Elementi annidati (es. gli iscritti). Se l'utente dice 'elementi', "
        "'iscritti', 'persone' o 'svuota i campi' di una lista con Elementi annidati intende gli Elementi dentro i "
        "Campi (i Campi restano); se dice 'cancella i campi' o 'svuota la lista' senza Elementi annidati intende i Campi.\n"
        "- report: leggere i dati salvati dall'utente (note, liste, task, diario) e mandargli un riepilogo o un "
        "calcolo (es. 'calcola la spesa della settimana passata', 'riassumimi le lezioni fatte nel mese'). Metti in "
        "'report_instruction' cosa calcolare/riassumere, e in 'period' il periodo di dati a cui si riferisce "
        f"(uno tra {', '.join(sorted(PERIODS))}; relativo al momento dell'esecuzione).\n"
        "- message: mandare un promemoria fisso (es. 'ogni mattina alle 8 ricordami di prendere la pillola'): "
        "testo in 'message_text'.\n"
        "- create_task: creare un task con scadenza il giorno dell'esecuzione (es. 'il primo di ogni mese crea "
        "il task pagare l'affitto'): 'task': {\"title\", \"priority\": \"alta|media|bassa\", \"due_time\": \"HH:MM o null\"}.\n\n"
        "Cadenza ('schedule'), orari in ora italiana:\n"
        "- {\"freq\": \"daily\", \"time\": \"HH:MM\"}\n"
        "- {\"freq\": \"weekly\", \"weekdays\": [0-6, 0=lunedì ... 6=domenica], \"time\": \"HH:MM\"}\n"
        "- {\"freq\": \"monthly\", \"day_of_month\": 1-31 o -1 per l'ultimo giorno, \"time\": \"HH:MM\"}\n"
        "- {\"freq\": \"once\", \"date\": \"YYYY-MM-DD\", \"time\": \"HH:MM\"} solo se l'utente vuole UNA sola esecuzione.\n"
        "Regole orari: 'l'una di notte di venerdì' / 'venerdì all'una di notte' = venerdì 01:00. 'X a mezzanotte' = "
        "fine del giorno X, cioè 00:00 del giorno SUCCESSIVO (es. 'domenica a mezzanotte' -> weekdays [0] lunedì "
        "alle 00:00; così 'la settimana passata' è quella lunedì-domenica appena conclusa). 'Mattina' senza orario "
        "= 08:00, 'sera' = 20:00. Se l'orario manca del tutto usa 09:00.\n\n"
        "'delivery': 'telegram' se l'utente chiede di mandargli qualcosa su Telegram (o per report/message in "
        "generale, se Telegram è collegato), altrimenti 'app'. 'notify': true se per list_update/create_task "
        "l'utente chiede di essere avvisato quando l'azione viene eseguita.\n\n"
        "NON supportate (supported=false, con 'reason' breve e gentile in italiano): azioni su servizi esterni non "
        "collegati (email, acquisti, pagamenti, siti web), cadenze sotto il giorno (ogni ora, ogni 10 minuti), "
        "richieste che non sono azioni ripetibili, azioni che richiederebbero dati che l'app non ha. Se il comando è "
        "troppo vago per capire cosa fare o quando, supported=false e in 'reason' chiedi cosa manca.\n\n"
        "Rispondi SOLO con JSON: {\"supported\": true|false, \"reason\": \"\", \"title\": \"titolo breve (max 60 "
        "caratteri) di cosa fa l'azione\", \"kind\": \"...\", \"schedule\": {...}, \"list_request\": \"\", "
        "\"report_instruction\": \"\", \"period\": \"none\", \"message_text\": \"\", \"task\": null, "
        "\"delivery\": \"telegram|app\", \"notify\": false}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=800, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
        )
    except Exception:
        _track(None, user_id, channel, status="errore")
        raise
    _track(resp, user_id, channel)
    raw = resp.choices[0].message.content or "{}"
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    parsed = json.loads(m.group(0)) if m else {}
    return parsed if isinstance(parsed, dict) else {}


# ======================= LLM: write a report =======================
async def write_report(instruction: str, data_block: str, now_local: datetime, period_label: Optional[str],
                       user_name: str = "", user_id: Optional[str] = None) -> str:
    today = now_local.date()
    system = (
        "Sei mAIPAL e stai eseguendo un'AZIONE PROGRAMMATA dall'utente: il testo che scrivi gli viene inviato così "
        f"com'è (di solito su Telegram). Adesso è {IT_WEEKDAYS[today.weekday()]} {today.day} "
        f"{IT_MONTHS[today.month - 1]} {today.year}, ore {now_local.strftime('%H:%M')}.\n"
        f"Istruzione dell'utente: \"{instruction}\".\n"
        + (f"Periodo di riferimento: {period_label}. Considera SOLO i dati che ricadono in questo periodo (le note "
           "riportano la data in cui sono state salvate: 'oggi'/'ieri' in una nota vanno letti rispetto a quella data).\n"
           if period_label else "")
        + "Usa ESCLUSIVAMENTE i DATI qui sotto, non inventare nulla. Se non ci sono dati pertinenti scrivilo "
        "chiaramente in una riga (es. 'Nessuna spesa registrata nel periodo').\n"
        "CALCOLI: non fare MAI tu le somme. Elenca le voci considerate (data, descrizione, importo) e al posto di "
        "ogni totale scrivi un segnaposto {{T1}}, {{T2}}, ...; in 'totals' riporta per ciascun segnaposto l'elenco "
        "dei numeri da sommare (solo numeri, es. 12.5). Il sistema sostituirà i segnaposto con i risultati esatti.\n"
        "Stile: breve e chiaro, in italiano, senza preamboli né saluti lunghi; puoi usare *grassetto* con un solo "
        "asterisco ed elenchi con '•'.\n"
        "Rispondi SOLO con JSON: {\"message\": \"testo\", \"totals\": [{\"key\": \"T1\", \"values\": [..]}]}\n\n"
        f"DATI:\n{data_block or '(nessun dato)'}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(
            model=MODEL, max_completion_tokens=1500, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": instruction}],
        )
    except Exception:
        _track(None, user_id, "sistema", trigger="automatico", status="errore")
        raise
    _track(resp, user_id, "sistema", trigger="automatico")
    raw = resp.choices[0].message.content or "{}"
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    parsed = json.loads(m.group(0)) if m else {}
    return fill_totals(str(parsed.get("message") or "").strip(), parsed.get("totals")).strip()
