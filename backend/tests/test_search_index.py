"""The search index (search_index.py) and its use in the search (retrieval.py), without external services:
- a write to a searchable record marks it for the index (and its meaning, if the text changed);
- the index's permission filter only matches what the user may see (checked against every kind of record);
- whatever the index returns, a record of another user / organization never reaches the answer: retrieval
  reads it again from MongoDB with the usual permission filter;
- an old record, beyond the latest ones read, is found through the index.
The same against a real MongoDB + Qdrant: tests/integration/it_search_index.py."""
import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MONGO_URL", "mongodb://x")
os.environ.setdefault("DB_NAME", "t")

import retrieval  # noqa: E402
import search_index as six  # noqa: E402


# ---------------------------------------------------------------- marking what changed
def test_update_marks_the_record_changed():
    u = six.mark_update({"$set": {"status": "fatto"}}, ("title",))
    assert u["$set"]["status"] == "fatto" and u["$set"]["ix_d"]
    assert u["$unset"] == {"ix_h": ""}                      # text not touched: the meaning stays


def test_text_change_drops_the_old_meaning():
    u = six.mark_update({"$set": {"text": "nuovo"}, "$push": {"problems": "x"}}, ("text", "problems"))
    assert u["$unset"] == {"ix_h": "", "embedding": ""}
    u = six.mark_update({"$set": {"materials.0.qty": 3}}, ("materials",))      # a nested field counts too
    assert "embedding" in u["$unset"]
    # the code setting the new meaning itself: not removed again
    u = six.mark_update({"$set": {"text": "nuovo", "embedding": [0.1]}}, ("text",))
    assert "embedding" not in u["$unset"] and u["$set"]["embedding"] == [0.1]


def test_marks_copied_from_a_read_record_are_not_written_back():
    # a record read (with its marks) and written again whole: no conflict with the marks of the update
    u = six.mark_update({"$set": {"title": "x", "ix_h": "abc", "ix_d": "old"}}, ())
    assert u["$set"]["ix_d"] != "old" and "ix_h" not in u["$set"] and u["$unset"]["ix_h"] == ""


def test_pipeline_update_and_replacement():
    u = six.mark_update([{"$set": {"a": 1}}], ())
    assert u[-1] == {"$unset": ["ix_h"]} and "ix_d" in u[-2]["$set"]
    assert six.mark_update({"title": "x"}, ()) == {"title": "x"}            # a replacement: untouched here


class _Res:
    def __init__(self, n): self.deleted_count = n


class _RawColl:
    def __init__(self, docs): self.docs = docs; self.ops = []
    def find(self, flt, proj=None):
        docs = [d for d in self.docs if all(d.get(k) == v for k, v in flt.items())]
        async def gen():
            for d in docs:
                yield d
        return gen()
    async def find_one(self, flt, proj=None):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in flt.items())), None)
    async def insert_one(self, doc): self.ops.append(("insert", doc))
    async def insert_many(self, docs, ordered=True): self.ops.append(("insert_many", docs))
    async def update_one(self, flt, upd, *a, **k): self.ops.append(("update", upd))
    async def delete_many(self, flt):
        n = len([d for d in self.docs if all(d.get(k) == v for k, v in flt.items())]); return _Res(n)
    async def delete_one(self, flt): return _Res(1)


class _RawDB:
    def __init__(self, **c): self.__dict__.update(c)
    def __getitem__(self, n): return getattr(self, n)


def test_tracked_db_marks_writes_and_queues_deletions():
    logs = _RawColl([{"id": "j1", "commessa_id": "c1"}, {"id": "j2", "commessa_id": "c1"}, {"id": "j3", "commessa_id": "c2"}])
    gone, users = _RawColl([]), _RawColl([])
    db = six.TrackedDB(_RawDB(job_logs=logs, search_index_gone=gone, users=users))
    assert db.users is users                                   # not a searchable collection: untouched

    async def go():
        await db.job_logs.insert_one({"id": "j9", "text": "x", "ix_h": "copied", "ix_d": "copied"})
        await db.job_logs.update_one({"id": "j1"}, {"$set": {"text": "y"}})
        await db.job_logs.delete_many({"commessa_id": "c1"})
        await db["job_logs"].delete_one({"id": "j3"})
    asyncio.run(go())
    assert logs.ops[0] == ("insert", {"id": "j9", "text": "x"})            # a copy doesn't look already indexed
    assert logs.ops[1][1]["$unset"] == {"ix_h": "", "embedding": ""}
    removed = [g["pid"] for _op, docs in gone.ops for g in docs]
    assert removed == [six.pid("job_log", "j1"), six.pid("job_log", "j2"), six.pid("job_log", "j3")]


# ---------------------------------------------------------------- the index's permission filter
def _cond(pl, c):
    if "must" in c or "should" in c:
        return _flt(pl, c)
    v, m = pl.get(c["key"]), c.get("match", {})
    if "value" in m: return v == m["value"]
    if "any" in m: return v in m["any"]
    if "text" in m: return m["text"].lower() in (v or "").lower().split()
    if "range" in c: return v is not None and c["range"]["gte"] <= v <= c["range"]["lte"]
    raise AssertionError(c)


def _flt(pl, f):
    if "must" in f and not all(_cond(pl, c) for c in f["must"]): return False
    if "should" in f and not any(_cond(pl, c) for c in f["should"]): return False
    return True


A = dict(user_id="ua", org_id="oa", tenant_kb="ta")
RECORDS = [   # every kind of record of org A, as it is in the index
    {"source": "kb", "user_id": "ua2"}, {"source": "kb", "user_id": "ua", "tenant_kb": "ta"},
    {"source": "task", "user_id": "ua2", "org_id": "oa", "visibility": "org"}, {"source": "task", "user_id": "ua2", "org_id": "oa"},
    {"source": "todo", "user_id": "ua2", "org_id": "oa"}, {"source": "journal", "user_id": "ua2", "org_id": "oa"},
    {"source": "vet_report", "user_id": "ua2"}, {"source": "work_report", "user_id": "ua2", "org_id": "oa"},
    {"source": "job_log", "user_id": "ua2", "org_id": "oa"}, {"source": "collection_item", "collection_id": "la"},
]


def test_permission_filter_never_matches_another_organization():
    b = six.perm_filter("ub", "ob", "tb", ["lb"], everything=True)
    assert not [r for r in RECORDS if _flt(r, b)]
    # and a colleague in org A sees just what the app shows them (shared with the org), not a private task / to-do
    a2 = six.perm_filter("ua3", "oa", "ta", ["la"], everything=True)
    seen = {(r["source"], r.get("visibility"), r.get("tenant_kb")) for r in RECORDS if _flt(r, a2)}
    assert seen == {("kb", None, "ta"), ("task", "org", None), ("job_log", None, None), ("collection_item", None, None)}
    # a user without an organization: only their own
    solo = six.perm_filter("ua2", None, None, [], everything=True)
    assert {r["source"] for r in RECORDS if _flt(r, solo)} == {"kb", "task", "todo", "journal", "vet_report", "work_report", "job_log"}
    # only notes / documents when the search is about them
    assert {r["source"] for r in RECORDS if _flt(r, six.perm_filter("ua2", "oa", "ta", ["la"], everything=False))} == {"kb"}


# ---------------------------------------------------------------- the search with the index
def _match(doc, q):
    for k, v in (q or {}).items():
        if k == "$or":
            if not any(_match(doc, s) for s in v): return False
            continue
        if k == "$and":
            if not all(_match(doc, s) for s in v): return False
            continue
        val = doc.get(k)
        if isinstance(v, dict):
            for op, arg in v.items():
                if op == "$in" and val not in arg: return False
                if op == "$nin" and val in arg: return False
                if op == "$ne" and val == arg: return False
                if op == "$gte" and (val is None or val < arg): return False
                if op == "$lte" and (val is None or val > arg): return False
        elif val != v:
            return False
    return True


class _Cur:
    def __init__(self, docs): self.docs = docs
    def sort(self, f, d=1):
        self.docs = sorted(self.docs, key=lambda x: x.get(f) or "", reverse=d == -1); return self
    async def to_list(self, n): return [dict(d) for d in (self.docs if n is None else self.docs[:n])]


class _Coll:
    def __init__(self, docs=None): self.docs = list(docs or [])
    def find(self, q=None, proj=None): return _Cur([d for d in self.docs if _match(d, q)])
    async def find_one(self, q=None, proj=None): return next((dict(d) for d in self.docs if _match(d, q)), None)
    async def update_one(self, *a, **k): pass


class _DB:
    def __init__(self, **cols):
        for n in ("kb_chunks", "tasks", "todos", "journal_entries", "vet_reports", "work_reports", "job_logs", "collections",
                  "collection_items", "collection_sub_items", "users", "job_economics", "job_contacts"):
            setattr(self, n, _Coll(cols.get(n)))


def _vec(i):
    v = [0.0] * 384; v[i % 384] = 1.0; return v


def _world(n_recent=30):
    """Org A: many diary entries, the oldest one with the boiler's serial number; org B: one with a serial too."""
    today = date(2026, 11, 24)
    logs = [{"id": f"a{i}", "user_id": "ua", "org_id": "oa", "commessa_id": "ca", "commessa_title": "Bagno", "client_name": "Rossi",
             "date": (today - timedelta(days=i)).isoformat(), "text": f"posa piastrelle giorno {i}", "embedding": _vec(i)} for i in range(n_recent)]
    logs[-1]["text"] = "montata caldaia Zefiro matricola ZX4471"
    logs.append({"id": "b1", "user_id": "ub", "org_id": "ob", "commessa_id": "cb", "commessa_title": "Cucina", "client_name": "Bianchi",
                 "date": today.isoformat(), "text": "caldaia matricola ZX4471 di un'altra impresa", "embedding": _vec(7)})
    kb = [{"chunk_id": "kb_b", "user_id": "ub", "tenant_kb": "tb", "text": "listino riservato impresa B matricola ZX4471",
           "doc_id": "doc_b", "chunk_index": 0, "created_at": "2026-11-01T10:00:00+00:00", "embedding": _vec(9)}]
    users = [{"user_id": "ua", "tenant_id": "ta"}, {"user_id": "ub", "tenant_id": "tb"}]
    return _DB(job_logs=logs, kb_chunks=kb, users=users)


def _with_index(monkeypatch, hits):
    async def ready(db): return True
    async def recall(*a, **k): return hits
    async def q(text): return _vec(1)
    monkeypatch.setattr(six, "ready", ready)
    monkeypatch.setattr(six, "recall", recall)
    monkeypatch.setattr(retrieval.emb, "embed_query", q)


def test_old_record_found_through_the_index(monkeypatch):
    db = _world()
    monkeypatch.setattr(retrieval, "RECENT_LOGS_INDEXED", 10)    # only the 10 latest read: the serial is in the 30th
    _with_index(monkeypatch, {"job_log": ["a29"]})
    out = asyncio.run(retrieval.retrieve(db, "ua", "matricola ZX4471", scope="all", org_id="oa"))
    assert any("ZX4471" in c["display"] and "Zefiro" in c["display"] for c in out)


def test_without_the_index_the_old_record_is_not_read(monkeypatch):
    db = _world()
    monkeypatch.setattr(retrieval, "LOGS_CAP", 10)
    async def q(text): return _vec(1)
    monkeypatch.setattr(retrieval.emb, "embed_query", q)
    out = asyncio.run(retrieval.retrieve(db, "ua", "matricola ZX4471", scope="all", org_id="oa"))
    assert not any("Zefiro" in c["display"] for c in out)


def test_index_can_never_bring_in_another_organizations_records(monkeypatch):
    # an index gone wrong (or tampered with) returns org B's records to a user of org A
    db = _world()
    _with_index(monkeypatch, {"job_log": ["b1", "a29"], "kb": ["kb_b"]})
    out = asyncio.run(retrieval.retrieve(db, "ua", "matricola ZX4471 caldaia listino", scope="all", org_id="oa"))
    shown = " ".join(c["display"] for c in out)
    assert "Zefiro" in shown
    assert "altra impresa" not in shown and "riservato" not in shown


def test_index_not_answering_falls_back_to_the_latest_records(monkeypatch):
    db = _world()
    async def ready(db): return True
    async def broken(*a, **k): raise OSError("connection refused")
    async def q(text): return _vec(1)
    monkeypatch.setattr(six, "ready", ready)
    monkeypatch.setattr(six, "recall", broken)
    monkeypatch.setattr(retrieval.emb, "embed_query", q)
    out = asyncio.run(retrieval.retrieve(db, "ua", "matricola ZX4471", scope="all", org_id="oa"))
    assert any("Zefiro" in c["display"] for c in out)              # 30 entries: all within the usual limit
    assert six._ready["bad_until"] > 0                              # and the index is left alone for a while
    six._ready["bad_until"] = 0


def test_commessa_totals_count_every_entry_of_a_long_diary(monkeypatch):
    db = _world(40)
    monkeypatch.setattr(retrieval, "LOGS_CAP", 10)                  # only the 10 latest entries read
    async def q(text): return _vec(1)
    monkeypatch.setattr(retrieval.emb, "embed_query", q)
    async def agg(pipeline):   # (the commesse of the whole diary)
        for g in ({"_id": "ca", "c": "Rossi", "t": "Bagno"},):
            yield g
    db.job_logs.aggregate = agg
    out = asyncio.run(retrieval.retrieve(db, "ua", "quante voci ha il diario della commessa Bagno di Rossi?", scope="all", org_id="oa"))
    summary = next(c["display"] for c in out if c["source"] == "summary")
    assert "40 voci" in summary, summary
