"""Personal-knowledge retrieval: the search behind "Cerca" in the chat and on Telegram.

Hybrid ranking over everything the user has saved (KB notes/documents, and with
scope="all" also tasks, to-dos, diary, vet reports and Liste):

- semantic similarity (multilingual MiniLM cosine) plus a keyword score where every query
  term is weighted by how RARE it is in the user's data: a person's name ("Martina") counts
  far more than a word that appears everywhere ("lezione", "fatto"). A flat per-term boost
  let generic list items outrank the one note that actually named the person asked about;
- entity recall: every record containing a rare query term (typically a name) is included,
  not only the top few - "quando ha fatto lezione Martina?" needs ALL the notes about
  Martina to list every date, not the best 8 fragments;
- forced items (every element of a Lista the question names, tasks due on a date the
  question names...) are added ON TOP of the regular results - they no longer take their
  slots, which used to push the actual answer out of the context entirely;
- each KB note carries the date it was saved, so relative expressions inside it ("oggi",
  "ieri", "venerdì scorso") can be resolved to a real date when answering "quando?".

Kept free of FastAPI/server imports (the db is passed in) so it can be tested directly.
"""
import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import List, Optional

import numpy as np

import embeddings as emb
import list_updates as lu

logger = logging.getLogger(__name__)

# Italian words that carry no search signal (articles, prepositions, question words,
# auxiliaries, generic request verbs). Distinct from list_updates' own stopword set, which
# is tuned for matching list names.
STOPWORDS = {
    "per", "con", "del", "dei", "della", "delle", "degli", "dal", "dalla", "dai", "dagli", "dallo",
    "sul", "sulla", "sui", "sugli", "sullo", "nel", "nella", "nei", "negli", "nello", "the", "and",
    "che", "chi", "cosa", "come", "dove", "quando", "quale", "quali", "quanti", "quanto", "quante",
    "quanta", "perché", "perche",
    "sono", "siamo", "siete", "essere", "stato", "stata", "stati", "state", "molto", "poco",
    "questa", "questo", "questi", "queste", "quello", "quella", "quelli", "quelle", "hai", "hanno",
    "una", "uno", "gli", "voi", "noi", "tuo", "tua", "tuoi", "tue", "mio", "mia", "miei", "mie",
    "info", "informazione", "informazioni", "dimmi", "dammi", "raccontami", "parlami", "cerca",
    "trova", "voglio", "sapere", "tutto", "tutti", "tutte", "tutta", "abbiamo", "avevo", "aveva",
    "fatto", "fatta", "fatti", "fatte", "fare", "fa", "fai", "faccio", "era", "erano", "ultima",
    "ultimo", "volta", "volte", "ancora", "sempre", "mai", "anche", "però", "pero", "allora",
    "stesso", "stessa", "già", "gia", "ricordi", "ricordami", "sai", "puoi", "potresti",
}

_WORD_RE = re.compile(r"[\wàèéìòù']+")
_IT_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
              "agosto", "settembre", "ottobre", "novembre", "dicembre"]
_IT_WEEKDAYS = ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"]

ENTITY_RECALL_CAP = 40     # max records pulled in by a rare term (e.g. every note naming a person)
EXTRA_SUB_ITEM_SCAN = 5000  # list sub-elements (e.g. people enrolled in a lesson) scanned for names


def query_terms(query: str) -> List[str]:
    """Meaningful lowercase terms of the query, in order, without duplicates."""
    out: List[str] = []
    for t in _WORD_RE.findall((query or "").lower()):
        t = t.strip("'")
        if len(t) >= 3 and t not in STOPWORDS and t not in out:
            out.append(t)
    return out[:10]


def _stem(t: str) -> str:
    """Very light Italian stem so singular/plural and gender variants match each other
    ("lezione"/"lezioni", "iscritto"/"iscritti"). Not used for entity recall, where an exact
    word is required (a stem would make "Martina" also match "Martino")."""
    if len(t) >= 5 and t[-1] in "aeiou":
        return t[:-1]
    return t


def _word_in(term: str, words: set) -> bool:
    return term in words


def _tokens(text: str) -> set:
    return set(_WORD_RE.findall((text or "").lower()))


def format_it_date(iso: Optional[str]) -> str:
    """'2026-09-19T08:00:00+00:00' -> 'sabato 19 settembre 2026' ('' if unparseable)."""
    if not iso:
        return ""
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date() if "T" in str(iso) else date.fromisoformat(str(iso)[:10])
    except ValueError:
        return ""
    return f"{_IT_WEEKDAYS[d.weekday()]} {d.day} {_IT_MONTHS[d.month - 1]} {d.year}"


def _kb_display(c: dict) -> str:
    """How a KB chunk is shown to the answering model: with the date it was saved, so a note
    like "oggi Martina ha fatto pilates" can be placed in time."""
    text = c.get("text", "")
    saved = format_it_date(c.get("created_at"))
    src = c.get("source_type")
    if src in ("file", "image_ocr"):
        name = c.get("source_name") or c.get("title") or "documento"
        head = f'[Documento "{name}"' + (f" · caricato {saved}" if saved else "") + "]"
    else:
        head = f"[Nota salvata {saved}]" if saved else "[Nota]"
    return f"{head} {text}"


def _match_scored(query: str, candidates: list) -> tuple:
    """Like list_updates.match_candidates (substring wins, else most shared significant
    words) but also returns the winning score, so callers can tell a strong match from a
    single shared common word."""
    ql = (query or "").strip().lower()
    if not ql or not candidates:
        return 0, []
    stop = lu._STOPWORDS_IT | STOPWORDS
    qtok = set(_WORD_RE.findall(ql)) - stop
    scored = []
    for cid, disp in candidates:
        dl = (disp or "").strip().lower()
        if not dl:
            continue
        score = 1000 if (ql in dl or dl in ql) else 0
        score += len(qtok & (set(_WORD_RE.findall(dl)) - stop)) * 10
        if score > 0:
            scored.append((score, cid))
    if not scored:
        return 0, []
    top = max(s for s, _ in scored)
    return top, [cid for s, cid in scored if s == top]


def _is_strong_match(score: int, n_tied: int) -> bool:
    """Force-include matched list entries only for a real match: the whole name, two or more
    shared words, or a single shared word that singles out at most 3 entries. One generic
    word ("lezione") shared by every lesson in a list is not a match for a question about a
    person - forcing all of them (and their enrolled people) is what used to crowd the note
    that actually answered it out of the context."""
    return score >= 20 or n_tied <= 3


async def retrieve(db, user_id: str, query: str, limit: int = 8, scope: str = "kb",
                   org_id: Optional[str] = None, today: Optional[date] = None) -> List[dict]:
    today = today or date.today()
    try:
        q_emb = await emb.embed_query(query)
    except Exception:
        logger.exception("embed_query failed, falling back to keyword-only")
        q_emb = None

    terms = query_terms(query)
    stems = {t: _stem(t) for t in terms}

    candidates: List[dict] = []
    forced: set = set()  # id() of candidates guaranteed into the result regardless of score

    # ---- KB notes/documents (always) ----
    kb_docs = await db.kb_chunks.find({"user_id": user_id}, {"_id": 0}).to_list(5000)
    doc_siblings: dict = {}
    for c in kb_docs:
        item = {
            "text": c.get("text", ""),
            "display": _kb_display(c),
            "source": "kb",
            "meta": {"chunk_id": c.get("chunk_id"), "title": c.get("title"), "doc_id": c.get("doc_id"),
                     "chunk_index": c.get("chunk_index", 0), "created_at": c.get("created_at")},
            "embedding": c.get("embedding"),
        }
        candidates.append(item)
        if c.get("doc_id"):
            doc_siblings.setdefault(c["doc_id"], []).append(item)
    for did in doc_siblings:
        doc_siblings[did].sort(key=lambda x: x["meta"].get("chunk_index", 0))

    def _owned_or_shared(query_field: str = "user_id") -> dict:
        if org_id:
            return {"$or": [{query_field: user_id}, {"org_id": org_id, "visibility": "org"}]}
        return {query_field: user_id}

    if scope == "all":
        for t in await db.tasks.find(_owned_or_shared(), {"_id": 0}).to_list(1000):
            txt = " · ".join(p for p in [t.get("title", ""), t.get("description", ""), t.get("notes", "")] if p)
            if not txt:
                continue
            when = t.get("due_date", "") + (f" {t.get('due_time', '')}" if t.get("due_time") else "")
            done = " · completato" if t.get("completed") else ""
            display = f"[Task] {t.get('title', '')} — {when} · priorità {t.get('priority', 'media')}{done}. {t.get('description', '') or ''}".strip()
            candidates.append({"text": txt, "display": display, "source": "task", "meta": {"id": t.get("id")}, "embedding": t.get("embedding")})
        for td in await db.todos.find({"user_id": user_id}, {"_id": 0}).to_list(1000):
            txt = " · ".join(p for p in [td.get("title", ""), td.get("description", ""), td.get("notes", "")] if p)
            if not txt:
                continue
            display = f"[To-Do] {td.get('title', '')} — stato {td.get('status', 'da_fare')} ({td.get('completion_percent', 0)}%). {td.get('description', '') or ''}".strip()
            candidates.append({"text": txt, "display": display, "source": "todo", "meta": {"id": td.get("id")}, "embedding": td.get("embedding")})
        for j in await db.journal_entries.find({"user_id": user_id}, {"_id": 0}).sort("date", -1).to_list(1000):
            txt = (j.get("cleaned_text") or j.get("raw_text") or "").strip()
            if not txt:
                continue
            # The whole day (up to 1500 chars), not just its opening: a name mentioned late in a
            # long entry used to be cut off before the model ever saw it.
            display = f"[Diario · {j.get('date', '')} ({format_it_date(j.get('date'))})] {j.get('title', '')}. {txt[:1500]}".strip()
            candidates.append({"text": txt, "display": display, "source": "journal", "meta": {"id": j.get("id"), "date": j.get("date")}, "embedding": j.get("embedding")})
        for vrp in await db.vet_reports.find({"user_id": user_id}, {"_id": 0, "docx_b64": 0}).sort("created_at", -1).to_list(1000):
            txt = (vrp.get("transcript") or "").strip()
            if not txt:
                continue
            who = vrp.get("patient_name") or "paziente non identificato"
            visit_date = (vrp.get("created_at") or "")[:10]
            display = f"[Referto veterinario · {visit_date}] {who} — {vrp.get('template_name', '')}. {txt[:600]}".strip()
            candidates.append({"text": f"{who} {txt}", "display": display, "source": "vet_report",
                               "meta": {"id": vrp.get("id"), "patient_item_id": vrp.get("patient_item_id"), "date": visit_date},
                               "embedding": vrp.get("embedding")})

    # ---- Liste ----
    extra_scan: List[dict] = []  # list sub-elements, searched by name only (no embedding cost)
    colls = await db.collections.find(_owned_or_shared(), {"_id": 0}).to_list(500)
    if colls:
        coll_map = {c["id"]: c for c in colls}
        coll_items = await db.collection_items.find({"collection_id": {"$in": list(coll_map.keys())}}, {"_id": 0}).to_list(5000)
        item_display_map: dict = {}
        item_candidates: List[dict] = []
        for it in coll_items:
            coll = coll_map.get(it.get("collection_id"))
            if not coll:
                continue
            labels = {f["key"]: f["label"] for f in (coll.get("fields") or [])}
            parts = [f"{labels.get(k, k)}: {v}" for k, v in (it.get("data") or {}).items() if v not in (None, "")]
            if not parts:
                continue
            txt = " · ".join(parts)
            cand = {"text": txt, "display": f"[Lista: {coll.get('name', '')}] {txt}", "source": "collection_item",
                    "meta": {"id": it.get("id"), "collection_id": it.get("collection_id")}, "embedding": it.get("embedding")}
            item_candidates.append(cand)
            item_display_map[it["id"]] = txt
        if scope == "all":
            candidates.extend(item_candidates)

        def _sub_candidate(s: dict) -> Optional[dict]:
            coll = coll_map.get(s.get("collection_id")) or coll_map.get(item_coll.get(s.get("item_id")))
            if not coll:
                return None
            labels = {f["key"]: f["label"] for f in (coll.get("sub_item_fields") or [])}
            parts = [f"{labels.get(k, k)}: {v}" for k, v in (s.get("data") or {}).items() if v not in (None, "")]
            if not parts:
                return None
            sub_txt = " · ".join(parts)
            parent = item_display_map.get(s.get("item_id"), "")
            return {"text": sub_txt, "display": f"[Lista: {coll.get('name', '')} > {parent}] {sub_txt}", "source": "collection_sub_item",
                    "meta": {"id": s.get("id"), "item_id": s.get("item_id"), "collection_id": s.get("collection_id")},
                    "embedding": s.get("embedding")}

        item_coll = {it["id"]: it.get("collection_id") for it in coll_items}

        # A question naming a Lista gets ALL of its elements (e.g. "quali pazienti ho in lista").
        score, named_ids = _match_scored(query, [(c["id"], c["name"]) for c in colls if (c.get("name") or "").strip()])
        if named_ids and _is_strong_match(score, len(named_ids)):
            for cand in item_candidates:
                if cand["meta"].get("collection_id") in set(named_ids):
                    if scope != "all":
                        candidates.append(cand)
                    forced.add(id(cand))

        # A question naming one element (e.g. "la lezione di pilates di lunedì mattina") gets
        # that element and everything nested in it (e.g. the people enrolled).
        sub_items_all = await db.collection_sub_items.find({"collection_id": {"$in": list(coll_map.keys())}}, {"_id": 0}).to_list(EXTRA_SUB_ITEM_SCAN)
        if item_display_map:
            score, matched = _match_scored(query, list(item_display_map.items()))
            if matched and _is_strong_match(score, len(matched)):
                matched = set(matched)
                by_id = {c["meta"]["id"]: c for c in item_candidates}
                for iid in matched:
                    cand = by_id.get(iid)
                    if cand:
                        if scope != "all":
                            candidates.append(cand)
                        forced.add(id(cand))
                for s in sub_items_all:
                    if s.get("item_id") in matched:
                        cand = _sub_candidate(s)
                        if cand:
                            candidates.append(cand)
                            forced.add(id(cand))
        # Every other sub-element stays out of the scored pool but can still be found by name
        # (entity recall below): "quando fa lezione Martina?" when Martina is only an enrolled
        # person inside a lesson.
        in_pool = {(c.get("meta") or {}).get("id") for c in candidates if c.get("source") == "collection_sub_item"}
        for s in sub_items_all:
            if s.get("id") not in in_pool:
                cand = _sub_candidate(s)
                if cand:
                    extra_scan.append(cand)

    # A query naming a month+year ("luglio 2026") surfaces every record containing it.
    query_low = (query or "").lower()
    date_month = next((m for m in _IT_MONTHS if m in query_low), None)
    date_year_m = re.search(r"\b(19|20)\d{2}\b", query_low)
    if date_month and date_year_m:
        for c in candidates:
            low = c["text"].lower()
            if date_month in low and date_year_m.group(0) in low:
                forced.add(id(c))

    # ---- term rarity (document frequency over everything searchable) ----
    token_cache = {id(c): _tokens(c["text"]) for c in candidates}
    for c in extra_scan:
        token_cache[id(c)] = _tokens(c["text"])
    pool_size = max(1, len(candidates) + len(extra_scan))
    all_token_sets = list(token_cache.values())

    df_exact = {t: sum(1 for toks in all_token_sets if t in toks) for t in terms}
    df_stem = {t: 0 for t in terms}
    stem_list = [(t, stems[t]) for t in terms]
    for toks in all_token_sets:
        for t, st in stem_list:
            if any(w.startswith(st) for w in toks):
                df_stem[t] += 1

    def _weight(df: int) -> float:
        # rare term -> up to 0.55, a term found in most records -> ~0.08
        rarity = 1.0 - min(1.0, df / pool_size)
        return 0.08 + 0.47 * (rarity ** 2)

    def _kw_score(c) -> tuple:
        toks = token_cache.get(id(c)) or _tokens(c["text"])
        score, hits = 0.0, 0
        for t in terms:
            if t in toks:
                score += _weight(df_exact[t]); hits += 1
            elif any(w.startswith(stems[t]) for w in toks):
                score += 0.6 * _weight(df_stem[t]); hits += 1
        return min(1.2, score), hits

    # ---- embeddings (lazily computed, then cached on the source record) ----
    if q_emb is not None:
        missing_kb = [c for c in candidates if c["source"] == "kb" and not c.get("embedding")]
        if missing_kb:
            try:
                for c, e in zip(missing_kb, await emb.embed_texts([c["text"] for c in missing_kb])):
                    c["embedding"] = e
                    await db.kb_chunks.update_one({"chunk_id": c["meta"]["chunk_id"]}, {"$set": {"embedding": e}})
            except Exception:
                logger.exception("backfill embeddings failed")
        non_kb = [c for c in candidates if c["source"] != "kb" and not c.get("embedding")]
        if non_kb:
            try:
                coll_by_source = {
                    "task": db.tasks, "todo": db.todos, "journal": db.journal_entries,
                    "collection_item": db.collection_items, "collection_sub_item": db.collection_sub_items,
                    "vet_report": db.vet_reports,
                }
                for c, e in zip(non_kb, await emb.embed_texts([c["text"] for c in non_kb])):
                    c["embedding"] = e
                    doc_id = (c.get("meta") or {}).get("id")
                    target = coll_by_source.get(c["source"])
                    if doc_id and target is not None:
                        try:
                            await target.update_one({"id": doc_id}, {"$set": {"embedding": e}})
                        except Exception:
                            logger.exception(f"embedding cache write failed for source={c['source']}")
            except Exception:
                logger.exception("non-kb embed failed")

    # Cosine for every candidate in one vectorized pass (a per-record Python loop over 384-dim
    # vectors dominated search time on larger archives).
    sems = [0.0] * len(candidates)
    if q_emb is not None:
        idx = [i for i, c in enumerate(candidates) if c.get("embedding")]
        if idx:
            mat = np.asarray([candidates[i]["embedding"] for i in idx], dtype=np.float32)
            q = np.asarray(q_emb, dtype=np.float32)
            denom = np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) or 1.0)
            denom[denom == 0] = 1.0
            for i, v in zip(idx, (mat @ q) / denom):
                sems[i] = float(v)
    scored = []
    for c, sem in zip(candidates, sems):
        kw, hits = _kw_score(c)
        scored.append((sem + kw, sem, hits, c))

    # ---- entity recall: every record containing a RARE query term (typically a name) ----
    # "Rare" = found in at most 25 records and in at most 5% of everything (always allowing up
    # to 3 for small archives): a person's name qualifies, a studio's everyday word doesn't.
    entity_terms = [t for t in terms if len(t) >= 4 and 0 < df_exact[t] <= max(3, min(25, int(0.05 * pool_size)))]
    entity_hits: List[tuple] = []
    if entity_terms:
        for c in candidates + extra_scan:
            toks = token_cache.get(id(c)) or _tokens(c["text"])
            n = sum(1 for t in entity_terms if t in toks)
            if n:
                entity_hits.append((n, c))
        # Records naming more of the rare terms first (e.g. "Martina" AND "pilates").
        rank = {id(s[3]): s[0] for s in scored}
        entity_hits.sort(key=lambda x: (x[0], rank.get(id(x[1]), 0.0)), reverse=True)
        for _n, c in entity_hits[:ENTITY_RECALL_CAP]:
            forced.add(id(c))

    forced_list = [c for c in candidates + extra_scan if id(c) in forced]
    rest = [s for s in scored if id(s[3]) not in forced and (s[1] >= 0.20 or s[2] >= 1)]
    rest.sort(key=lambda x: x[0], reverse=True)
    # Forced records come IN ADDITION to the regular top `limit` - never instead of them.
    top = forced_list + [c for _s, _sem, _h, c in rest[:limit]]

    # ---- document expansion: a matched chunk brings its whole document ----
    expanded: List[dict] = []
    seen_chunks, seen_docs, seen_other = set(), set(), set()
    for c in top:
        meta = c.get("meta") or {}
        did, cid = meta.get("doc_id"), meta.get("chunk_id")
        if c.get("source") == "kb" and did and did in doc_siblings:
            if did in seen_docs:
                continue
            for sib in doc_siblings[did]:
                scid = sib["meta"].get("chunk_id")
                if scid not in seen_chunks:
                    expanded.append(sib)
                    seen_chunks.add(scid)
            seen_docs.add(did)
        elif cid:
            if cid not in seen_chunks:
                expanded.append(c)
                seen_chunks.add(cid)
        else:
            key = (c.get("source"), meta.get("id"), c.get("text"))
            if key not in seen_other:
                expanded.append(c)
                seen_other.add(key)
    top = expanded

    # ---- temporal questions about tasks ("oggi", "domani", "questa settimana", "scaduti") ----
    if scope == "all":
        lo = hi = None
        if "oggi" in query_low:
            lo = hi = today.isoformat()
        elif "domani" in query_low:
            lo = hi = (today + timedelta(days=1)).isoformat()
        elif "settiman" in query_low:
            lo, hi = today.isoformat(), (today + timedelta(days=7)).isoformat()
        elif "scad" in query_low or "ritardo" in query_low:
            hi = (today - timedelta(days=1)).isoformat()
        if lo or hi:
            date_q: dict = {"user_id": user_id}
            if lo and hi:
                date_q["due_date"] = {"$gte": lo, "$lte": hi}
            elif hi:
                date_q["due_date"] = {"$lte": hi}
            existing = {(c.get("meta") or {}).get("id") for c in top if c.get("source") == "task"}
            injected = []
            for t in await db.tasks.find(date_q, {"_id": 0}).sort("due_date", 1).to_list(200):
                if t.get("id") in existing:
                    continue
                when = t.get("due_date", "") + (f" {t.get('due_time', '')}" if t.get("due_time") else "")
                injected.append({"text": t.get("title", ""), "source": "task", "meta": {"id": t.get("id")},
                                 "display": f"[Task] {t.get('title', '')} — {when} · priorità {t.get('priority', 'media')}. {t.get('description', '') or ''}".strip()})
            top = injected + top

    # Last resort: nothing passed the filters but a term appears literally somewhere.
    if not top and terms:
        for c in candidates + extra_scan:
            low = c["text"].lower()
            if any(t in low for t in terms):
                top.append(c)
                if len(top) >= limit:
                    break

    logger.info(f"[retrieve] q={query[:60]!r} terms={terms} entity={entity_terms} pool={pool_size} forced={len(forced_list)} returned={len(top)}")
    return top
