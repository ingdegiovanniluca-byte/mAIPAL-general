"""The search index, by hand (inside the backend or worker container):
    python scripts/search_reindex.py            # status: records in the index, still to index, complete or not
    python scripts/search_reindex.py --rebuild  # empty it: the worker indexes everything again in the background

--rebuild is also how to move to another index (another server, or another kind of index): point
SEARCH_INDEX_URL at it and rebuild - MongoDB holds everything, the index is only a copy. While it is
rebuilt, questions search the latest records as before; once complete, the whole history."""
import asyncio, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from motor.motor_asyncio import AsyncIOMotorClient
import search_index as six


async def main(rebuild: bool) -> int:
    if not six.configured():
        print("SEARCH_INDEX_URL non impostato: nessun indice di ricerca (si cercano solo i record più recenti).")
        return 1
    raw = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
    idx = six.index()
    if rebuild:
        await idx.drop()
        await raw[six.STATE].update_one({"_id": "main"}, {"$set": {"ready": False}}, upsert=True)
        await six.mark_all(raw)
        print("Indice svuotato: il worker lo ricostruisce in background (un po' ogni minuto).")
    todo = {n: await raw[n].count_documents({"ix_h": None}) for n in six.TRACKED}
    st = await raw[six.STATE].find_one({"_id": "main"}) or {}
    try:
        n = await idx.count()
    except Exception as e:
        print(f"L'indice non risponde ({six.url()}): {e}")
        return 1
    print(f"Record nell'indice: {n}")
    print("Ancora da indicizzare: " + (", ".join(f"{k} {v}" for k, v in todo.items() if v) or "nessuno"))
    print("Completo (le domande cercano in tutto lo storico): " + ("sì" if st.get("ready") else "non ancora"))
    return 0

sys.exit(asyncio.run(main("--rebuild" in sys.argv)))
