"""Suggerimenti "per te" che scorrono sopra la chat (mobile).

Two layers:
- build_rule_suggestions: deterministic, free, recomputed on every request from the user's
  tasks, to-dos, today's news, the diary and the scheduled actions.
- AI insights (server.py, once a day, cached): short links between saved information and
  what is coming up ("domani chiami Marco: nell'ultima nota aspettava il preventivo").

Every suggestion is {"id", "kind", "text", "target", "priority"}; `target` says what a tap
does: {"type": "task", "id"} | {"type": "page", "to"} | {"type": "url", "url"} |
{"type": "chat", "action", "text"}.
"""
from datetime import date, datetime, timedelta
from typing import Optional

IT_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
             "settembre", "ottobre", "novembre", "dicembre"]

TIPS = [
    ("Prova: «ogni lunedì alle 9 ricordami di chiamare il fornitore» crea un task ricorrente",
     {"type": "chat", "action": "task_todo", "text": "Ogni lunedì alle 9 ricordami di "}),
    ("Chiedimi qualcosa che hai salvato, es. «qual è il codice del wifi?»",
     {"type": "chat", "action": "info_request", "text": ""}),
    ("Con Azioni programmate faccio da solo un compito ogni settimana, finché non mi fermi",
     {"type": "chat", "action": "scheduled_action", "text": ""}),
]


def _q(title: str, n: int = 60) -> str:
    t = " ".join(str(title or "").split())
    return f"«{t[:n - 1]}…»" if len(t) > n else f"«{t}»"


def _open(t: dict) -> bool:
    return not t.get("completed")


def build_rule_suggestions(today: date, now_local: datetime, tasks: list, todos: list, news: list,
                           journal_past: list, actions: list) -> list[dict]:
    out = []
    iso = today.isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()
    open_tasks = [t for t in tasks if _open(t) and t.get("due_date")]

    overdue = sorted([t for t in open_tasks if t["due_date"] < iso], key=lambda t: (t["due_date"], t.get("due_time") or ""))
    if overdue:
        oldest = overdue[0]
        text = (f"Hai un task scaduto: {_q(oldest.get('title'))}" if len(overdue) == 1
                else f"{len(overdue)} task scaduti, il più vecchio è {_q(oldest.get('title'), 45)}")
        out.append({"id": "overdue", "kind": "task", "text": text, "target": {"type": "task", "id": oldest["id"]}, "priority": 100})

    today_tasks = sorted([t for t in open_tasks if t["due_date"] == iso], key=lambda t: t.get("due_time") or "99:99")
    if today_tasks:
        now_hm = now_local.strftime("%H:%M")
        nxt = next((t for t in today_tasks if (t.get("due_time") or "99:99") >= now_hm), today_tasks[0])
        at = f" alle {nxt['due_time']}" if nxt.get("due_time") else ""
        text = (f"Oggi: {_q(nxt.get('title'))}{at}" if len(today_tasks) == 1
                else f"Oggi hai {len(today_tasks)} task, il prossimo è {_q(nxt.get('title'), 45)}{at}")
        out.append({"id": "today", "kind": "task", "text": text, "target": {"type": "task", "id": nxt["id"]}, "priority": 90})

    tomorrow_tasks = sorted([t for t in open_tasks if t["due_date"] == tomorrow], key=lambda t: t.get("due_time") or "99:99")
    if tomorrow_tasks:
        first = tomorrow_tasks[0]
        at = f" alle {first['due_time']}" if first.get("due_time") else ""
        text = (f"Domani: {_q(first.get('title'))}{at}" if len(tomorrow_tasks) == 1
                else f"Domani hai {len(tomorrow_tasks)} task, si parte con {_q(first.get('title'), 45)}{at}")
        out.append({"id": "tomorrow", "kind": "task", "text": text, "target": {"type": "task", "id": first["id"]}, "priority": 60})

    def _age(t) -> Optional[int]:
        try:
            return (today - datetime.fromisoformat(str(t.get("created_at")).replace("Z", "+00:00")).date()).days
        except (ValueError, TypeError):
            return None
    stuck = [(a, t) for t in todos if t.get("status") in ("da_fare", "in_corso") for a in [_age(t)] if a is not None and a >= 7]
    if stuck:
        age, t = max(stuck, key=lambda x: x[0])
        out.append({"id": "todo", "kind": "todo", "text": f"To-Do fermo da {age} giorni: {_q(t.get('title'))}",
                    "target": {"type": "page", "to": "/dashboard/todos"}, "priority": 50})

    todays_news = [n for n in news if n.get("date") == iso and n.get("feedback") != "dislike"]
    if todays_news:
        n0 = todays_news[0]
        text = f"News di oggi: {_q(n0.get('title'), 70)}" + (f" e altre {len(todays_news) - 1}" if len(todays_news) > 1 else "")
        target = {"type": "url", "url": n0["url"]} if n0.get("url") else {"type": "page", "to": "/dashboard/news"}
        out.append({"id": "news", "kind": "news", "text": text, "target": target, "priority": 40})

    for years in (1, 2, 3):
        try:
            past = today.replace(year=today.year - years).isoformat()
        except ValueError:  # 29 febbraio
            continue
        hit = next((j for j in journal_past if j.get("date") == past), None)
        if hit:
            what = hit.get("title") or hit.get("summary") or hit.get("cleaned_text") or ""
            when = "Un anno fa" if years == 1 else f"{years} anni fa"
            out.append({"id": f"diary{years}", "kind": "journal", "text": f"{when} nel diario: {_q(what, 55)}",
                        "target": {"type": "page", "to": "/dashboard/journal", "date": past}, "priority": 45})
            break

    soon = []
    for a in actions:
        if not a.get("enabled") or not a.get("next_run_at"):
            continue
        try:
            at = datetime.fromisoformat(a["next_run_at"]).astimezone(now_local.tzinfo)
        except (ValueError, TypeError):
            continue
        if now_local <= at <= now_local + timedelta(hours=24):
            soon.append((at, a))
    if soon:
        at, a = min(soon, key=lambda x: x[0])
        when = "Stanotte" if at.hour < 6 and at.date() != now_local.date() else ("Oggi" if at.date() == now_local.date() else "Domani")
        out.append({"id": "action", "kind": "action", "text": f"{when} alle {at.strftime('%H:%M')} parte l'azione {_q(a.get('title'), 45)}",
                    "target": {"type": "page", "to": "/dashboard/azioni"}, "priority": 35})
    return out


def with_tips(items: list[dict], today: date, minimum: int = 3) -> list[dict]:
    """Tops a short list up with tips on what the app can do (a different one each day)."""
    out = list(items)
    k = today.toordinal()
    i = 0
    while len(out) < minimum and i < len(TIPS):
        text, target = TIPS[(k + i) % len(TIPS)]
        out.append({"id": f"tip{(k + i) % len(TIPS)}", "kind": "tip", "text": text, "target": target, "priority": 5})
        i += 1
    return out
