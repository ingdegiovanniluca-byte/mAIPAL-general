"""Rule-based "per te" suggestions shown above the chat on mobile.
Run with: python -m pytest tests/test_suggestions.py -q
"""
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import suggestions as sg  # noqa: E402

ROME = ZoneInfo("Europe/Rome")
TODAY = date(2026, 9, 25)
NOW = datetime(2026, 9, 25, 10, 0, tzinfo=ROME)


def _run(tasks=(), todos=(), news=(), journal=(), actions=()):
    return {s["id"]: s for s in sg.build_rule_suggestions(TODAY, NOW, list(tasks), list(todos), list(news), list(journal), list(actions))}


def test_overdue_today_tomorrow():
    tasks = [
        {"id": "a", "title": "Rinnovo assicurazione", "due_date": "2026-09-20"},
        {"id": "b", "title": "Bolletta", "due_date": "2026-09-22"},
        {"id": "c", "title": "Palestra", "due_date": "2026-09-25", "due_time": "18:00"},
        {"id": "d", "title": "Chiamare Marco", "due_date": "2026-09-25", "due_time": "09:00"},
        {"id": "e", "title": "Dentista", "due_date": "2026-09-26", "due_time": "15:30"},
        {"id": "f", "title": "Fatto", "due_date": "2026-09-19", "completed": True},
    ]
    s = _run(tasks)
    assert s["overdue"]["text"].startswith("2 task scaduti") and s["overdue"]["target"] == {"type": "task", "id": "a"}
    # 09:00 is already past at 10:00 -> the next one is Palestra at 18:00
    assert "Palestra" in s["today"]["text"] and "18:00" in s["today"]["text"]
    assert s["tomorrow"]["text"] == "Domani: «Dentista» alle 15:30"


def test_stuck_todo_news_diary_action():
    s = _run(
        todos=[{"id": "t", "title": "Preventivo", "status": "da_fare", "created_at": "2026-09-10T08:00:00+00:00"},
               {"id": "u", "title": "Nuovo", "status": "da_fare", "created_at": "2026-09-24T08:00:00+00:00"}],
        news=[{"title": "Nuove regole per le partite IVA", "url": "https://x", "date": "2026-09-25"},
              {"title": "Altro", "url": "https://y", "date": "2026-09-25"}],
        journal=[{"date": "2025-09-25", "title": "Giornata al mare"}],
        actions=[{"title": "Svuota iscritti", "enabled": True, "next_run_at": "2026-09-25T23:00:00+00:00"}],
    )
    assert s["todo"]["text"] == "To-Do fermo da 15 giorni: «Preventivo»"
    assert s["news"]["target"] == {"type": "url", "url": "https://x"} and "altre 1" in s["news"]["text"]
    assert s["diary1"]["text"] == "Un anno fa nel diario: «Giornata al mare»"
    assert s["action"]["text"] == "Stanotte alle 01:00 parte l'azione «Svuota iscritti»"


def test_tips_fill_a_short_list():
    items = sg.with_tips([], TODAY)
    assert len(items) == 3 and all(i["kind"] == "tip" for i in items)
    assert len(sg.with_tips([{"id": x} for x in "abc"], TODAY)) == 3
