"""Chat vecchie: una conversazione NON preferita si cancella da sola 10 giorni dopo il suo
ultimo messaggio (non dalla creazione: una chat ripresa ieri resta). Cancellare la chat
toglie solo la conversazione - note, task, diario e liste creati da essa restano."""
from datetime import datetime, timedelta, timezone
from typing import Optional

RETENTION_DAYS = 10


def _parse(ts) -> Optional[datetime]:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def last_activity(conv: dict) -> Optional[datetime]:
    stamps = [conv.get("created_at"), conv.get("completed_at")] + [m.get("ts") for m in (conv.get("messages") or [])]
    parsed = [p for p in (_parse(s) for s in stamps if s) if p]
    return max(parsed) if parsed else None


def is_expired(conv: dict, now: datetime, days: int = RETENTION_DAYS) -> bool:
    if conv.get("favorite"):
        return False
    last = last_activity(conv)
    return last is not None and last < now - timedelta(days=days)
