"""The periodic jobs with more than one copy of the server (jobs.py): a job runs on one copy at a time and once per
period, a crashed run frees it, the Telegram bot has one leader; ROLE=api starts no job, ROLE=all/worker all of them."""
import asyncio, copy, os, sys
from datetime import datetime, timedelta, timezone
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from pymongo.errors import DuplicateKeyError
import jobs


def _match(doc, q):
    for k, v in q.items():
        if k == "$or":
            if not any(_match(doc, s) for s in v): return False
            continue
        if k == "$and":
            if not all(_match(doc, s) for s in v): return False
            continue
        val = doc.get(k)
        if isinstance(v, dict):
            for op, arg in v.items():
                if op == "$lte" and (val is None or val > arg): return False
                if op == "$exists" and ((k in doc) != arg): return False
        elif val != v:
            return False
    return True


class Leases:
    """job_leases: one document per name (the unique index), find_one_and_update with upsert like MongoDB's."""
    def __init__(self): self.docs = []
    async def create_index(self, *a, **k): pass
    async def find_one_and_update(self, q, u, upsert=False):
        for d in self.docs:
            if _match(d, q):
                old = copy.deepcopy(d); d.update(u["$set"]); return old
        if upsert:
            if any(d["name"] == q["name"] for d in self.docs):
                raise DuplicateKeyError("E11000 duplicate key: name")
            self.docs.append(dict(u["$set"]))
        return None
    async def update_one(self, q, u):
        for d in self.docs:
            if _match(d, q):
                d.update(u["$set"]); return


class DB:
    def __init__(self): self.job_leases = Leases()


def as_copy(owner):
    jobs.OWNER = owner


async def main():
    db = DB()
    t0 = datetime(2026, 11, 24, 19, 0, tzinfo=timezone.utc)
    lease = lambda: next(d for d in db.job_leases.docs if d["name"] == "presence_late_check")

    # 1) two copies at the same moment: one runs it, the other skips
    as_copy("A"); a = await jobs.claim(db, "presence_late_check", 300, now=t0)
    as_copy("B"); b = await jobs.claim(db, "presence_late_check", 300, now=t0)
    assert (a, b) == (True, False), (a, b)
    # still running on A, later than the period: B still can't (never two runs together)
    as_copy("B"); assert not await jobs.claim(db, "presence_late_check", 300, now=t0 + timedelta(minutes=6))
    # A ends; next period due one period later (whoever claims it)
    as_copy("A"); await jobs.release(db, "presence_late_check", 2.5)
    assert lease()["running_until"] is None and lease()["last_took_s"] == 2.5
    as_copy("B"); assert not await jobs.claim(db, "presence_late_check", 300, now=t0 + timedelta(minutes=1))
    as_copy("B"); assert await jobs.claim(db, "presence_late_check", 300, now=t0 + timedelta(minutes=5))
    assert lease()["owner"] == "B"

    # 2) a copy that crashed mid-run (never released): the job is free again after max_run
    as_copy("B"); await jobs.claim(db, "daily_news", 300, max_run_s=600, now=t0)
    as_copy("A"); assert not await jobs.claim(db, "daily_news", 300, max_run_s=600, now=t0 + timedelta(minutes=8))
    as_copy("A"); assert await jobs.claim(db, "daily_news", 300, max_run_s=600, now=t0 + timedelta(minutes=11))

    # 3) the bot's leader: one copy; the spare takes over only when the leader's lease expires
    as_copy("A"); assert await jobs.hold(db, "telegram_polling", ttl_s=60)
    as_copy("B"); assert not await jobs.hold(db, "telegram_polling", ttl_s=60)
    as_copy("A"); assert await jobs.hold(db, "telegram_polling", ttl_s=60)   # renewed
    tp = next(d for d in db.job_leases.docs if d["name"] == "telegram_polling")
    tp["until"] = datetime.now(timezone.utc) - timedelta(seconds=1)          # A stopped renewing it
    as_copy("B"); assert await jobs.hold(db, "telegram_polling", ttl_s=60)
    as_copy("A"); assert not await jobs.hold(db, "telegram_polling", ttl_s=60)

    # 4) every(): runs the function on the copy that claims, and releases it
    runs = []
    async def work(): runs.append(1)
    as_copy("C")
    task = jobs.every(db, "unit_job", 3600, work)
    await asyncio.sleep(0.05); task.cancel()
    assert runs == [1] and next(d for d in db.job_leases.docs if d["name"] == "unit_job")["running_until"] is None
    # a failing job is logged and released too
    async def boom(): raise RuntimeError("x")
    task = jobs.every(db, "boom_job", 3600, boom)
    await asyncio.sleep(0.05); task.cancel()
    assert next(d for d in db.job_leases.docs if d["name"] == "boom_job")["running_until"] is None

    # 5) roles
    for r, expect in (("api", False), ("worker", True), ("all", True), ("", True), ("nonsense", True)):
        os.environ["ROLE"] = r
        assert jobs.runs_jobs() is expect, r
    os.environ.pop("ROLE", None)

    # 6) the server's startup: ROLE=api starts nothing; otherwise every job (each its own) and the bot's leader
    import server
    started, leaders = [], []
    real_every, real_leader = jobs.every, jobs.as_leader
    jobs.every = lambda db_, name, period, fn, first=0, max_run=1800: started.append((name, period))
    jobs.as_leader = lambda db_, name, start, ttl_s=60: leaders.append(name)
    async def no_idx(db_): return 0
    server.db_indexes.ensure_indexes = no_idx
    for n in ("_migrate_tenants", "_migrate_commesse", "_migrate_weekly_actions", "_migrate_list_values", "_migrate_added_quotes"):
        async def nothing(*a, **k): return None
        setattr(server, n, nothing)
    class NoIdx:
        def __getattr__(s, n):
            class C:
                async def create_index(self, *a, **k): pass
            return C()
    server.db = NoIdx()
    os.environ["ROLE"] = "api"
    await server.start_services()
    assert not started and not leaders
    os.environ["ROLE"] = "worker"
    await server.start_services()
    names = {n for n, _ in started}
    assert {j.strip("_") for j in server.FIVE_MINUTE_JOBS} <= names and len(server.FIVE_MINUTE_JOBS) == 18
    assert {"daily_summary", "daily_news", "scheduled_actions", "exact_reminders", "task_reminders", "task_series",
            "conversation_cleanup", "news_cleanup", "usage_aggregation", "geo_backfill", "todo_step_reminders"} <= names
    assert len(names) == len(started), "a job registered twice"
    assert leaders == ["telegram_polling"]
    jobs.every, jobs.as_leader = real_every, real_leader

    # 7) Telegram: one Bot reused for every message (not a new connection each time), paced under Telegram's limit
    import telegram, time as _t
    import telegram_bot as tgb
    made, sent = [], []
    class FakeBot:
        def __init__(self, token=None, request=None): made.append(token)
        async def send_message(self, chat_id=None, text=None, **k): sent.append((chat_id, _t.monotonic()))
    telegram.Bot = FakeBot
    os.environ["TELEGRAM_BOT_TOKEN"] = "123:abc"
    tgb.SEND_RATE = 20.0
    tgb._shared.clear()
    t0 = _t.monotonic()
    await asyncio.gather(*(tgb.shared_bot().send_message(chat_id=i, text="x") for i in range(6)))
    took = _t.monotonic() - t0
    assert len(made) == 1 and len(sent) == 6, (made, sent)
    gaps = [b[1] - a[1] for a, b in zip(sent, sent[1:])]
    assert took >= 0.2 and min(gaps) >= 0.04, (took, gaps)   # 20 a second: 50 ms apart (a little scheduling slack)
    print("ALL OK")

asyncio.run(main())
