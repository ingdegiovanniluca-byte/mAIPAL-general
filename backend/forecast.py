"""Previsioni di commessa: where a job is heading, from its own data, no AI.

- progress: how much of the job is done - the milestones done, each weighted by the working
  days it was planned to take; without milestones, the percentage of the last SAL report.
- end: when it will really end - the pace of the milestones done so far (how much longer than
  planned they took) applied to the ones left.
- cost: what it will cost at the end - the cost so far divided by the progress.
- stall: a site "in corso" slowing down or standing still.

Every forecast says how much it can be trusted (bassa / media / alta) and, when it can't be
made, why (no milestones, too early...), so nothing is guessed.
"""
import re
from datetime import date, datetime, timedelta
from typing import Optional

MIN_PROGRESS_FOR_COST = 0.15   # before 15% done the cost so far says little about the end
PACE_MIN, PACE_MAX = 0.6, 3.0  # a pace outside this is a typing error, not a job


def _d(s) -> Optional[date]:
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def workdays(a: date, b: date) -> int:
    """Working days (Mon-Fri) after a up to b included; 0 when b is not after a."""
    if b <= a:
        return 0
    days = (b - a).days
    weeks, rest = divmod(days, 7)
    n = weeks * 5
    for i in range(1, rest + 1):
        if (a + timedelta(days=i)).weekday() < 5:
            n += 1
    return n


def add_workdays(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def start_of(commessa: dict, first_day: Optional[str], milestones: list, today: date) -> date:
    """The job's first day: its start date, else its first diary entry, else when its first
    milestone was planned."""
    for s in (commessa.get("data_inizio"), first_day):
        d = _d(s)
        if d:
            return d
    made = [_d(m.get("created_at")) for m in milestones]
    made = [d for d in made if d]
    return min(made) if made else today


def _spans(milestones: list, start: date) -> list:
    """[(milestone, planned working days, planned date)], in planned order: each milestone takes
    the working days from the one before (or the start) to its first planned date."""
    rows = []
    prev = start
    for m in sorted(milestones, key=lambda x: (x.get("original_due_date") or x.get("due_date") or "", x.get("created_at") or "")):
        planned = _d(m.get("original_due_date") or m.get("due_date"))
        if not planned:
            continue
        rows.append((m, max(1, workdays(prev, planned)), planned))
        prev = max(prev, planned)
    return rows


def sal_percent(reports: list) -> Optional[tuple]:
    """(percent 0-1, date) from the latest SAL report that states one."""
    best = None
    for r in reports:
        if r.get("report_type") != "sal":
            continue
        for sec in r.get("sections") or []:
            v = (sec.get("fields") or {}).get("Percentuale di avanzamento") or ""
            m = re.search(r"(\d{1,3})(?:[.,]\d+)?\s*%?", str(v))
            if m and 0 <= int(m.group(1)) <= 100:
                when = (r.get("created_at") or "")[:10]
                if not best or when > best[1]:
                    best = (int(m.group(1)) / 100, when)
    return best


def progress(milestones: list, start: date, sal: Optional[tuple] = None) -> Optional[dict]:
    rows = _spans(milestones, start)
    if rows:
        total = sum(s for _, s, _ in rows)
        done = sum(s for m, s, _ in rows if m.get("done"))
        return {"value": round(done / total, 3), "source": "milestone", "done": sum(1 for m, _, _ in rows if m.get("done")),
                "total": len(rows)}
    if sal:
        return {"value": sal[0], "source": "sal", "date": sal[1]}
    return None


def end_forecast(milestones: list, start: date, today: date) -> Optional[dict]:
    rows = _spans(milestones, start)
    if not rows:
        return None
    planned_end = max(_d(m.get("due_date")) or p for m, _, p in rows)   # the plan as it is now
    done = [(m, s, p) for m, s, p in rows if m.get("done")]
    left = [(m, s, p) for m, s, p in rows if not m.get("done")]
    last_done = max((_d(m.get("done_date")) or p for m, _, p in done), default=None)
    if not left:
        return {"date": (last_done or planned_end).isoformat(), "planned": planned_end.isoformat(), "delay_days": 0,
                "pace": 1.0, "confidence": "alta", "finished": True}
    if done:
        pace = max(1, workdays(start, last_done)) / sum(s for _, s, _ in done)
    else:   # nothing done yet: late on the first one already says something
        first = left[0]
        pace = (workdays(start, today) / first[1]) if today > first[2] else 1.0
    pace = max(PACE_MIN, min(PACE_MAX, pace))
    since = last_done or start
    still = sum(s for _, s, _ in left) * pace - workdays(since, today)
    end = add_workdays(today, max(len(left), round(still)))
    delay = workdays(planned_end, end) if end > planned_end else -workdays(end, planned_end)
    confidence = "alta" if len(done) >= 4 else "media" if len(done) >= 2 else "bassa"
    return {"date": end.isoformat(), "planned": planned_end.isoformat(), "delay_days": delay, "pace": round(pace, 2),
            "confidence": confidence, "finished": False}


def cost_forecast(econ: dict, prog: Optional[dict]) -> Optional[dict]:
    """What the job will cost at the end, at this pace: cost so far / progress."""
    if not prog or not econ or (econ.get("cost_total") or 0) <= 0:
        return None
    p = prog["value"]
    if p < MIN_PROGRESS_FOR_COST:
        return {"final": None, "reason": "troppo presto: meno del 15% dei lavori fatto"}
    final = round(econ["cost_total"] / p, 2)
    budget = econ.get("budget")
    out = {"final": final, "budget": budget, "pct": round(final / budget * 100, 1) if budget else None,
           "over": round(final - budget, 2) if budget else None, "complete": econ.get("complete", True)}
    if prog["source"] == "sal":
        out["confidence"] = "bassa"
    else:
        out["confidence"] = "alta" if p >= 0.5 and out["complete"] else "media" if p >= 0.3 else "bassa"
    return out


def stall(work_logs: list, today: date, stato: str, milestones: list) -> Optional[dict]:
    """A site "in corso" standing still or slowing down: no entries for 5 working days, this
    week's hours well under its usual week, or a milestone due within 5 working days and nobody
    there in the last 3."""
    if stato != "in corso":
        return None
    days = sorted({lg.get("date") for lg in work_logs if lg.get("date")})
    last = _d(days[-1]) if days else None
    if not last:
        return {"reason": "nessuna voce di diario"}
    idle = workdays(last, today)
    if idle >= 5:
        return {"reason": f"nessuna voce da {idle} giorni lavorativi", "last": last.isoformat()}
    hours = lambda lo, hi: sum(float(h.get("hours") or 0) for lg in work_logs
                               if lo <= (_d(lg.get("date")) or date.min) <= hi for h in lg.get("hours") or [])
    week_now = hours(today - timedelta(days=6), today)
    weeks = [hours(today - timedelta(days=7 * k + 6), today - timedelta(days=7 * k)) for k in range(1, 9)]
    active = [w for w in weeks if w > 0]
    if len(active) >= 2:
        usual = sum(active) / len(active)
        if usual >= 8 and week_now < 0.4 * usual:
            return {"reason": f"questa settimana {week_now:g} h contro le solite {usual:.0f} h", "last": last.isoformat()}
    soon = [m for m in milestones if not m.get("done") and _d(m.get("due_date"))
            and 0 <= workdays(today, _d(m["due_date"])) <= 5]
    if soon and idle >= 3:
        m = min(soon, key=lambda x: x["due_date"])
        return {"reason": f"«{m['title']}» scade il {_d(m['due_date']).strftime('%d/%m')} e nessuno scrive da {idle} giorni",
                "last": last.isoformat()}
    return None


def forecast(commessa: dict, milestones: list, work_logs: list, econ: dict, reports: list, today: date) -> dict:
    """Everything about where the job is heading, for the diary, its chat and the summaries."""
    first_day = min((lg.get("date") for lg in work_logs if lg.get("date")), default=None)
    start = start_of(commessa, first_day, milestones, today)
    prog = progress(milestones, start, sal_percent(reports))
    out = {"progress": prog, "end": end_forecast(milestones, start, today), "cost": cost_forecast(econ, prog),
           "stall": stall(work_logs, today, commessa.get("stato") or "", milestones), "start": start.isoformat()}
    if not prog:
        out["missing"] = "Per le previsioni servono le milestone (o un SAL con la percentuale di avanzamento)"
    out["line"] = forecast_line(out)
    return out


def _it(iso: str) -> str:
    d = _d(iso)
    return d.strftime("%d/%m/%Y") if d else ""


def _eur(x: Optional[float]) -> str:
    if x is None:
        return "—"
    s = f"{abs(x):,.0f}".replace(",", ".")
    return ("-" if x < 0 else "") + "€ " + s


def forecast_line(f: dict) -> str:
    """One line for the commessa's chat and the Monday summary."""
    parts = []
    p = f.get("progress")
    if p:
        parts.append(f"avanzamento {round(p['value'] * 100)}%" + (" (dall'ultimo SAL)" if p["source"] == "sal" else ""))
    e = f.get("end")
    if e and not e.get("finished"):
        rit = (f", {e['delay_days']} giorni lavorativi dopo il previsto ({_it(e['planned'])})" if e["delay_days"] > 0 else
               f", in anticipo di {-e['delay_days']} giorni" if e["delay_days"] < 0 else ", in linea con il previsto")
        parts.append(f"fine prevista {_it(e['date'])}{rit} (affidabilità {e['confidence']})")
    c = f.get("cost")
    if c and c.get("final"):
        parts.append(f"costo finale previsto {_eur(c['final'])}" + (f" su {_eur(c['budget'])} di preventivo ({c['pct']:.0f}%)" if c.get("budget") else "")
                     + f" (affidabilità {c['confidence']})")
    s = f.get("stall")
    if s:
        parts.append(f"cantiere a rilento: {s['reason']}")
    if not parts and f.get("missing"):
        return f["missing"]
    return "; ".join(parts)
