"""The Attrezzatura list's base attributes (name, model, serial number, purchase date, price, last service, advised
maintenance, dealer, notes) - also added to the lists made before -, and the maintenance reminders: only with both the
last service and the frequency, a week before and on the day, each once per due date, to the organization's admins."""
import asyncio, copy, os, sys
from datetime import date
os.environ.update(MONGO_URL="mongodb://x", DB_NAME="t", OPENAI_API_KEY="x", APP_BASE_URL="https://maipal.it/general")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
import server, verticals as vx, notify_prefs as nprefs


def _get(doc, k):
    for part in k.split("."):
        doc = (doc or {}).get(part) if isinstance(doc, dict) else None
    return doc


def _match(doc, q):
    for k, v in (q or {}).items():
        if k == "$or":
            if not any(_match(doc, x) for x in v):
                return False
            continue
        val = _get(doc, k)
        if isinstance(v, dict) and any(x.startswith("$") for x in v):
            if "$in" in v and not (val in v["$in"] or (isinstance(val, list) and set(val) & set(v["$in"]))):
                return False
            if "$ne" in v and val == v["$ne"]:
                return False
            if "$nin" in v and val in v["$nin"]:
                return False
        elif isinstance(val, list) and not isinstance(v, list):
            if v not in val:
                return False
        elif val != v:
            return False
    return True


class Cur:
    def __init__(s, d): s.d = d
    def sort(s, f, dr=1): s.d = sorted(s.d, key=lambda x: x.get(f) or "", reverse=dr == -1); return s
    async def to_list(s, n): return [copy.deepcopy(x) for x in (s.d if n is None else s.d[:n])]
    def __aiter__(s):
        s._it = iter(copy.deepcopy(s.d)); return s
    async def __anext__(s):
        try: return next(s._it)
        except StopIteration: raise StopAsyncIteration


class Coll:
    def __init__(s): s.docs = []
    def find(s, q=None, proj=None): return Cur([d for d in s.docs if _match(d, q)])
    async def find_one(s, q=None, proj=None): return next((copy.deepcopy(d) for d in s.docs if _match(d, q)), None)
    async def insert_one(s, d): s.docs.append(copy.deepcopy(d))
    async def update_one(s, q, u, upsert=False):
        if upsert and not any(_match(d, q) for d in s.docs):
            s.docs.append({k: v for k, v in q.items() if not k.startswith("$")})
        for d in s.docs:
            if _match(d, q):
                for k, v in u.get("$set", {}).items():
                    t = d
                    *path, last = k.split(".")
                    for p in path:
                        t = t.setdefault(p, {})
                    t[last] = copy.deepcopy(v)
                for k, v in u.get("$inc", {}).items(): d[k] = (d.get(k) or 0) + v
                return
    async def count_documents(s, q): return len([d for d in s.docs if _match(d, q)])
    async def update_many(s, q, u):
        n = 0
        for d in s.docs:
            if _match(d, q):
                d.update(copy.deepcopy(u.get("$set", {}))); n += 1
        return type("R", (), {"modified_count": n})()
    async def delete_many(s, q): s.docs = [d for d in s.docs if not _match(d, q)]
    async def delete_one(s, q):
        for i, d in enumerate(s.docs):
            if _match(d, q): s.docs.pop(i); return


class DB:
    def __getattr__(s, n):
        c = Coll(); setattr(s, n, c); return c


db = DB()
server.db = db
SENT = []


async def fake_notify(owner, text, kind=None, push_too=True, url=""):
    SENT.append((owner.user_id, kind, text))
server._notify_owner = fake_notify
TODAY = [date(2026, 11, 28)]
server._local_today = lambda: TODAY[0]


async def main():
    # the frequency: words and numbers; the next service: months kept on the last day of a short month
    assert vx.parse_frequency("ogni 6 mesi") == (6, "m") == vx.parse_frequency("semestrale") == vx.parse_frequency("6 mesi")
    assert vx.parse_frequency("ogni anno") == (1, "y") and vx.parse_frequency("90 giorni") == (90, "d")
    assert vx.parse_frequency("quando capita") is None and vx.parse_frequency("") is None
    assert vx.next_maintenance("2026-08-31", "ogni 6 mesi") == "2027-02-28"
    assert vx.next_maintenance("2026-01-10", "ogni 2 anni") == "2028-01-10"
    assert vx.next_maintenance(None, "ogni anno") is None and vx.next_maintenance("2026-01-10", None) is None
    assert "tools" in nprefs.KIND_KEYS

    for uid, role in (("ua", "admin"), ("ub", "admin"), ("uw", "user")):
        await db.users.insert_one({"user_id": uid, "email": f"{uid}@x.it", "name": uid, "role": role, "tenant_id": "t1", "org_id": "o1"})
    admin = server.User(**await db.users.find_one({"user_id": "ua"}))

    # a new list: the base attributes, in this order (the QR's "who has it" at the end)
    lst = await server._ensure_attrezzi_list(admin)
    assert [f["label"] for f in lst["fields"]] == ["Nome", "Marca e modello", "Matricola", "Data acquisto", "Prezzo",
        "Data ultima revisione / riparazione", "Frequenza manutenzione consigliata", "Rivenditore", "Note", "Link utili", "Ce l'ha", "Dal"]
    freq = next(f for f in lst["fields"] if f["key"] == "frequenza_manutenzione")
    assert freq["type"] == "select" and "ogni 6 mesi" in freq["options"]
    assert {f["key"]: f["type"] for f in lst["fields"]}["prezzo"] == "number"

    # a list made before: the new attributes added in their place, its own ones (and its data) kept
    old_fields = [{"key": k, "label": l, "type": t} for k, l, t in (("nome", "Nome", "text"), ("marca_modello", "Marca e modello", "text"),
                  ("matricola", "Matricola", "text"), ("note", "Note", "textarea"), ("preso_da", "Ce l'ha", "text"), ("preso_il", "Dal", "date"),
                  ("colore", "Colore", "text"), ("ultima", "Ultima manutenzione", "date"))]
    await db.collections.insert_one({"id": "old", "user_id": "ux", "system_key": vx.ATTREZZI_KEY, "fields": old_fields,
                                     "system_map": {"nome": "nome", "marca_modello": "marca_modello", "matricola": "matricola",
                                                    "note": "note", "preso_da": "preso_da", "preso_il": "preso_il"}})
    await db.collection_items.insert_one({"id": "o1", "collection_id": "old", "data": {"nome": "Scala", "colore": "rosso", "ultima": "2026-01-02"}})
    assert await server._migrate_attrezzi_lists() == 1
    old = await db.collections.find_one({"id": "old"})
    labels = [f["label"] for f in old["fields"]]
    assert labels[:3] == ["Nome", "Marca e modello", "Matricola"] and labels[-1] == "Colore", labels
    assert old["system_map"]["ultima_revisione"] == "ultima"                 # ("Ultima manutenzione" adopted, not doubled)
    assert labels.count("Data ultima revisione / riparazione") == 0 and "Ultima manutenzione" in labels
    assert (await db.collection_items.find_one({"id": "o1"}))["data"] == {"nome": "Scala", "colore": "rosso", "ultima": "2026-01-02"}
    assert await server._migrate_attrezzi_lists() == 0                        # (idempotent)
    await db.collections.delete_many({"id": "old"})

    # the reminders
    L = lst["id"]
    def item(iid, **data): return {"id": iid, "collection_id": L, "data": data}
    for it in (item("a", nome="Trapano", ultima_revisione="2026-05-28", frequenza_manutenzione="ogni 6 mesi"),   # due today
               item("b", nome="Flessibile", ultima_revisione="2026-06-01", frequenza_manutenzione="semestrale"),  # in 3 days
               item("c", nome="Scala", ultima_revisione="2026-05-01"),                                           # no frequency
               item("d", nome="Avvitatore", frequenza_manutenzione="ogni anno"),                                 # no last service
               item("e", nome="Betoniera", ultima_revisione="2026-01-01", frequenza_manutenzione="quando serve"), # unreadable
               item("f", nome="Generatore", ultima_revisione="2026-11-01", frequenza_manutenzione="ogni anno"),   # far away
               item("g", nome="Compressore", ultima_revisione="2024-03-01", frequenza_manutenzione="ogni anno")):  # long late
        await db.collection_items.insert_one(it)
    assert await server._tool_maintenance_tick() == 3
    by = {}
    for uid, kind, text in SENT:
        assert kind == "tools" and uid in ("ua", "ub")                       # the organization's administrators, not the users
        by.setdefault(text.split("«")[1].split("»")[0], set()).add(uid)
    assert set(by) == {"Trapano", "Flessibile", "Compressore"} and by["Trapano"] == {"ua", "ub"}
    texts = {t.split("«")[1].split("»")[0]: t for _u, _k, t in SENT}
    assert "da fare oggi" in texts["Trapano"] and "tra 3 giorni" in texts["Flessibile"] and "28 novembre" not in texts["Flessibile"]
    assert "il 1 marzo 2025" in texts["Compressore"]
    # once: nothing again the same day
    SENT.clear()
    assert await server._tool_maintenance_tick() == 0 and not SENT
    # the day comes for the second one: its "due" reminder; the first one is not repeated
    TODAY[0] = date(2026, 12, 1)
    assert await server._tool_maintenance_tick() == 1 and "Flessibile" in SENT[0][2] and "da fare oggi" in SENT[0][2]
    # a new service written in the list: the next one moves, its reminders start again from then
    SENT.clear()
    await db.collection_items.update_one({"id": "a"}, {"$set": {"data.ultima_revisione": "2026-12-01"}})
    assert await server._tool_maintenance_tick() == 0
    TODAY[0] = date(2027, 5, 26)
    assert await server._tool_maintenance_tick() == 1 and "Trapano" in SENT[0][2] and "tra 6 giorni" in SENT[0][2]
    print("ALL OK")


asyncio.run(main())
