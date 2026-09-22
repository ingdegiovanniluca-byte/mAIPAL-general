"""Unit tests for usage_tracking.py (cost calc, normalization, llm_calls/feature_events
recording) - the "punto unico di tracciamento" from the usage-tracking spec.

Deliberately NOT following this repo's usual live-integration convention (requests against
a running server + a real MongoDB, see tests/test_iteration*.py): those require a deployed
instance to be up, which this environment doesn't have. These tests instead exercise the
module directly against a tiny in-memory fake standing in for the Motor database, covering
exactly the pieces the spec calls out as needing tests (§13.7): cost calculation and the
tracking wrapper's never-raise/never-lose-a-call guarantees. They run with plain pytest, no
extra dependency, by driving the async functions via asyncio.run() from sync test bodies
(this repo has no pytest-asyncio installed).

Before pushing to a real environment, also do one manual end-to-end check: trigger one web
chat action and one Telegram action, then confirm matching rows appear in `llm_calls` and
`feature_events` - these unit tests cannot substitute for that, since they never touch a
real OpenAI call or a real Mongo instance.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import usage_tracking as ut


class _FakeCursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, n):
        return list(self._docs[:n])


class _FakeCollection:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(dict(doc))
        return doc

    def find(self, query=None, projection=None):
        return _FakeCursor(self.docs)


class _FakeDB:
    def __init__(self):
        self.llm_pricing = _FakeCollection()
        self.llm_calls = _FakeCollection()
        self.feature_events = _FakeCollection()


def _fresh_fake_db():
    """Every test gets its own fake db AND a cleared pricing cache - the 60s in-process
    cache in usage_tracking.py must never leak pricing rows between tests."""
    db = _FakeDB()
    ut._db = db
    ut._pricing_cache = {"at": 0.0, "rows": []}
    return db


def _seed_pricing(db, model="gpt-4o", input_price=2.50, cached_price=1.25, output_price=10.00):
    db.llm_pricing.docs.append({
        "id": f"price_{model}", "model": model,
        "input_per_1m_usd": input_price, "cached_input_per_1m_usd": cached_price,
        "output_per_1m_usd": output_price, "per_minute_usd": None,
        "valid_from": "2020-01-01", "valid_to": None,
    })


# ==== normalization: an unknown value is never lost, it falls back to a safe default ====
def test_norm_feature_falls_back_to_altro():
    assert ut._norm_feature("diario") == "diario"
    assert ut._norm_feature("qualcosa_di_inesistente") == "altro"
    assert ut._norm_feature(None) == "altro"


def test_norm_channel_and_trigger_fallbacks():
    assert ut._norm_channel("telegram") == "telegram"
    assert ut._norm_channel("bogus") == "sistema"
    assert ut._norm_trigger("utente") == "utente"
    assert ut._norm_trigger("bogus") == "automatico"


# ==== cost calculation: exact formula from the spec ====
def test_compute_token_cost_matches_formula():
    pricing = {"input_per_1m_usd": 2.50, "cached_input_per_1m_usd": 1.25, "output_per_1m_usd": 10.00}
    # 1000 input tokens (200 of them cached) + 500 output tokens
    cost = ut._compute_token_cost(pricing, input_tokens=1000, cached_input_tokens=200, output_tokens=500)
    expected = (800 * 2.50 + 200 * 1.25 + 500 * 10.00) / 1_000_000
    assert cost == round(expected, 6)


def test_compute_token_cost_without_cached_price_falls_back_to_input_price():
    pricing = {"input_per_1m_usd": 2.50, "cached_input_per_1m_usd": None, "output_per_1m_usd": 10.00}
    cost = ut._compute_token_cost(pricing, input_tokens=1000, cached_input_tokens=200, output_tokens=0)
    # cached tokens priced as ordinary input tokens when no cached price is configured
    expected = round(1000 * 2.50 / 1_000_000, 6)
    assert cost == expected


def test_compute_token_cost_none_when_pricing_incomplete():
    assert ut._compute_token_cost({"input_per_1m_usd": None, "output_per_1m_usd": 10.0}, 100, 0, 100) is None


def test_compute_minute_cost():
    pricing = {"per_minute_usd": 0.006}
    cost = ut._compute_minute_cost(pricing, duration_seconds=90)  # 1.5 minutes
    assert cost == round(1.5 * 0.006, 6)
    assert ut._compute_minute_cost(pricing, duration_seconds=None) is None
    assert ut._compute_minute_cost({"per_minute_usd": None}, duration_seconds=60) is None


# ==== track_llm_call: never loses a call, cost computed from configured pricing ====
def test_track_llm_call_records_row_with_cost():
    db = _fresh_fake_db()
    _seed_pricing(db)
    asyncio.run(ut.track_llm_call(
        user_id="user_1", feature="diario", channel="web", trigger="utente",
        model="gpt-4o", endpoint="chat.completions",
        input_tokens=1000, cached_input_tokens=0, output_tokens=500,
    ))
    assert len(db.llm_calls.docs) == 1
    row = db.llm_calls.docs[0]
    assert row["feature"] == "diario"
    assert row["total_tokens"] == 1500
    assert row["cost_usd"] == round((1000 * 2.50 + 500 * 10.00) / 1_000_000, 6)
    assert row["status"] == "ok"


def test_track_llm_call_without_pricing_still_records_row_with_null_cost():
    """A model with no pricing row must NEVER cause the call to be lost - it's recorded
    with cost_usd=None so the dashboard can flag it, per the spec."""
    db = _fresh_fake_db()  # no pricing seeded
    asyncio.run(ut.track_llm_call(
        user_id="user_1", feature="diario", channel="web", trigger="utente",
        model="some-unpriced-model", endpoint="chat.completions",
        input_tokens=10, cached_input_tokens=0, output_tokens=10,
    ))
    assert len(db.llm_calls.docs) == 1
    assert db.llm_calls.docs[0]["cost_usd"] is None


def test_track_llm_call_records_errors_too():
    db = _fresh_fake_db()
    _seed_pricing(db)
    asyncio.run(ut.track_llm_call(
        user_id="user_1", feature="creazione_task", channel="telegram", trigger="utente",
        model="gpt-4o", endpoint="chat.completions",
        input_tokens=0, cached_input_tokens=0, output_tokens=0, status="errore",
    ))
    assert db.llm_calls.docs[0]["status"] == "errore"


def test_track_llm_call_unknown_feature_falls_back_to_altro_but_is_never_dropped():
    db = _fresh_fake_db()
    _seed_pricing(db)
    asyncio.run(ut.track_llm_call(
        user_id="user_1", feature="not_a_real_feature", channel="web", trigger="utente",
        model="gpt-4o", endpoint="chat.completions", input_tokens=1, output_tokens=1,
    ))
    assert db.llm_calls.docs[0]["feature"] == "altro"


# ==== track_feature_event: one row per feature use ====
def test_track_feature_event_records_row_and_returns_id():
    db = _fresh_fake_db()
    event_id = asyncio.run(ut.track_feature_event(user_id="user_1", feature="diario", channel="web", trigger="utente"))
    assert event_id and event_id.startswith("fev_")
    assert len(db.feature_events.docs) == 1
    assert db.feature_events.docs[0]["feature"] == "diario"


def test_track_feature_event_without_user_id_is_skipped_not_crashed():
    db = _fresh_fake_db()
    event_id = asyncio.run(ut.track_feature_event(user_id=None, feature="diario", channel="web", trigger="utente"))
    assert event_id is None
    assert len(db.feature_events.docs) == 0


# ==== pricing lookup: exact match, then prefix fallback for dated snapshot model names ====
def test_pricing_for_model_prefix_fallback():
    db = _fresh_fake_db()
    _seed_pricing(db, model="gpt-4o")
    pricing = asyncio.run(ut._pricing_for_model("gpt-4o-2024-08-06"))
    assert pricing is not None
    assert pricing["model"] == "gpt-4o"


def test_pricing_for_model_respects_valid_to():
    db = _fresh_fake_db()
    db.llm_pricing.docs.append({
        "id": "price_old", "model": "gpt-4o", "input_per_1m_usd": 5.0, "cached_input_per_1m_usd": 2.5,
        "output_per_1m_usd": 15.0, "per_minute_usd": None, "valid_from": "2020-01-01", "valid_to": "2020-12-31",
    })
    pricing = asyncio.run(ut._pricing_for_model("gpt-4o"))
    assert pricing is None  # expired row must not be picked up
