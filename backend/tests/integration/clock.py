"""A fixed clock for the integration scripts whose steps depend on the time of day (reminders "from 8:00", the day's
pinned message at 6:00, "ho finito alle 7:30"): set_time(10, 0) makes every module see that time of TODAY (Rome) from now
on, the clock still running from there - so a script passes at any hour it is run."""
import sys
import time
from datetime import datetime as _dt, timezone
from zoneinfo import ZoneInfo

ROME = ZoneInfo("Europe/Rome")


def set_time(hour: int, minute: int = 0, modules=("server", "job_logs", "site_presence", "collab_telegram", "telegram_bot",
                                                  "team_presence_tg", "scheduled_actions")) -> None:
    start = _dt.now(ROME).replace(hour=hour, minute=minute, second=0, microsecond=0)
    t0 = time.monotonic()

    class FixedDateTime(_dt):
        @classmethod
        def now(cls, tz=None):
            t = start.astimezone(timezone.utc) + __import__("datetime").timedelta(seconds=time.monotonic() - t0)
            t = _dt(t.year, t.month, t.day, t.hour, t.minute, t.second, t.microsecond, tzinfo=timezone.utc)
            out = t.astimezone(tz) if tz else t.astimezone(ROME).replace(tzinfo=None)
            return cls(out.year, out.month, out.day, out.hour, out.minute, out.second, out.microsecond, tzinfo=out.tzinfo)

        @classmethod
        def utcnow(cls):
            return cls.now(timezone.utc).replace(tzinfo=None)

    for name in modules:
        mod = sys.modules.get(name)
        if mod is not None and getattr(mod, "datetime", None) is _dt:
            mod.datetime = FixedDateTime
    me = sys.modules.get("__main__")
    if me is not None and getattr(me, "datetime", None) is _dt:
        me.datetime = FixedDateTime
