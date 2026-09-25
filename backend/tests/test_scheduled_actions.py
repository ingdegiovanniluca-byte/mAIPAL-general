"""Deterministic parts of the scheduled actions ("Azioni"): schedule validation, next run
computation (local time, DST, short months, midnight), report periods and the sums the
report model is never allowed to compute itself. Run with:
    python -m pytest tests/test_scheduled_actions.py -q
"""
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import scheduled_actions as sa  # noqa: E402

ROME = ZoneInfo("Europe/Rome")


def local(y, m, d, hh=0, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ROME)


def test_normalize_schedule_validates_and_simplifies():
    assert sa.normalize_schedule({"freq": "weekly", "weekdays": [4], "time": "1:00"}) == {"freq": "weekly", "weekdays": [4], "time": "01:00"}
    assert sa.normalize_schedule({"freq": "weekly", "weekdays": list(range(7)), "time": "08:00"})["freq"] == "daily"
    assert sa.normalize_schedule({"freq": "daily", "time": "24:00"}) == {"freq": "daily", "time": "00:00"}
    assert sa.normalize_schedule({"freq": "weekly", "weekdays": [], "time": "08:00"}) is None
    assert sa.normalize_schedule({"freq": "hourly", "time": "08:00"}) is None
    assert sa.normalize_schedule({"freq": "monthly", "day_of_month": 32, "time": "08:00"}) is None
    assert sa.normalize_schedule({"freq": "daily", "time": "25:00"}) is None


def test_every_friday_at_one_am():
    s = sa.normalize_schedule({"freq": "weekly", "weekdays": [4], "time": "01:00"})
    # Friday 25 Sep 2026, 13:00 -> next is Friday 2 Oct at 01:00 local
    nxt = sa.next_run_after(s, local(2026, 9, 25, 13, 0))
    assert nxt.astimezone(ROME) == local(2026, 10, 2, 1, 0)
    # right before it on the same Friday -> that same night
    assert sa.next_run_after(s, local(2026, 9, 25, 0, 30)).astimezone(ROME) == local(2026, 9, 25, 1, 0)


def test_sunday_midnight_runs_monday_0000_and_covers_the_week_just_ended():
    s = sa.normalize_schedule({"freq": "weekly", "weekdays": [0], "time": "00:00"})
    nxt = sa.next_run_after(s, local(2026, 9, 25, 13, 0)).astimezone(ROME)
    assert nxt == local(2026, 9, 28, 0, 0)  # Monday
    start, end, label = sa.period_range("last_week", nxt)
    assert (start, end) == (date(2026, 9, 21), date(2026, 9, 27))  # Mon 21 - Sun 27
    assert "settimana passata" in label
    assert "mezzanotte" in sa.schedule_label(s) and "domenica" in sa.schedule_label(s)


def test_local_time_is_kept_across_dst_change():
    s = sa.normalize_schedule({"freq": "daily", "time": "09:00"})
    # DST ends in Italy on Sunday 25 Oct 2026
    before = sa.next_run_after(s, local(2026, 10, 23, 10, 0))  # -> sat 24 (CEST)
    after = sa.next_run_after(s, before)
    assert before.astimezone(ROME).hour == 9 and after.astimezone(ROME).hour == 9
    assert before.hour == 7 and after.hour == 8  # UTC shifts, local time doesn't


def test_monthly_31st_falls_back_to_last_day_and_last_day_option():
    s31 = sa.normalize_schedule({"freq": "monthly", "day_of_month": 31, "time": "09:00"})
    assert sa.next_run_after(s31, local(2026, 9, 1)).astimezone(ROME) == local(2026, 9, 30, 9, 0)
    last = sa.normalize_schedule({"freq": "monthly", "day_of_month": -1, "time": "20:00"})
    assert sa.next_run_after(last, local(2027, 2, 1)).astimezone(ROME) == local(2027, 2, 28, 20, 0)


def test_once_in_the_past_has_no_next_run():
    s = sa.normalize_schedule({"freq": "once", "date": "2026-09-20", "time": "09:00"})
    assert sa.next_run_after(s, local(2026, 9, 25)) is None
    s2 = sa.normalize_schedule({"freq": "once", "date": "2026-10-01", "time": "09:00"})
    assert sa.next_run_after(s2, local(2026, 9, 25)).astimezone(ROME) == local(2026, 10, 1, 9, 0)


def test_next_run_is_always_utc_and_strictly_after():
    s = sa.normalize_schedule({"freq": "daily", "time": "10:00"})
    at = local(2026, 9, 25, 10, 0).astimezone(timezone.utc)
    nxt = sa.next_run_after(s, at)
    assert nxt.tzinfo == timezone.utc and nxt > at


def test_schedule_labels():
    assert sa.schedule_label({"freq": "weekly", "weekdays": [4], "time": "01:00"}) == "Ogni venerdì alle 01:00"
    assert sa.schedule_label({"freq": "weekly", "weekdays": [0, 1, 2, 3, 4], "time": "08:00"}) == "Dal lunedì al venerdì alle 08:00"
    assert sa.schedule_label({"freq": "daily", "time": "07:30"}) == "Ogni giorno alle 07:30"
    assert "ultimo giorno" in sa.schedule_label({"freq": "monthly", "day_of_month": -1, "time": "09:00"})


def test_periods():
    run = local(2026, 10, 1, 9, 0)  # Thursday
    assert sa.period_range("yesterday", run)[:2] == (date(2026, 9, 30), date(2026, 9, 30))
    assert sa.period_range("this_week", run)[:2] == (date(2026, 9, 28), date(2026, 10, 1))
    assert sa.period_range("last_month", run)[:2] == (date(2026, 9, 1), date(2026, 9, 30))
    assert sa.period_range("last_7_days", run)[:2] == (date(2026, 9, 24), date(2026, 9, 30))
    assert sa.period_range("none", run) is None


def test_totals_are_computed_not_trusted_to_the_model():
    msg = "Spese: • spesa 23,40 € • benzina 50 € • farmacia 12.35 €\n*Totale: {{T1}} €*"
    out = sa.fill_totals(msg, [{"key": "T1", "values": ["23,40", 50, "12.35 €"]}])
    assert out.endswith("*Totale: 85,75 €*")
    assert sa.fill_totals("{{T1}} e {{T9}}", [{"key": "T1", "values": [1000, 234.5]}]) == "1.234,50 e ?"


def test_number_parsing():
    assert sa._to_number("1.234,50") == 1234.5
    assert sa._to_number("1,234.50") == 1234.5
    assert sa._to_number("€ 12") == 12.0
    assert sa._to_number("abc") is None
    assert sa.format_number_it(1234) == "1.234"
    assert sa.format_number_it(0.1 + 0.2) == "0,30"
