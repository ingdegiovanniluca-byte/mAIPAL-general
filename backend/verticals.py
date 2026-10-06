"""Pacchetti verticali: what turning a vertical on adds to the general app.

The general features (chat agents, search, lists, tasks, actions, Telegram, Drive...) are
the shared engine and are never removed. A vertical is a "pack" on top of it: lists it
creates (marked with a system_key so the app finds them even if renamed), which chat
agents it shows, which menu entries it hides. Turning it off leaves the data in place.
Kept free of server imports so it can be tested on its own.
"""
from typing import Optional

# ---- artigiano: Clienti, and under each client its Commesse ----
CLIENTI_KEY = "artigiano_clienti"
CLIENTI_NAME = "Clienti"
CLIENTI_FIELDS = [
    {"key": "nome", "label": "Nome", "type": "text"},
    {"key": "telefono", "label": "Telefono", "type": "phone"},
    {"key": "email", "label": "Email", "type": "email"},
    {"key": "indirizzo", "label": "Indirizzo", "type": "text"},
    {"key": "note", "label": "Note", "type": "textarea"},
]
COMMESSA_STATI = ["preventivo", "in corso", "sospesa", "chiusa"]
COMMESSA_FIELDS = [
    {"key": "titolo", "label": "Titolo", "type": "text"},
    {"key": "indirizzo_cantiere", "label": "Indirizzo cantiere", "type": "text"},
    {"key": "stato", "label": "Stato", "type": "select", "options": COMMESSA_STATI},
    {"key": "data_inizio", "label": "Data inizio", "type": "date"},
    {"key": "data_fine", "label": "Data fine", "type": "date"},
    {"key": "descrizione", "label": "Descrizione", "type": "textarea"},
]

PACKS = {
    "artigiano": {
        "label": "Artigiani e piccole imprese",
        "team": True,                    # the owner gets a team (collaborators come later)
        "system_lists": [CLIENTI_KEY],
        "agents": ["work_report"],       # the "Report" agent (primo sopralluogo, ...)
    },
    "veterinario": {"label": "Veterinari", "team": False, "system_lists": [], "agents": ["vet_report"]},
    "fitness": {"label": "Palestre e centri fitness", "team": False, "system_lists": [], "agents": []},
}


def pack(key: Optional[str]) -> Optional[dict]:
    return PACKS.get(key or "")


def _norm(label: str) -> str:
    return " ".join((label or "").lower().split())


def merge_system_fields(existing: list, base: list) -> tuple[list, dict]:
    """Adds the base attributes a system list needs to the attributes it already has, without
    touching the existing ones (or their data): an attribute with the same name is reused, the
    list's first attribute is its name (Nome / Titolo) whatever it's called. Returns
    (attributes, {base key -> actual key})."""
    fields = [dict(f) for f in (existing or [])]
    keys = {f.get("key") for f in fields}
    mapping = {}
    for i, b in enumerate(base):
        if i == 0 and fields:
            mapping[b["key"]] = fields[0]["key"]
            continue
        same = next((f for f in fields if _norm(f.get("label")) == _norm(b["label"])), None)
        if same:
            mapping[b["key"]] = same["key"]
            if b.get("options") and not same.get("options") and same.get("type") in (None, "text", "select"):
                same["type"], same["options"] = "select", list(b["options"])
            continue
        key, n = b["key"], 2
        while key in keys:
            key, n = f"{b['key']}_{n}", n + 1
        keys.add(key)
        fields.append({**b, "key": key, "options": b.get("options"), "ref_collection_id": None})
        mapping[b["key"]] = key
    return fields, mapping


def missing_system_fields(coll: dict) -> list:
    """The base attributes of a system list that a requested change would remove (labels)."""
    out = []
    for attr, base, mkey in (("fields", CLIENTI_FIELDS, "system_map"), ("sub_item_fields", COMMESSA_FIELDS, "system_sub_map")):
        present = {f.get("key") for f in coll.get(attr) or []}
        labels = {b["key"]: b["label"] for b in base}
        for base_key, real_key in (coll.get(mkey) or {}).items():
            if real_key not in present:
                out.append(labels.get(base_key, base_key))
    return out
