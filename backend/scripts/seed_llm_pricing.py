"""One-off script that seeds/updates the `llm_pricing` collection used by usage_tracking.py
to cost every tracked LLM call. This project has no migration framework (MongoDB is used
fully schema-less, with collections created implicitly on first insert - confirmed by
inspection: there is no init_db/schema-version anywhere in the codebase), so this plain
script is the closest equivalent to a "migration" for pricing data, run manually:

    cd backend && python3 scripts/seed_llm_pricing.py

Safe to re-run: it upserts by (model, valid_from), it never rewrites a model's existing
valid_from/valid_to (so historical costs already computed from an OLD row are never
altered), and it only ever CLOSES a price row's valid_to (via update_price_and_reseed
below) rather than mutating a price in place - exactly the spec's requirement that
"un aggiornamento di prezzo non deve mai alterare i costi storici già calcolati".

Prices verified 2026-09-22 against https://developers.openai.com/api/docs/pricing.md
(USD, per 1,000,000 tokens for chat models; per-minute for whisper-1).
"""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# model -> pricing row (USD). Token prices are per 1,000,000 tokens; whisper-1 uses
# per_minute_usd instead (it bills by audio duration, not tokens - see usage_tracking.py's
# _compute_minute_cost). valid_from is today unless this model already has a row (then the
# existing valid_from is kept - see main()).
PRICING = [
    {"model": "gpt-4o", "input_per_1m_usd": 2.50, "cached_input_per_1m_usd": 1.25, "output_per_1m_usd": 10.00, "per_minute_usd": None},
    {"model": "gpt-4o-mini", "input_per_1m_usd": 0.15, "cached_input_per_1m_usd": 0.075, "output_per_1m_usd": 0.60, "per_minute_usd": None},
    {"model": "whisper-1", "input_per_1m_usd": None, "cached_input_per_1m_usd": None, "output_per_1m_usd": None, "per_minute_usd": 0.006},
]


async def main():
    mongo_url = os.environ["MONGO_URL"]
    db_name = os.environ["DB_NAME"]
    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    today = datetime.now(timezone.utc).date().isoformat()
    seeded, skipped = [], []
    for p in PRICING:
        existing = await db.llm_pricing.find_one({"model": p["model"], "valid_to": None}, {"_id": 0})
        if existing:
            # A currently-open row for this model already exists - leave it untouched
            # (don't silently overwrite a price someone may have already customized) unless
            # --force is passed.
            if "--force" not in sys.argv:
                skipped.append(p["model"])
                continue
            await db.llm_pricing.update_one(
                {"id": existing["id"]},
                {"$set": {k: v for k, v in p.items() if k != "model"}},
            )
            seeded.append(f"{p['model']} (updated in place, --force)")
            continue
        row_id = f"price_{p['model'].replace('.', '_')}_{today.replace('-', '')}"
        await db.llm_pricing.insert_one({
            "id": row_id,
            "model": p["model"],
            "input_per_1m_usd": p["input_per_1m_usd"],
            "cached_input_per_1m_usd": p["cached_input_per_1m_usd"],
            "output_per_1m_usd": p["output_per_1m_usd"],
            "per_minute_usd": p["per_minute_usd"],
            "valid_from": today,
            "valid_to": None,
        })
        seeded.append(p["model"])

    print(f"Seeded: {seeded or '(none)'}")
    print(f"Already present, left untouched: {skipped or '(none)'}")
    if skipped:
        print("Run with --force to update an already-present model's price in place "
              "(only do this to fix a typo - for a genuine price CHANGE, close the old row's "
              "valid_to and insert a new one instead, so historical costs stay correct).")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
