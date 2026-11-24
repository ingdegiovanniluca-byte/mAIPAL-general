"""The periodic jobs, ready for more than one copy of the server.

- Each job runs on its own (its own asyncio task and period): a slow one no longer delays the others.
- Each run is claimed in the database (collection job_leases, one document per job): whichever copy claims it
  first runs it, the others skip that period. With one copy nothing changes; with several (more API copies, or
  a worker and its spare) a reminder is never sent twice.
- Things that must run on one copy only while it is alive (the Telegram bot's polling) hold a "leader" lease,
  renewed every few seconds: if that copy stops, another takes over after the lease expires.
- ROLE (environment): "all" (default: API and jobs in the same process, as before), "api" (requests only - for
  the copies behind the load balancer), "worker" (jobs and bot only)."""
import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

OWNER = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"   # this copy


def role() -> str:
    r = (os.environ.get("ROLE") or "all").strip().lower()
    return r if r in ("all", "api", "worker") else "all"


def runs_jobs() -> bool:
    return role() in ("all", "worker")


_INDEXED = set()


async def _unique(db) -> None:
    """The leases rely on one document per name: the unique index, made once per database."""
    if id(db) not in _INDEXED:
        await db.job_leases.create_index("name", unique=True)
        _INDEXED.add(id(db))


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def claim(db, name: str, every_s: float, max_run_s: float = 1800, now: Optional[datetime] = None) -> bool:
    """This copy runs `name` now if its period is due and no copy is running it (a run that crashed frees it after
    max_run_s). The next run is due one period later, whoever runs it. Call release() when done. -> claimed."""
    now = now or _now()
    try:
        await _unique(db)
        await db.job_leases.find_one_and_update(
            {"name": name,
             "$and": [{"$or": [{"next_at": {"$lte": now}}, {"next_at": {"$exists": False}}]},
                      {"$or": [{"running_until": None}, {"running_until": {"$lte": now}}, {"running_until": {"$exists": False}}]}]},
            {"$set": {"name": name, "owner": OWNER, "claimed_at": now,
                      "next_at": now + timedelta(seconds=every_s * 0.9),   # (a little early: the copies' sleeps drift)
                      "running_until": now + timedelta(seconds=max_run_s)}},
            upsert=True)
        return True   # (updated a due one, or created it the first time)
    except DuplicateKeyError:   # not due, or running elsewhere: the filter missed it and the upsert met its unique name
        return False


async def release(db, name: str, took_s: float = 0) -> None:
    await db.job_leases.update_one({"name": name, "owner": OWNER},
                                   {"$set": {"running_until": None, "last_took_s": round(took_s, 2), "last_end_at": _now()}})


async def hold(db, name: str, ttl_s: float = 60) -> bool:
    """Leader lease: taken if free or expired, renewed if already ours. -> this copy is the leader."""
    now = _now()
    try:
        await _unique(db)
        await db.job_leases.find_one_and_update(
            {"name": name, "$or": [{"owner": OWNER}, {"until": {"$lte": now}}, {"until": {"$exists": False}}]},
            {"$set": {"name": name, "owner": OWNER, "until": now + timedelta(seconds=ttl_s)}},
            upsert=True)
        return True
    except DuplicateKeyError:
        return False


def every(db, name: str, period_s: float, fn: Callable[[], Awaitable], first_delay_s: float = 0,
          max_run_s: float = 1800) -> asyncio.Task:
    """Runs fn every period_s seconds, on one copy at a time (never two runs of it together)."""
    async def loop():
        if first_delay_s:
            await asyncio.sleep(first_delay_s)
        while True:
            claimed, t0 = False, time.monotonic()
            try:
                claimed = await claim(db, name, period_s, max_run_s)
                if claimed:
                    await fn()
            except Exception:
                logger.exception("periodic job %s failed", name)
            finally:
                if claimed:
                    took = time.monotonic() - t0
                    if took > period_s:
                        logger.warning("periodic job %s took %.0fs (period %.0fs)", name, took, period_s)
                    try:
                        await release(db, name, took)
                    except Exception:
                        logger.exception("periodic job %s not released", name)
            await asyncio.sleep(period_s)
    return asyncio.create_task(loop(), name=f"job:{name}")


def as_leader(db, name: str, start: Callable[[], Awaitable], ttl_s: float = 60) -> asyncio.Task:
    """Starts `start` on the copy that holds the leader lease `name` (and keeps renewing it); a spare copy keeps
    trying and takes over when the leader's lease expires."""
    async def loop():
        started = False
        while True:
            try:
                if await hold(db, name, ttl_s):
                    if not started:
                        logger.info("leader of %s: %s", name, OWNER)
                        started = True
                        await start()
            except Exception:
                logger.exception("leader job %s failed", name)
            await asyncio.sleep(ttl_s / 3)
    return asyncio.create_task(loop(), name=f"leader:{name}")
