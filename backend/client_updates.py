"""The weekly progress for the client (artigiano), on Telegram: what was done on their commessa
this week, the milestones reached and the next works - a short, friendly message. Never hours,
times, costs, prices, people's names or internal problems: only the diary's notes of work
done, rewritten for the client and checked against them (a line that isn't in the notes, or
that speaks of hours or money, is dropped).
Kept free of server imports so it can be tested on its own.
"""
import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Optional

import openai

import job_logs as jl

logger = logging.getLogger(__name__)

WEEKDAYS = jl.IT_WEEKDAYS
DEFAULT_DAY, DEFAULT_AT = 4, "17:00"     # friday, 17:00 (the owner can change them)
MAX_LINES = 8

# what a client never reads: hours and times, money, the quote, the site's internal problems
_PRIVATE = re.compile(r"€|\beur[o]?\b|\d+(?:[.,]\d+)?\s*(?:h|ore|ora|min|minuti)\b|\b(?:dalle|alle)\s+\d|\d{1,2}[:.]\d{2}\b"
                      r"|\bcost[oiae]?\b|\bprezz|\bpreventiv|\bmargin|\bfattur|\bpagament|\bsconto|\bacconto"
                      r"|\bmanc(?:a|ano|ava|avano|ante|anti)\b|\bsbagli|\berror|\britard|\bproblem|\bguast|\bdifett|\bcolpa\b", re.I)


def period_label(start: date, end: date) -> str:
    months = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre",
              "ottobre", "novembre", "dicembre"]
    if start.month == end.month:
        return f"dal {start.day} al {end.day} {months[end.month - 1]}"
    return f"dal {start.day} {months[start.month - 1]} al {end.day} {months[end.month - 1]}"


def safe_lines(lines: list, source: str) -> list:
    """Only lines that hold to the notes and say nothing private."""
    out = []
    for ln in lines if isinstance(lines, list) else []:
        t = " ".join(str(ln or "").strip(" -•·").split())
        if t and not _PRIVATE.search(t) and jl.grounded(t, source, 0.6) and t not in out:
            out.append(t[0].upper() + t[1:])
    return out[:MAX_LINES]


async def summarize(title: str, notes: list, user_id: Optional[str] = None) -> list:
    """The week's notes (texts of the diary) -> the lines of work done, for the client."""
    if not notes:
        return []
    source = "\n".join(notes)
    system = (
        "Sei l'assistente di un'impresa artigiana. Scrivi per il CLIENTE un breve aggiornamento su come avanzano i "
        f"lavori «{title}» questa settimana, usando SOLO le note del diario di cantiere qui sotto.\n"
        "Regole:\n"
        "- Elenca i lavori fatti, in frasi brevi e chiare per chi non è del mestiere, al passato (\"Posato il piatto doccia\"). "
        f"Unisci le attività simili; al massimo {MAX_LINES} righe.\n"
        "- NON scrivere MAI: ore lavorate, orari, costi, prezzi, importi, preventivi, nomi delle persone o delle ditte, "
        "problemi, ritardi, errori, materiali mancanti o da comprare, cose ancora da fare.\n"
        "- Non aggiungere nulla che non sia nelle note. Se le note non contengono lavori fatti, restituisci un elenco vuoto.\n"
        "Rispondi SOLO con JSON: {\"done\": [\"...\"]}"
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    try:
        resp = await client.chat.completions.create(
            model=jl.MODEL, max_completion_tokens=800, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": system}, {"role": "user", "content": source[:12000]}])
    except Exception:
        jl._track(None, user_id, "telegram", status="errore")
        raise
    jl._track(resp, user_id, "telegram")
    m = re.search(r"\{.*\}", resp.choices[0].message.content or "", re.S)
    parsed = json.loads(m.group(0)) if m else {}
    return safe_lines(parsed.get("done"), source)


def message(title: str, start: date, end: date, done: list, reached: list, upcoming: list, signer: str) -> str:
    """The message for the client (plain text)."""
    lines = [f"🏗️ Avanzamento lavori — «{title}»", f"Settimana {period_label(start, end)}", ""]
    if done:
        lines.append("Questa settimana:")
        lines += [f"• {x}" for x in done]
    for r in reached:
        lines.append(f"✅ Completato: {r}")
    if upcoming:
        lines += ["", "Prossimi lavori: " + ", ".join(upcoming) + "."]
    if signer:
        lines += ["", signer]
    return "\n".join(lines).strip()


def week_start(day: date, last_sent: Optional[str]) -> date:
    """From the day after the last message (at most a week back), else the last 7 days."""
    start = day - timedelta(days=6)
    try:
        after = date.fromisoformat(str(last_sent)[:10]) + timedelta(days=1)
    except ValueError:
        return start
    return min(max(start, after), day)
