"""Task ricorrenti: regola di ripetizione di una serie di task, date delle occorrenze,
descrizione in italiano e regola RRULE per Google Calendar.

A recurring task is a "series" (task_series collection) holding the template fields and a
rule; its occurrences are ordinary tasks (with series_id) generated a rolling window ahead
(WINDOW_DAYS), so each one can be completed, moved or deleted on its own and shows up in
the calendar strip / month list like any other task. Everything here is pure and
deterministic - no dates are ever left to the model.

Rule shape (normalize_rule):
  {"freq": "daily"|"weekly"|"monthly"|"yearly", "interval": 1..99,
   "weekdays": [0..6]            (weekly only, 0 = lunedì),
   "day_of_month": 1..31 | -1    (monthly only, -1 = ultimo giorno),
   "until": "YYYY-MM-DD" | None, "count": int | None}
"""
from datetime import date, timedelta
from typing import Optional

WINDOW_DAYS = 60
MAX_SCAN_DAYS = 6000

FREQS = ("daily", "weekly", "monthly", "yearly")
IT_WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]
IT_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
             "settembre", "ottobre", "novembre", "dicembre"]
_RR_DAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]


def _int(v, lo, hi) -> Optional[int]:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if lo <= n <= hi else None


def normalize_rule(raw, start: Optional[date] = None) -> Optional[dict]:
    """Validates a rule (from the UI or the model). Missing weekday/day-of-month default to
    the start date's, so "ogni settimana" starting on a Monday means every Monday."""
    if not isinstance(raw, dict) or raw.get("freq") not in FREQS:
        return None
    rule = {"freq": raw["freq"], "interval": _int(raw.get("interval") or 1, 1, 99) or 1}
    if rule["freq"] == "weekly":
        days = sorted({d for d in (_int(x, 0, 6) for x in (raw.get("weekdays") or [])) if d is not None})
        if not days:
            if not start:
                return None
            days = [start.weekday()]
        if len(days) == 7 and rule["interval"] == 1:
            rule = {"freq": "daily", "interval": 1}
        else:
            rule["weekdays"] = days
    elif rule["freq"] == "monthly":
        dom = raw.get("day_of_month")
        dom = -1 if str(dom) == "-1" else _int(dom, 1, 31)
        if dom is None:
            if not start:
                return None
            dom = start.day
        rule["day_of_month"] = dom
    until = raw.get("until")
    if until:
        try:
            rule["until"] = date.fromisoformat(str(until)[:10]).isoformat()
        except ValueError:
            pass
    count = _int(raw.get("count"), 1, 1000) if raw.get("count") else None
    if count:
        rule["count"] = count
    return rule


def _last_day(y: int, m: int) -> int:
    nxt = date(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return (nxt - timedelta(days=1)).day


def _matches(rule: dict, start: date, d: date) -> bool:
    f, n = rule["freq"], rule.get("interval", 1)
    if f == "daily":
        return (d - start).days % n == 0
    if f == "weekly":
        if d.weekday() not in rule["weekdays"]:
            return False
        weeks = ((d - timedelta(days=d.weekday())) - (start - timedelta(days=start.weekday()))).days // 7
        return weeks % n == 0
    if f == "monthly":
        months = (d.year * 12 + d.month) - (start.year * 12 + start.month)
        if months % n:
            return False
        last = _last_day(d.year, d.month)
        dom = rule["day_of_month"]
        return d.day == (last if dom == -1 else min(dom, last))  # "il 31" -> ultimo giorno nei mesi corti
    # yearly: same day/month as the start (29 febbraio -> 28 negli anni non bisestili)
    if (d.year - start.year) % n or d.month != start.month:
        return False
    return d.day == min(start.day, _last_day(d.year, d.month))


def occurrences(rule: dict, start: date, from_date: date, to_date: date) -> list[date]:
    """Occurrence dates within [from_date, to_date], counting from `start` (the first
    occurrence of the series is always `start` itself, even if it doesn't match the rule -
    e.g. a task created on a Thursday and then set to repeat every Monday keeps its date)."""
    until = date.fromisoformat(rule["until"]) if rule.get("until") else None
    count = rule.get("count")
    end = min(to_date, until) if until else to_date
    out, seen, d = [], 0, start
    for _ in range(MAX_SCAN_DAYS):
        if d > end:
            break
        if d == start or _matches(rule, start, d):
            seen += 1
            if count and seen > count:
                break
            if d >= from_date:
                out.append(d)
        d += timedelta(days=1)
    return out


def is_finished(rule: dict, start: date, after: date) -> bool:
    """True when no occurrence exists after `after` (the series can stop being extended)."""
    horizon = after + timedelta(days=400 * rule.get("interval", 1))
    return not occurrences(rule, start, after + timedelta(days=1), horizon)


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " e " + words[-1]


def rule_label(rule: dict, start: Optional[date] = None) -> str:
    f, n = rule["freq"], rule.get("interval", 1)
    if f == "daily":
        s = "Ogni giorno" if n == 1 else f"Ogni {n} giorni"
    elif f == "weekly":
        days = rule["weekdays"]
        names = _join([IT_WEEKDAYS[d] for d in days])
        if n == 1:
            s = "Dal lunedì al venerdì" if days == [0, 1, 2, 3, 4] else f"Ogni {names}"
        else:
            s = f"Ogni {n} settimane, {names}"
    elif f == "monthly":
        dom = rule["day_of_month"]
        when = "l'ultimo giorno" if dom == -1 else f"il giorno {dom}"
        s = f"Ogni mese {when}" if n == 1 else f"Ogni {n} mesi {when}"
    else:
        when = f" il {start.day} {IT_MONTHS[start.month - 1]}" if start else ""
        s = f"Ogni anno{when}" if n == 1 else f"Ogni {n} anni{when}"
    if rule.get("until"):
        u = date.fromisoformat(rule["until"])
        s += f", fino al {u.day} {IT_MONTHS[u.month - 1]} {u.year}"
    elif rule.get("count"):
        s += f", per {rule['count']} volte"
    return s


def to_rrule(rule: dict, start: Optional[date] = None) -> str:
    """RRULE for a single recurring Google Calendar event mirroring the series."""
    f, n = rule["freq"], rule.get("interval", 1)
    parts = [f"FREQ={f.upper()}"]
    if n > 1:
        parts.append(f"INTERVAL={n}")
    if f == "weekly":
        parts.append("BYDAY=" + ",".join(_RR_DAYS[d] for d in rule["weekdays"]))
    elif f == "monthly":
        dom = rule["day_of_month"]
        if dom == -1 or dom <= 28:
            parts.append(f"BYMONTHDAY={dom}")
        else:
            # "il 31" = last day in shorter months, same as the app: the last of 28..31 that exists
            parts.append("BYMONTHDAY=" + ",".join(str(x) for x in range(28, dom + 1)) + ";BYSETPOS=-1")
    if rule.get("until"):
        parts.append("UNTIL=" + rule["until"].replace("-", "") + "T235959Z")
    elif rule.get("count"):
        parts.append(f"COUNT={rule['count']}")
    return "RRULE:" + ";".join(parts)


def first_occurrence(raw, today: date) -> str:
    """First date from `today` on matching a rule the user gave without a start date
    ("ogni lunedì" -> the next Monday, today included)."""
    rule = normalize_rule(raw, today)
    if not rule:
        return today.isoformat()
    for i in range(0, 400 * rule.get("interval", 1)):
        d = today + timedelta(days=i)
        if _matches(rule, today, d):
            return d.isoformat()
    return today.isoformat()
