"""Old non-favorite chats are deleted 10 days after their LAST message.
Run with: python -m pytest tests/test_conversation_retention.py -q
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import conversation_retention as cr  # noqa: E402

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)


def test_old_chat_expires():
    assert cr.is_expired({"created_at": "2026-09-10T10:00:00+00:00", "messages": [{"ts": "2026-09-10T10:01:00+00:00"}]}, NOW)


def test_favorite_never_expires():
    assert not cr.is_expired({"favorite": True, "created_at": "2026-01-01T10:00:00+00:00"}, NOW)


def test_counted_from_the_last_message_not_creation():
    conv = {"created_at": "2026-08-01T10:00:00+00:00",
            "messages": [{"ts": "2026-08-01T10:00:00+00:00"}, {"ts": "2026-09-20T09:00:00+00:00"}]}
    assert not cr.is_expired(conv, NOW)


def test_exactly_within_ten_days_stays():
    assert not cr.is_expired({"created_at": "2026-09-16T10:00:00+00:00"}, NOW)
    assert cr.is_expired({"created_at": "2026-09-15T11:59:00+00:00"}, NOW)


def test_no_dates_is_left_alone():
    assert not cr.is_expired({"messages": []}, NOW)
