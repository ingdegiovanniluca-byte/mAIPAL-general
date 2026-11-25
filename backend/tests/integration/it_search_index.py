"""The search index against a real MongoDB and a real Qdrant (run by hand, e.g. with docker):
    docker run -d -p 27017:27017 mongo:7 ; docker run -d -p 6333:6333 qdrant/qdrant:v1.13.6
    IT_MONGO_URL=mongodb://localhost:27017 SEARCH_INDEX_URL=http://localhost:6333 python tests/integration/it_search_index.py
Uses its own database and index ("it_search_index"), dropped first. Checks: an organization with more records than
the latest ones read finds its oldest fact only with the index; another organization asking the same never sees it;
a change and a deletion reach the index at the next sync; the index rebuilt from scratch gives the same."""
import asyncio, os, sys, random
from datetime import date, datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
os.environ.update(MONGO_URL=os.environ.get("IT_MONGO_URL", "mongodb://localhost:27017"), DB_NAME="it_search_index", OPENAI_API_KEY="x")
os.environ.setdefault("SEARCH_INDEX_URL", "http://localhost:6333")
os.environ["SEARCH_INDEX_NAME"] = "it_search_index"
import numpy as np
from motor.motor_asyncio import AsyncIOMotorClient
import retrieval, embeddings as emb, search_index as six, db_indexes

rng = np.random.default_rng(1)
W = "caldaia tubo raccordo valvola impianto bagno cucina parete intonaco piastrella cavo quadro presa pompa filtro".split()
def vec(): v = rng.standard_normal(384); return (v / np.linalg.norm(v)).tolist()
def txt(n): return " ".join(random.choice(W) for _ in range(n))


async def seed(raw, org, user, tenant, kb, logs):
    await raw.users.insert_one({"user_id": user, "tenant_id": tenant, "org_id": org})
    now = datetime.now(timezone.utc)
    await raw.kb_chunks.insert_many([{"chunk_id": f"{org}k{i}", "user_id": user, "tenant_kb": tenant, "text": txt(60), "doc_id": f"{org}d{i // 4}",
                                      "chunk_index": i % 4, "embedding": vec(), "created_at": (now - timedelta(hours=i)).isoformat()} for i in range(kb)])
    await raw.job_logs.insert_many([{"id": f"{org}j{i}", "user_id": user, "org_id": org, "commessa_id": f"{org}c{i % 40}", "commessa_title": f"Lavoro {i % 40}",
                                     "client_name": f"Cliente {i % 30}", "date": (date.today() - timedelta(days=i // 5)).isoformat(), "text": txt(40),
                                     "hours": [], "materials": [], "problems": []} for i in range(logs)])   # (no meaning yet: the sync computes it)


async def found(db, user, org, q):
    out = await retrieval.retrieve(db, user, q, scope="all", org_id=org)
    return " ".join(c.get("display") or "" for c in out)


async def sync_all(db):
    while True:
        await six.sync_tick(db, budget_s=600)
        if (await db._raw[six.STATE].find_one({"_id": "main"}) or {}).get("ready"):
            six._ready["at"] = 0
            return


async def main():
    async def eq(q): return vec()
    async def et(ts): return [vec() for _ in ts]
    emb.embed_query, emb.embed_texts = eq, et          # (the meaning is random here: the words of the question find the records)
    cli = AsyncIOMotorClient(os.environ["MONGO_URL"])
    await cli.drop_database("it_search_index")
    raw = cli["it_search_index"]
    six._index = None
    await six.index().drop()
    await seed(raw, "oa", "ua", "ta", 6000, 4000)
    await seed(raw, "ob", "ub", "tb", 50, 50)
    await raw.job_logs.update_one({"id": "oaj3999"}, {"$set": {"text": "montata caldaia Zefiro matricola ZX4471"}})
    await raw.kb_chunks.update_one({"chunk_id": "obk3"}, {"$set": {"text": "listino riservato impresa B codice KR2210"}})
    await db_indexes.ensure_indexes(raw)
    q = "che caldaia abbiamo montato? matricola ZX4471"

    assert "Zefiro" not in await found(raw, "ua", "oa", q), "without the index the oldest entry is not read"
    db = six.TrackedDB(raw)
    await sync_all(db)
    assert await six.index().count() == 10100
    assert (await raw.job_logs.find_one({"id": "oaj10"}))["embedding"], "the sync saves the meaning on the record"
    assert "Zefiro" in await found(db, "ua", "oa", q), "with the index the oldest entry is found"
    assert "Zefiro" not in await found(db, "ub", "ob", q), "another organization never sees it"
    assert "KR2210" not in await found(db, "ua", "oa", "listino codice KR2210")
    assert "KR2210" in await found(db, "ub", "ob", "listino codice KR2210")

    # a change and a deletion, through the app's (tracked) database
    await db.job_logs.update_one({"id": "oaj3998"}, {"$set": {"text": "sostituito vaso di espansione codice QW9911"}})
    await db.job_logs.delete_one({"id": "oaj3999"})
    st = await six.sync_tick(db, budget_s=60)
    assert st["gone"] == 1 and st["job_logs"] == 1, st
    assert "QW9911" in await found(db, "ua", "oa", "codice QW9911")
    assert "Zefiro" not in await found(db, "ua", "oa", q)

    # the index lost (or a new one, e.g. moving to another server): rebuilt from MongoDB, same answers
    await six.index().drop()
    await sync_all(db)
    assert await six.index().count() == 10099
    assert "QW9911" in await found(db, "ua", "oa", "codice QW9911")

    # the full text of a document sent on a commessa: a detail on page 7 (the entry shows only a short description)
    import server
    server.db = db
    pages = [f"Pagina {i}: rilievo delle stanze, pareti intonacate e pavimenti in gres. " * 12 for i in range(12)]
    pages[7] = "Locale tecnico: caldaia murale a condensazione, potenza 24 kW, matricola PQ5521, canna fumaria in acciaio."
    entry = {"id": "jdoc1", "user_id": "ua", "org_id": "oa", "commessa_id": "oac1", "commessa_title": "Lavoro 1", "client_name": "Cliente 1",
             "date": date.today().isoformat(), "text": "📎 sopralluogo.pdf\nSopralluogo impianto termico", "doc_name": "sopralluogo.pdf",
             "created_at": datetime.now(timezone.utc).isoformat(), "hours": [], "materials": [], "problems": []}
    await db.job_logs.insert_one(dict(entry))
    n = await server._save_doc_chunks(entry, "\n\n".join(pages))
    assert n > 5, n
    st = await six.sync_tick(db, budget_s=60)
    assert st["job_doc_chunks"] == n, st
    q2 = "che potenza ha la caldaia del Cliente 1? matricola PQ5521"
    assert "PQ5521" in await found(db, "ua", "oa", q2)
    assert "PQ5521" not in await found(db, "ub", "ob", q2)
    # the entry deleted (as the app does): its pieces leave the search and the index
    await db.job_logs.delete_one({"id": "jdoc1"})
    await db.job_doc_chunks.delete_many({"log_id": "jdoc1"})
    st = await six.sync_tick(db, budget_s=60)
    assert st["gone"] == n + 1, st
    assert "PQ5521" not in await found(db, "ua", "oa", q2)
    # a document sent before this version (only the entry, with its text): made searchable at the worker's start
    await raw.job_logs.insert_one({"id": "jold", "user_id": "ua", "org_id": "oa", "commessa_id": "oac2", "date": "2025-03-01",
                                   "text": "📎 vecchio.pdf", "doc_name": "vecchio.pdf", "doc_text": "Contatore gas matricola GH7781 nel vano scala."})
    assert await server._migrate_job_doc_chunks() == 1 and await server._migrate_job_doc_chunks() == 0
    await six.sync_tick(db, budget_s=60)
    assert "GH7781" in await found(db, "ua", "oa", "matricola GH7781")

    # without the index: the worker still computes the meaning of what is saved; turned on again, it is filled again
    url = os.environ.pop("SEARCH_INDEX_URL"); six._index = None
    await db.job_logs.insert_one({"id": "jnew", "user_id": "ua", "org_id": "oa", "date": date.today().isoformat(), "text": "posato vaso"})
    await six.sync_tick(db, budget_s=60)
    assert (await raw.job_logs.find_one({"id": "jnew"}))["embedding"], "meaning computed without the index"
    assert (await raw[six.STATE].find_one({"_id": "main"}))["mode"] == "embed"
    os.environ["SEARCH_INDEX_URL"] = url; six._index = None
    await sync_all(db)
    assert await six.index().count() == await raw.job_logs.count_documents({}) + await raw.kb_chunks.count_documents({}) \
        + await raw.job_doc_chunks.count_documents({})

    await cli.drop_database("it_search_index")
    await six.index().drop()
    print("ALL OK")

asyncio.run(main())
