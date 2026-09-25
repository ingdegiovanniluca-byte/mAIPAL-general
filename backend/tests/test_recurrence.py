"""Recurring tasks: rule validation, occurrence dates, labels and Google Calendar RRULEs.
Run with: python -m pytest tests/test_recurrence.py -q
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import recurrence as rec  # noqa: E402

MON = date(2026, 9, 28)  # a Monday


def test_weekly_defaults_to_the_start_weekday():
    assert rec.normalize_rule({"freq": "weekly"}, MON) == {"freq": "weekly", "interval": 1, "weekdays": [0]}
    assert rec.normalize_rule({"freq": "weekly"}) is None
    assert rec.normalize_rule({"freq": "weekly", "weekdays": list(range(7))}, MON) == {"freq": "daily", "interval": 1}
    assert rec.normalize_rule({"freq": "hourly"}, MON) is None


def test_every_monday():
    rule = rec.normalize_rule({"freq": "weekly", "weekdays": [0]}, MON)
    assert rec.occurrences(rule, MON, MON, date(2026, 10, 20)) == [date(2026, 9, 28), date(2026, 10, 5), date(2026, 10, 12), date(2026, 10, 19)]


def test_monday_and_wednesday_every_two_weeks():
    rule = rec.normalize_rule({"freq": "weekly", "interval": 2, "weekdays": [0, 2]}, MON)
    assert rec.occurrences(rule, MON, MON, date(2026, 10, 25)) == [date(2026, 9, 28), date(2026, 9, 30), date(2026, 10, 12), date(2026, 10, 14)]


def test_start_is_always_the_first_occurrence():
    thu = date(2026, 10, 1)
    rule = rec.normalize_rule({"freq": "weekly", "weekdays": [0]}, thu)
    assert rec.occurrences(rule, thu, thu, date(2026, 10, 13)) == [thu, date(2026, 10, 5), date(2026, 10, 12)]


def test_until_and_count():
    rule = rec.normalize_rule({"freq": "daily", "until": "2026-09-30"}, MON)
    assert rec.occurrences(rule, MON, MON, date(2026, 12, 31)) == [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)]
    rule = rec.normalize_rule({"freq": "weekly", "count": 3}, MON)
    got = rec.occurrences(rule, MON, date(2026, 10, 6), date(2026, 12, 31))
    assert got == [date(2026, 10, 12)]  # 3rd and last occurrence; the first two are before from_date
    assert rec.is_finished(rule, MON, date(2026, 10, 12))


def test_monthly_31st_and_last_day():
    start = date(2026, 1, 31)
    rule = rec.normalize_rule({"freq": "monthly"}, start)
    assert rule["day_of_month"] == 31
    assert rec.occurrences(rule, start, start, date(2026, 4, 30)) == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)]
    last = rec.normalize_rule({"freq": "monthly", "day_of_month": -1}, start)
    assert rec.occurrences(last, start, date(2026, 2, 1), date(2026, 2, 28)) == [date(2026, 2, 28)]


def test_yearly_on_29_february():
    start = date(2028, 2, 29)
    rule = rec.normalize_rule({"freq": "yearly"}, start)
    assert rec.occurrences(rule, start, date(2029, 1, 1), date(2029, 12, 31)) == [date(2029, 2, 28)]


def test_first_occurrence_from_today():
    fri = date(2026, 9, 25)
    assert rec.first_occurrence({"freq": "weekly", "weekdays": [0]}, fri) == "2026-09-28"
    assert rec.first_occurrence({"freq": "weekly", "weekdays": [4]}, fri) == "2026-09-25"
    assert rec.first_occurrence({"freq": "monthly", "day_of_month": 1}, fri) == "2026-10-01"


def test_labels():
    assert rec.rule_label({"freq": "weekly", "interval": 1, "weekdays": [0]}) == "Ogni lunedì"
    assert rec.rule_label({"freq": "weekly", "interval": 1, "weekdays": [0, 2, 4]}) == "Ogni lunedì, mercoledì e venerdì"
    assert rec.rule_label({"freq": "weekly", "interval": 1, "weekdays": [0, 1, 2, 3, 4]}) == "Dal lunedì al venerdì"
    assert rec.rule_label({"freq": "daily", "interval": 1, "until": "2026-12-31"}) == "Ogni giorno, fino al 31 dicembre 2026"
    assert rec.rule_label({"freq": "monthly", "interval": 1, "day_of_month": -1}) == "Ogni mese l'ultimo giorno"
    assert rec.rule_label({"freq": "yearly", "interval": 1}, date(2026, 10, 3)) == "Ogni anno il 3 ottobre"


def test_rrule():
    assert rec.to_rrule({"freq": "weekly", "interval": 1, "weekdays": [0, 2]}) == "RRULE:FREQ=WEEKLY;BYDAY=MO,WE"
    assert rec.to_rrule({"freq": "daily", "interval": 2, "until": "2026-12-31"}) == "RRULE:FREQ=DAILY;INTERVAL=2;UNTIL=20261231T235959Z"
    assert rec.to_rrule({"freq": "monthly", "interval": 1, "day_of_month": 31}) == "RRULE:FREQ=MONTHLY;BYMONTHDAY=28,29,30,31;BYSETPOS=-1"
    assert rec.to_rrule({"freq": "monthly", "interval": 1, "day_of_month": 5, "count": 4}) == "RRULE:FREQ=MONTHLY;BYMONTHDAY=5;COUNT=4"
