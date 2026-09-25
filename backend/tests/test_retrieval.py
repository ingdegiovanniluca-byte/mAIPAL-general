"""Search quality tests for retrieval.py against a realistic in-memory dataset.

Uses the real embedding model (fastembed multilingual MiniLM, same as production) so the
semantic part behaves as in the app; skipped if fastembed isn't installed. Mongo is replaced
by a tiny in-memory fake supporting the queries retrieval.py issues. Run with:
    python -m pytest tests/test_retrieval.py -q
"""
import asyncio
import re
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
pytest.importorskip("fastembed")

import retrieval  # noqa: E402


# ---------------- in-memory Mongo stand-in ----------------
def _match(doc, q):
    for k, v in (q or {}).items():
        if k == "$or":
            if not any(_match(doc, sub) for sub in v):
                return False
            continue
        val = doc.get(k)
        if isinstance(v, dict):
            for op, arg in v.items():
                if op == "$in" and val not in arg: return False
                if op == "$gte" and (val is None or val < arg): return False
                if op == "$lte" and (val is None or val > arg): return False
        elif val != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs): self.docs = docs
    def sort(self, field, direction=1):
        self.docs = sorted(self.docs, key=lambda d: d.get(field) or "", reverse=direction == -1)
        return self
    async def to_list(self, n): return [dict(d) for d in self.docs[:n]]


class _Coll:
    def __init__(self, docs=None): self.docs = list(docs or [])
    def find(self, q=None, proj=None): return _Cursor([d for d in self.docs if _match(d, q)])
    async def update_one(self, q, upd):
        for d in self.docs:
            if _match(d, q):
                d.update(upd.get("$set", {})); return


class _DB:
    def __init__(self, **cols):
        for name in ["kb_chunks", "tasks", "todos", "journal_entries", "vet_reports", "collections",
                     "collection_items", "collection_sub_items"]:
            setattr(self, name, _Coll(cols.get(name)))


U = "u1"
TODAY = date(2026, 9, 25)


def _note(i, text, created):
    return {"chunk_id": f"kb_{i}", "user_id": U, "text": text, "doc_id": f"doc_{i}", "chunk_index": 0,
            "source_type": "chat", "created_at": created}


def _dataset():
    notes = [
        _note(1, "Martina ha fatto pilates il giorno 19 settembre", "2026-09-19T18:00:00+00:00"),
        _note(2, "oggi Martina ha fatto lezione di pilates reformer", "2026-09-12T10:00:00+00:00"),
        _note(3, "Giulia ha fatto lezione di pilates oggi, molto brava", "2026-09-18T10:00:00+00:00"),
        _note(4, "Marco ha saltato la lezione di pilates di mercoledì", "2026-09-17T10:00:00+00:00"),
        _note(5, "Sara ha pagato il pacchetto da 10 lezioni", "2026-09-10T10:00:00+00:00"),
        _note(6, "Il codice del wifi dello studio è XYZ-123", "2026-09-01T10:00:00+00:00"),
        _note(7, "La lezione di yoga del venerdì è spostata alle 19", "2026-09-15T10:00:00+00:00"),
        _note(8, "Elena ha fatto la prima lezione di prova", "2026-09-16T10:00:00+00:00"),
        _note(9, "Martino ha chiesto informazioni sui prezzi", "2026-09-14T10:00:00+00:00"),
    ]
    coll = {"id": "c1", "user_id": U, "name": "Lezioni Pilates",
            "fields": [{"key": "lezione", "label": "Lezione"}, {"key": "giorno", "label": "Giorno"}, {"key": "ora", "label": "Ora"}],
            "sub_item_fields": [{"key": "nome", "label": "Nome"}]}
    days = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì"]
    items, subs = [], []
    people = ["Giulia", "Marco", "Sara", "Elena", "Paolo", "Anna", "Luca", "Chiara"]
    for i, d in enumerate(days):
        for j, ora in enumerate(["9:00", "18:00"]):
            iid = f"it_{i}_{j}"
            items.append({"id": iid, "collection_id": "c1", "data": {"lezione": "Lezione Pilates", "giorno": d, "ora": ora}})
            for k in range(4):
                subs.append({"id": f"s_{i}_{j}_{k}", "item_id": iid, "collection_id": "c1", "data": {"nome": people[(i + j + k) % len(people)]}})
    tasks = [{"id": f"t{i}", "user_id": U, "title": f"Preparare lezione pilates {d}", "due_date": f"2026-09-{20 + i}", "priority": "media"} for i, d in enumerate(days)]
    journal = [{"id": "j1", "user_id": U, "date": "2026-09-20", "cleaned_text": "Giornata piena di lezioni, tutte le lezioni al completo."}]
    return _DB(kb_chunks=notes, tasks=tasks, collections=[coll], collection_items=items, collection_sub_items=subs, journal_entries=journal)


def _run(q, scope="all", db=None):
    return asyncio.run(retrieval.retrieve(db or _dataset(), U, q, limit=8, scope=scope, today=TODAY))


def _texts(res):
    return [c.get("display") or c.get("text") for c in res]


def test_person_question_finds_all_notes_about_that_person():
    res = _texts(_run("quando ha fatto lezione martina"))
    assert any("Martina ha fatto pilates il giorno 19" in t for t in res), res
    assert any("oggi Martina ha fatto lezione di pilates" in t for t in res), res


def test_notes_carry_the_date_they_were_saved():
    res = _texts(_run("quando ha fatto lezione martina"))
    oggi = next(t for t in res if "oggi Martina" in t)
    assert "12 settembre 2026" in oggi, oggi


def test_generic_word_does_not_force_every_list_item():
    db = _dataset()
    res = asyncio.run(retrieval.retrieve(db, U, "quando ha fatto lezione martina", limit=8, scope="all", today=TODAY))
    list_items = [c for c in res if c["source"] in ("collection_item", "collection_sub_item")]
    # A single shared word ("lezione") must not pull in all 10 lessons + their 40 enrolled people.
    assert len(list_items) < 10, len(list_items)


def test_person_enrolled_in_a_list_is_found():
    res = _texts(_run("in quali lezioni è iscritta chiara"))
    assert any("Chiara" in t for t in res), res


def test_named_list_element_still_forces_its_members():
    res = _run("quante persone ci sono nella lezione pilates di lunedì 9:00")
    members = [c for c in res if c["source"] == "collection_sub_item" and "lunedì" in c["display"] and "9:00" in c["display"]]
    assert len(members) == 4, [c["display"] for c in res]


def test_other_names_do_not_drown_the_answer():
    res = _texts(_run("quando ha fatto lezione martina"))
    idx = [i for i, t in enumerate(res) if "Martina" in t]
    assert idx and min(idx) < 3, res


def test_default_kb_scope_also_finds_the_person():
    res = _texts(_run("quando ha fatto lezione martina", scope="kb"))
    assert sum("Martina" in t for t in res) == 2, res


def _realistic_order():
    """A studio saves lesson notes over weeks; the notes about Martina were saved LAST - the
    old search returned the first 8 notes containing "lezione" in saving order and never
    reached them (the reported bug)."""
    db = _dataset()
    martina = [n for n in db.kb_chunks.docs if "Martina" in n["text"]]
    others = [n for n in db.kb_chunks.docs if "Martina" not in n["text"]]
    extra = [_note(100 + i, f"{p} ha fatto lezione di pilates, tutto bene", f"2026-09-0{1 + i % 9}T09:00:00+00:00")
             for i, p in enumerate(["Anna", "Luca", "Paolo", "Chiara", "Giulia", "Sara", "Elena", "Marco"])]
    db.kb_chunks.docs = extra + others + martina
    return db


def test_person_notes_saved_last_are_still_found():
    res = _texts(_run("quando ha fatto lezione martina", db=_realistic_order()))
    assert sum("Martina" in t for t in res) == 2, res


def test_non_note_sources_are_kept_in_the_results():
    res = _run("preparare lezione pilates giovedì", db=_realistic_order())
    assert any(c["source"] == "task" and "giovedì" in c["display"] for c in res), [c.get("display") for c in res]


def test_query_terms_drop_question_words():
    assert retrieval.query_terms("Quando ha fatto lezione Martina?") == ["lezione", "martina"]
