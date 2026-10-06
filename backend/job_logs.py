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


def clean_materials(rows) -> list:
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not str(r.get("name") or "").strip():
            continue
        out.append({"name": str(r["name"]).strip()[:120], "qty": _num(r.get("qty")),
                    "unit": str(r.get("unit") or "").strip()[:20]})
    return out


def clean_problems(rows) -> list:
    return [str(p).strip()[:300] for p in (rows if isinstance(rows, list) else []) if str(p or "").strip()]


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
                    user_id: Optional[str] = None, channel: str = "web") -> dict:
    """-> {"date", "text", "hours": [{who, hours}], "materials": [{name, qty, unit}], "problems": [...],
    "client": str, "commessa": str}"""
    today = today_local()
    team_s = ", ".join(t for t in team if t and t != speaker) or "nessuno registrato"
    job_s = (f"La voce riguarda la commessa «{known.get('title')}» del cliente {known.get('client')}.\n"
             if known and known.get("title") else "")
    system = (
        "Sei l'assistente di un'impresa artigiana (impianti, edilizia, manutenzioni). Ricevi una voce del "
        "DIARIO DI COMMESSA: cosa è stato fatto in cantiere. Oggi è "
        f"{IT_WEEKDAYS[today.weekday()]} {today.isoformat()}. Chi scrive è {speaker} (\"io\" = {speaker}); "
        f"colleghi del team: {team_s}.\n{job_s}\n"
        "Compiti:\n"
        "1. \"text\": il testo sistemato (grammatica, punteggiatura, termini tecnici corretti), stessa persona "
        "e stessi fatti. NON aggiungere nulla che non sia detto.\n"
        "2. \"date\": il giorno a cui si riferisce (\"ieri\", \"lunedì\", \"il 3\") in formato YYYY-MM-DD; se non "
        "lo dice, oggi.\n"
        "3. \"hours\": ore lavorate PER PERSONA, [{\"who\": nome, \"hours\": numero}]. \"Io e Gino 4 ore\" = 4 "
        "a testa (due righe). \"Dalle 8 alle 12\" = 4. Un collega senza nome: \"who\": \"collega\". Se le ore "
        "non sono dette: [] (MAI stimarle).\n"
        "4. \"materials\": materiali usati o posati, [{\"name\", \"qty\": numero o null, \"unit\": \"m|pz|kg|l|"
        "sacchi|...\" o \"\"}]. Solo quelli detti, con le quantità dette; niente attrezzi.\n"
        "5. \"problems\": problemi, imprevisti, cose mancanti o da rifare, frasi brevi. Nessuno: [].\n"
        "6. \"client\" e \"commessa\": il cliente e i lavori/cantiere come li nomina il testo (\"dai Rossi\" -> "
        "\"Rossi\"), stringa vuota se non li nomina.\n"
        "Rispondi SOLO con JSON: {\"date\": \"\", \"text\": \"\", \"hours\": [], \"materials\": [], \"problems\": [], "
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
    return {
        "date": valid_day(parsed.get("date"), today),
        "text": str(parsed.get("text") or "").strip() or text.strip(),
        "hours": clean_hours(parsed.get("hours"), speaker),
        "materials": clean_materials(parsed.get("materials")),
        "problems": clean_problems(parsed.get("problems")),
        "client": str(parsed.get("client") or "").strip(),
        "commessa": str(parsed.get("commessa") or "").strip(),
    }


def _mat_key(m: dict) -> tuple:
    return (" ".join((m.get("name") or "").lower().split()), (m.get("unit") or "").lower().strip("."))


def totals(logs: list) -> dict:
    """Hours (total and per person), materials summed by name+unit, problems with their day."""
    by_person, mats, problems = {}, {}, []
    for lg in logs:
        for h in lg.get("hours") or []:
            by_person[h["who"]] = round(by_person.get(h["who"], 0) + float(h.get("hours") or 0), 2)
        for m in lg.get("materials") or []:
            k = _mat_key(m)
            cur = mats.setdefault(k, {"name": m["name"], "unit": m.get("unit") or "", "qty": None})
            if m.get("qty") is not None:
                cur["qty"] = round((cur["qty"] or 0) + float(m["qty"]), 3)
        for p in lg.get("problems") or []:
            problems.append({"date": lg.get("date"), "text": p, "log_id": lg.get("id")})
    return {"hours_total": round(sum(by_person.values()), 2), "by_person": by_person,
            "materials": sorted(mats.values(), key=lambda x: x["name"].lower()), "problems": problems,
            "entries": sum(1 for lg in logs if not lg.get("kind")),   # state changes are not entries
            "first_day": min((lg.get("date") for lg in logs if lg.get("date")), default=None),
            "last_day": max((lg.get("date") for lg in logs if lg.get("date")), default=None)}


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
    if lg.get("kind") == "stato":
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
    ] if x)
    totals_s = (f"Voci di diario: {tot['entries']}. Ore totali: {_fmt_num(tot['hours_total'])} h" + (f" ({per})" if per else "")
                + ". Materiali: " + (materials_line(tot["materials"]) or "nessuno") + ".")
    diary = "\n".join(_ctx_line(lg) for lg in logs) or "(nessuna voce)"
    reps = []
    for r in reports:
        filled = "; ".join(f"{f}: {v}" for sec in r.get("sections") or [] for f, v in sec["fields"].items() if v)
        reps.append(f"- {r.get('template_name')} del {(r.get('created_at') or '')[:10]}: {filled[:2500]}")
    today = today_local()
    system = (
        "Sei l'assistente di un'impresa artigiana e rispondi su UNA commessa, usando SOLO i dati qui sotto (scheda, "
        "diario, report). Se un dato non c'è, dillo chiaramente: non inventare ore, materiali, date o importi. Fai i conti "
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
    if log.get("materials"):
        bits.append("Materiali: " + materials_line(log["materials"]) + ".")
    if log.get("problems"):
        bits.append("Problemi: " + "; ".join(log["problems"]) + ".")
    return " ".join(b for b in bits if b)
