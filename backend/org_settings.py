"""The organization's settings for the commesse automations (specifica commesse, cap. 7): times,
tolerances, thresholds and the rules decided by the owner. Every automation reads them from
here, never from a constant - each organization (tenants.settings) can change them.
Kept free of server imports so it can be tested on its own.
"""
import re
from typing import Optional

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

DEFAULTS = {
    # times (HH:MM, Europe/Rome)
    "default_start_time": "09:00",            # expected start on site when nothing else says it
    "max_presence_hours": 9,                  # expected end = check-in + this, when nothing else says it
    "checkin_tolerance_minutes": 30,          # no check-in by start + this: missed arrival
    "checkout_tolerance_minutes": 30,         # no check-out by end + this: missed exit
    "day_before_reminder_time": "18:00",      # the activity's reminder the day before (G-1)
    "confirmation_nudge_time": "21:00",       # no answer to the G-1 reminder: asked again
    "confirmation_admin_alert_time": "07:00", # still no answer the day itself: the administrator is told
    "daily_message_time": "07:00",            # the pinned message of the day...
    "daily_message_lead_minutes": 60,         # ...or this long before the first start, if earlier
    "missing_notes_time": "19:00",            # on site without a note: "com'è andata?"
    "daily_summary_time": "20:00",            # the evening summary to the administrator, by site
    "weekly_report_day": "FRI",               # the weekly report, the client's draft, the next week's plan
    "weekly_report_time": "18:00",
    "quote_followup_days": 7,                 # a quote without outcome: asked again every N days
    "quote_followup_max": 4,                  # at most this many times
    "weather_alert_rain_pct": 60,             # rain probability that may stop the works
    "weather_alert_wind_kmh": 40,             # wind that may stop the works
    "weather_alert_temp_min": 0,              # below this (°C) the works may stop
    "weather_alert_temp_max": 35,             # above this (°C)
    "working_days": ["MON", "TUE", "WED", "THU", "FRI"],
    "timezone": "Europe/Rome",
    "lunch_break_minutes": 0,                 # PA-04: taken off the hours on site (0 = not)
    # rules
    "save_position": True,                    # the 📍 button keeps the position (C.4)
    "client_report_approval": True,           # the client's weekly message waits for approval (C.2)
}

_TIME_KEYS = {k for k, v in DEFAULTS.items() if isinstance(v, str) and re.fullmatch(r"\d\d:\d\d", v)}
_INT_LIMITS = {"max_presence_hours": (1, 24), "checkin_tolerance_minutes": (0, 240), "checkout_tolerance_minutes": (0, 240),
               "daily_message_lead_minutes": (0, 240), "quote_followup_days": (1, 60), "quote_followup_max": (0, 20),
               "weather_alert_rain_pct": (0, 100), "weather_alert_wind_kmh": (0, 200), "weather_alert_temp_min": (-30, 30),
               "weather_alert_temp_max": (10, 60), "lunch_break_minutes": (0, 180)}


def settings(tenant: Optional[dict]) -> dict:
    """The organization's settings: its own over the defaults."""
    return {**DEFAULTS, **{k: v for k, v in ((tenant or {}).get("settings") or {}).items() if k in DEFAULTS}}


def clean(patch: dict) -> dict:
    """Validates a change -> the values to store. ValueError with an Italian message when wrong."""
    out = {}
    for k, v in (patch or {}).items():
        if k not in DEFAULTS:
            continue
        if k in _TIME_KEYS:
            m = re.fullmatch(r"(\d{1,2})[:.](\d{2})", str(v or "").strip())
            if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
                raise ValueError(f"Orario non valido: {v}")
            out[k] = f"{int(m.group(1)):02d}:{m.group(2)}"
        elif k in _INT_LIMITS:
            try:
                n = int(v)
            except (TypeError, ValueError):
                raise ValueError(f"Valore non valido: {v}")
            lo, hi = _INT_LIMITS[k]
            if not lo <= n <= hi:
                raise ValueError(f"Il valore deve essere tra {lo} e {hi}")
            out[k] = n
        elif k == "weekly_report_day":
            if str(v).upper() not in WEEKDAYS:
                raise ValueError("Giorno non valido")
            out[k] = str(v).upper()
        elif k == "working_days":
            days = [str(d).upper() for d in (v or [])]
            if not days or any(d not in WEEKDAYS for d in days):
                raise ValueError("Giorni lavorativi non validi")
            out[k] = [d for d in WEEKDAYS if d in days]
        elif k == "timezone":
            out[k] = "Europe/Rome"            # the only one supported for now
        elif isinstance(DEFAULTS[k], bool):
            out[k] = bool(v)
    return out


def is_working_day(s: dict, d) -> bool:
    return WEEKDAYS[d.weekday()] in (s.get("working_days") or DEFAULTS["working_days"])


def minutes(hhmm: str) -> int:
    h, m = (int(x) for x in str(hhmm or "00:00").split(":")[:2])
    return h * 60 + m


def hhmm(total_minutes: int) -> str:
    total_minutes = max(0, min(int(total_minutes), 23 * 60 + 59))
    return f"{total_minutes // 60:02d}:{total_minutes % 60:02d}"
