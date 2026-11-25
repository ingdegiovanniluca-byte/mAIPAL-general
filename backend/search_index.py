"""The search index: every searchable record (notes and documents, diary of the commesse, diary, tasks,
to-dos, reports, elements of the Liste) also lives in a vector index, so a question searches the whole
history of an organization and not only the latest records read in memory (retrieval.py).

- MongoDB stays the source of truth. The index is a copy, rebuilt from MongoDB at any time
  (scripts/search_reindex.py): moving to another index (e.g. MongoDB Atlas Vector Search) is another
  class with the same methods as QdrantIndex, then a rebuild.
- The index only says WHICH records to look at: retrieval.py reads them again from MongoDB with the
  same permission filter as always, so a record of another user or organization never comes in
  through the index, even if the index were wrong.
- Kept up to date by the worker (sync_tick, every minute): a write to one of the tracked collections
  marks the record (TrackedDB, wrapped around the server's database), the worker computes its meaning
  (embedding, saved on the record) and indexes it. Without the index the worker still computes the meaning,
  so a question never waits for it.

Configured by SEARCH_INDEX_URL (e.g. http://qdrant:6333; optional SEARCH_INDEX_API_KEY). Not set:
no index, the search works as before (the latest records only)."""
import asyncio
import hashlib
import logging
import os
import time
import uuid
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DIM = 384                    # the embedding model's size (embeddings.py)
SEM_K = 150                  # records most similar to the question
PERIOD_K = 200               # ...among those of the period asked about ("a marzo")
TERM_K = 120                 # records containing a word of the question (a name, a code): all of them if fewer
MAX_TERMS = 6

# collection -> (source, id field, fields whose change changes the text searched)
TRACKED = {
    "kb_chunks": ("kb", "chunk_id", ("text",)),
    "tasks": ("task", "id", ("title", "description", "notes")),
    "todos": ("todo", "id", ("title", "description", "notes")),
    "journal_entries": ("journal", "id", ("cleaned_text", "raw_text")),
    "vet_reports": ("vet_report", "id", ("transcript", "patient_name")),
    "work_reports": ("work_report", "id", ("transcript", "client_name", "commessa_title")),
    "job_logs": ("job_log", "id", ("text", "hours", "hours_pending", "hours_replaced_by", "materials", "problems",
                                   "client_name", "commessa_title")),
    "collection_items": ("collection_item", "id", ("data",)),
    # the full text of the documents sent on a commessa, in pieces (the diary's entry has only its description)
    "job_doc_chunks": ("job_doc", "id", ("text",)),
}
SOURCE_COLL = {v[0]: k for k, v in TRACKED.items()}
MARKS = ("ix_h", "ix_d")     # ix_h: indexed (hash of what was indexed); ix_d: changed since (a token)
GONE = "search_index_gone"   # records deleted, to remove from the index
STATE = "search_index_state"


def url() -> str:
    return (os.environ.get("SEARCH_INDEX_URL") or "").rstrip("/")


def configured() -> bool:
    return bool(url())


def pid(source: str, rid: str) -> str:
    """The point id of a record in the index (stable: the same record -> the same point)."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"maipal:{source}:{rid}"))


# ---------------------------------------------------------------- the index (Qdrant, over HTTP)
class QdrantIndex:
    def __init__(self, base: str, name: str, api_key: str = ""):
        self.base, self.name = base, name
        self.headers = {"api-key": api_key} if api_key else {}
        self._client: Optional[httpx.AsyncClient] = None

    def _c(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=self.base, headers=self.headers, timeout=httpx.Timeout(30.0, connect=3.0))
        return self._client

    async def _req(self, method: str, path: str, timeout: Optional[float] = None, **kw) -> dict:
        r = await self._c().request(method, f"/collections/{self.name}{path}", timeout=timeout or httpx.USE_CLIENT_DEFAULT, **kw)
        if r.status_code == 404 and method == "GET":
            return {}
        r.raise_for_status()
        return r.json()

    async def ensure(self) -> bool:
        """Create the collection if missing. True = it was just created (empty)."""
        if (await self._req("GET", "")).get("result"):
            return False
        await self._req("PUT", "", json={
            "vectors": {"size": DIM, "distance": "Cosine", "on_disk": True},
            "quantization_config": {"scalar": {"type": "int8", "always_ram": True}},   # ~4x less memory
            "on_disk_payload": True,
        })
        for field, schema in (("source", "keyword"), ("user_id", "keyword"), ("org_id", "keyword"), ("tenant_kb", "keyword"),
                              ("visibility", "keyword"), ("collection_id", "keyword"), ("day", "integer"),
                              ("text", {"type": "text", "tokenizer": "word", "lowercase": True, "min_token_len": 2,
                                        "max_token_len": 30, "on_disk": True})):
            await self._req("PUT", "/index?wait=true", json={"field_name": field, "field_schema": schema})
        return True

    async def upsert(self, points: List[dict]) -> None:
        if points:
            await self._req("PUT", "/points?wait=true", json={"points": points})

    async def delete(self, ids: List[str]) -> None:
        if ids:
            await self._req("POST", "/points/delete?wait=true", json={"points": ids})

    async def query(self, vector: List[float], flt: dict, limit: int) -> List[dict]:
        r = await self._req("POST", "/points/query", timeout=3.0,
                            json={"query": vector, "filter": flt, "limit": limit, "with_payload": ["source", "rid"]})
        return (r.get("result") or {}).get("points") or []

    async def scroll(self, flt: dict, limit: int) -> List[dict]:
        r = await self._req("POST", "/points/scroll", timeout=3.0,
                            json={"filter": flt, "limit": limit, "with_payload": ["source", "rid"], "with_vector": False})
        return (r.get("result") or {}).get("points") or []

    async def count(self) -> int:
        if not (await self._req("GET", "")).get("result"):
            return 0   # (not created yet)
        r = await self._req("POST", "/points/count", json={"exact": True})
        return int((r.get("result") or {}).get("count") or 0)

    async def drop(self) -> None:
        r = await self._c().delete(f"/collections/{self.name}")
        if r.status_code not in (200, 404):
            r.raise_for_status()


_index = None


def index():
    """The configured index (None without SEARCH_INDEX_URL). Tests may set search_index._index."""
    global _index
    if _index is None and configured():
        _index = QdrantIndex(url(), os.environ.get("SEARCH_INDEX_NAME", "maipal_search"), os.environ.get("SEARCH_INDEX_API_KEY", ""))
    return _index


# ---------------------------------------------------------------- is it usable now?
_ready = {"at": 0.0, "ok": False, "bad_until": 0.0}


def unhealthy(seconds: float = 30.0) -> None:
    """The index didn't answer: search without it for a while (no timeout on every question)."""
    _ready["bad_until"] = time.monotonic() + seconds


async def ready(db) -> bool:
    """True when the index holds every record (the first full indexing is over) and answers."""
    if index() is None or time.monotonic() < _ready["bad_until"]:
        return False
    if time.monotonic() - _ready["at"] > 30:
        try:
            st = await db[STATE].find_one({"_id": "main"}) or {}
            _ready["ok"] = bool(st.get("ready"))
        except Exception:
            _ready["ok"] = False
        _ready["at"] = time.monotonic()
    return _ready["ok"]


# ---------------------------------------------------------------- questions
def _m(key: str, value) -> dict:
    return {"key": key, "match": {"value": value}}


def perm_filter(user_id: str, org_id: Optional[str], tenant_id: Optional[str], coll_ids: List[str], everything: bool) -> dict:
    """What this user may see, as the index's filter - the same rules as the MongoDB queries in retrieval.py
    (which re-check every record anyway)."""
    def src(names, *alts):
        return {"must": [{"key": "source", "match": {"any": list(names)}}, {"should": [a for a in alts if a]}]}
    mine = _m("user_id", user_id)
    should = [src(["kb"], mine, _m("tenant_kb", tenant_id) if tenant_id else None)]
    if everything:
        should += [
            src(["task"], mine, {"must": [_m("org_id", org_id), _m("visibility", "org")]} if org_id else None),
            src(["todo", "journal", "vet_report", "work_report"], mine),
            src(["job_log", "job_doc"], mine, _m("org_id", org_id) if org_id else None),
        ]
        if coll_ids:
            should.append(src(["collection_item"], {"key": "collection_id", "match": {"any": list(coll_ids)}}))
    return {"should": should}


def _day_int(d) -> Optional[int]:
    if isinstance(d, datetime):
        d = d.date()
    return d.year * 10000 + d.month * 100 + d.day if isinstance(d, date) else None


async def recall(q_emb: List[float], terms: List[str], window, *, user_id: str, org_id: Optional[str],
                 tenant_id: Optional[str], coll_ids: List[str], everything: bool) -> Dict[str, List[str]]:
    """The records to look at for this question, by source: the most similar, those of the period asked about,
    those containing a rare word of the question (a name, a code)."""
    idx = index()
    perm = perm_filter(user_id, org_id, tenant_id, coll_ids, everything)
    jobs = [idx.query(q_emb, perm, SEM_K)]
    if window:
        rng = {"key": "day", "range": {"gte": _day_int(window[0]), "lte": _day_int(window[1])}}
        jobs.append(idx.query(q_emb, {"must": [perm, rng]}, PERIOD_K))
    words = [t for t in terms if len(t) >= 3][:MAX_TERMS]
    for t in words:
        jobs.append(idx.scroll({"must": [perm, {"key": "text", "match": {"text": t}}]}, TERM_K))
    res = await asyncio.gather(*jobs)
    out: Dict[str, List[str]] = {}
    seen = set()
    n_vec = 2 if window else 1
    for i, points in enumerate(res):
        if i >= n_vec and len(points) >= TERM_K:
            continue   # a common word: the similar ones above are enough
        for p in points:
            pl = p.get("payload") or {}
            key = (pl.get("source"), pl.get("rid"))
            if key[0] and key[1] and key not in seen:
                seen.add(key)
                out.setdefault(key[0], []).append(key[1])
    return out


# ---------------------------------------------------------------- what is written to the index
def _payload(source: str, doc: dict, cand: dict, rid: str) -> dict:
    pl = {"source": source, "rid": rid, "text": (cand.get("text") or "")[:6000]}
    for k in ("user_id", "org_id", "tenant_kb", "visibility", "collection_id"):
        if doc.get(k):
            pl[k] = doc[k]
    d = _day_int(cand.get("day"))
    if d:
        pl["day"] = d
    return pl


def _hash(pl: dict) -> str:
    return hashlib.sha1(repr(sorted(pl.items())).encode()).hexdigest()[:16]


def _good_vec(e) -> bool:
    return isinstance(e, list) and len(e) == DIM


async def _sync_coll(raw, coll_name: str, idx, deadline: float, batch: int = 200) -> int:
    """Index the changed records of one collection (until the deadline). Returns how many."""
    import retrieval as rt          # (here: retrieval imports this module)
    import embeddings as emb
    from pymongo import UpdateOne
    source, idf, _ = TRACKED[coll_name]
    coll = raw[coll_name]
    done = 0
    while time.monotonic() < deadline:
        docs = await coll.find({"ix_h": None}, {"docx_b64": 0}).limit(batch).to_list(batch)
        if not docs:
            break
        lists = {}
        if source == "collection_item":
            cids = list({d.get("collection_id") for d in docs if d.get("collection_id")})
            lists = {c["id"]: c async for c in raw.collections.find({"id": {"$in": cids}}, {"_id": 0, "id": 1, "name": 1, "fields": 1})}
        rows = []
        for d in docs:
            rid = d.get(idf)
            cand = (rt.item_candidate(d, lists.get(d.get("collection_id"))) if source == "collection_item"
                    else rt.CANDIDATE[source](d)) if rid else None
            rows.append((d, rid, cand if cand and (cand.get("text") or "").strip() else None))
        need = [(d, c) for d, _r, c in rows if c and not _good_vec(d.get("embedding"))]
        if need:   # the meaning of the new / changed records (also saved on the record: the search uses it)
            vecs = await emb.embed_texts([c["text"] for _d, c in need])
            for (d, _c), v in zip(need, vecs):
                d["embedding"] = v
            await coll.bulk_write([UpdateOne({"_id": d["_id"]}, {"$set": {"embedding": d["embedding"]}}) for d, _c in need], ordered=False)
        points, drop, marks = [], [], []
        for d, rid, cand in rows:
            if cand:
                pl = _payload(source, d, cand, rid)
                points.append({"id": pid(source, rid), "vector": d["embedding"], "payload": pl})
                h = _hash(pl)
            else:   # nothing to search in it (empty text, no id): not in the index
                if rid:
                    drop.append(pid(source, rid))
                h = "-"
            # only if not changed again meanwhile (ix_d is the token of the last change)
            marks.append(UpdateOne({"_id": d["_id"], "ix_d": d.get("ix_d")}, {"$set": {"ix_h": h}}))
        if idx is not None:
            await idx.upsert(points)
            await idx.delete(drop)
        await coll.bulk_write(marks, ordered=False)
        done += len(docs)
    return done


async def _sync_gone(raw, idx, deadline: float) -> int:
    n = 0
    while time.monotonic() < deadline:
        gone = await raw[GONE].find({}).limit(500).to_list(500)
        if not gone:
            break
        await idx.delete([g["pid"] for g in gone if g.get("pid")])
        await raw[GONE].delete_many({"_id": {"$in": [g["_id"] for g in gone]}})
        n += len(gone)
    return n


async def mark_all(raw) -> None:
    """Everything to index again (an empty index, or a new one)."""
    for name in TRACKED:
        await raw[name].update_many({"ix_h": {"$ne": None}}, {"$unset": {"ix_h": ""}})


async def sync_tick(db, budget_s: float = 240.0) -> dict:
    """The worker's job, every minute: the meaning (embedding) of every new or changed searchable record, computed
    after it is saved - not while someone waits for an answer - and, with the index, the index kept up to date
    (the first time, everything, a bit each minute). Without SEARCH_INDEX_URL: only the meaning."""
    idx = index()
    raw = getattr(db, "_raw", db)
    deadline = time.monotonic() + budget_s
    st = await raw[STATE].find_one({"_id": "main"}) or {}
    prev = st.get("mode") or ("index" if st else None)   # (before modes: there was only the index)
    if idx is not None:
        created = await idx.ensure()
        if created or prev != "index":   # a new / empty index, or one that missed the changes made without it
            await raw[STATE].update_one({"_id": "main"}, {"$set": {"ready": False, "mode": "index",
                                                                  "created_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
            await mark_all(raw)
            logger.info("search index: indexing every record")
        stats = {"gone": await _sync_gone(raw, idx, deadline)}
    else:
        if prev != "embed":
            await raw[STATE].update_one({"_id": "main"}, {"$set": {"ready": False, "mode": "embed"}}, upsert=True)
        await raw[GONE].delete_many({})   # (nothing to remove them from)
        stats = {}
    for name in TRACKED:
        stats[name] = await _sync_coll(raw, name, idx, deadline)
    if idx is not None and time.monotonic() < deadline:   # went through everything: the index is complete
        st = await raw[STATE].find_one({"_id": "main"}) or {}
        if not st.get("ready"):
            await raw[STATE].update_one({"_id": "main"}, {"$set": {"ready": True, "ready_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
            logger.info("search index complete: questions now search the whole history")
    if any(stats.values()):
        logger.info(f"search index sync: {stats}")
    return stats


# ---------------------------------------------------------------- marking what changed
def _clean_ops(update: dict) -> dict:
    out = {}
    for op, val in update.items():
        if isinstance(val, dict):
            val = {k: v for k, v in val.items() if k not in MARKS}
            if not val and op in ("$set", "$unset"):
                continue
        out[op] = val
    return out


def _touched(update: dict) -> set:
    return {k.split(".", 1)[0] for v in update.values() if isinstance(v, dict) for k in v}


def mark_update(update, text_fields=()):
    """The same update, plus: the record changed (ix_d new, ix_h gone) and, if its text changed, its meaning
    (embedding) is to compute again."""
    token = uuid.uuid4().hex[:12]
    if isinstance(update, list):   # an aggregation pipeline
        return update + [{"$set": {"ix_d": token}}, {"$unset": ["ix_h"]}]
    if not isinstance(update, dict) or not any(str(k).startswith("$") for k in update):
        return update               # (a replacement document: replace_one strips the marks itself)
    u = _clean_ops(update)
    touched = _touched(u)
    u["$set"] = {**(u.get("$set") or {}), "ix_d": token}
    unset = dict(u.get("$unset") or {})
    unset["ix_h"] = ""
    if "embedding" not in touched and touched & set(text_fields):
        unset["embedding"] = ""
    u["$unset"] = unset
    return u


class _TrackedColl:
    def __init__(self, coll, raw_db, name: str):
        self._c, self._raw, self._name = coll, raw_db, name
        self._source, self._idf, self._text = TRACKED[name]

    def __getattr__(self, n):
        return getattr(self._c, n)

    def __getitem__(self, n):
        return self._c[n]

    async def _gone(self, ids: List[str]) -> None:
        ids = [i for i in ids if i]
        if ids:
            now = datetime.now(timezone.utc)
            await self._raw[GONE].insert_many([{"pid": pid(self._source, i), "at": now} for i in ids], ordered=False)

    @staticmethod
    def _strip(doc):
        if isinstance(doc, dict):
            for k in MARKS:
                doc.pop(k, None)
        return doc

    async def insert_one(self, doc, *a, **k):
        return await self._c.insert_one(self._strip(doc), *a, **k)

    async def insert_many(self, docs, *a, **k):
        return await self._c.insert_many([self._strip(d) for d in docs], *a, **k)

    async def replace_one(self, flt, doc, *a, **k):
        return await self._c.replace_one(flt, self._strip(dict(doc)), *a, **k)

    async def update_one(self, flt, update, *a, **k):
        return await self._c.update_one(flt, mark_update(update, self._text), *a, **k)

    async def update_many(self, flt, update, *a, **k):
        return await self._c.update_many(flt, mark_update(update, self._text), *a, **k)

    async def find_one_and_update(self, flt, update, *a, **k):
        return await self._c.find_one_and_update(flt, mark_update(update, self._text), *a, **k)

    async def delete_one(self, flt, *a, **k):
        d = await self._c.find_one(flt, {self._idf: 1})
        r = await self._c.delete_one(flt, *a, **k)
        if d and r.deleted_count:
            await self._gone([d.get(self._idf)])
        return r

    async def delete_many(self, flt, *a, **k):
        ids = [d.get(self._idf) async for d in self._c.find(flt, {self._idf: 1})]
        r = await self._c.delete_many(flt, *a, **k)
        await self._gone(ids)
        return r

    async def find_one_and_delete(self, flt, *a, **k):
        d = await self._c.find_one_and_delete(flt, *a, **k)
        if d:
            await self._gone([d.get(self._idf)])
        return d

    async def bulk_write(self, ops, *a, **k):
        from pymongo import DeleteMany, DeleteOne, ReplaceOne, UpdateMany, UpdateOne
        out, gone_f = [], []
        for op in ops:
            if isinstance(op, (UpdateOne, UpdateMany)):
                op = type(op)(op._filter, mark_update(op._doc, self._text), upsert=op._upsert, collation=op._collation,
                              array_filters=op._array_filters, hint=op._hint)
            elif isinstance(op, ReplaceOne):
                op = ReplaceOne(op._filter, self._strip(dict(op._doc)), upsert=op._upsert, collation=op._collation, hint=op._hint)
            elif isinstance(op, (DeleteOne, DeleteMany)):
                gone_f.append(op._filter)
            out.append(op)
        ids = [d.get(self._idf) async for d in self._c.find({"$or": gone_f}, {self._idf: 1})] if gone_f else []
        r = await self._c.bulk_write(out, *a, **k)
        await self._gone(ids)
        return r


def track(raw):
    """The database to use in the server: the searchable records' changes are seen (for their meaning and the index)."""
    return TrackedDB(raw)


class TrackedDB:
    """The server's database, unchanged, except that writes to the searchable collections also mark the record
    for the search index (and a deleted record is removed from it)."""
    def __init__(self, raw):
        object.__setattr__(self, "_raw", raw)

    def __getattr__(self, name):
        c = getattr(self._raw, name)
        return _TrackedColl(c, self._raw, name) if name in TRACKED else c

    def __getitem__(self, name):
        c = self._raw[name]
        return _TrackedColl(c, self._raw, name) if name in TRACKED else c
