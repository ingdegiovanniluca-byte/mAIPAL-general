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
    {"key": "tipo", "label": "Tipo", "type": "select", "options": ["privato", "azienda"]},
    {"key": "cf_piva", "label": "Codice fiscale / P. IVA", "type": "text"},
    {"key": "referente", "label": "Referente", "type": "text"},
]
# the commessa's life (specifica commesse 3.3, + "sospesa" kept from before):
#   nuova -> sopralluogo (first survey content) -> preventivo inviato (quote uploaded)
#   -> in lavorazione (quote accepted) | persa (lost, with its reason) -> completata -> archiviata
COMMESSA_STATI = ["nuova", "sopralluogo", "preventivo inviato", "in lavorazione", "sospesa", "persa", "completata", "archiviata"]
LEGACY_STATI = {"preventivo": "preventivo inviato", "in corso": "in lavorazione", "chiusa": "completata"}
CLOSED_STATI = {"persa", "completata", "archiviata"}   # out of the operational views: no work, no collaborators
WORKING_STATO = "in lavorazione"                       # reminders and notifications only here
COMMESSA_FIELDS = [
    {"key": "titolo", "label": "Titolo", "type": "text"},
    {"key": "indirizzo_cantiere", "label": "Indirizzo cantiere", "type": "text"},
    {"key": "stato", "label": "Stato", "type": "select", "options": COMMESSA_STATI},
    {"key": "data_inizio", "label": "Data inizio", "type": "date"},
    {"key": "data_fine", "label": "Data fine", "type": "date"},
    {"key": "descrizione", "label": "Descrizione", "type": "textarea"},
    {"key": "codice", "label": "Codice", "type": "text"},
    {"key": "ora_inizio", "label": "Orario standard inizio", "type": "text"},
    {"key": "ora_fine", "label": "Orario standard fine", "type": "text"},
    # the money, the same as in the commessa's diary (Costi): changed on one side, changed on the other
    {"key": "valore", "label": "Valore commessa", "type": "number",
     "aliases": ["valore", "valore della commessa", "importo", "importo commessa", "importo lavori", "prezzo", "budget"]},
    {"key": "spesa_prevista", "label": "Spesa prevista", "type": "number",
     "aliases": ["spese previste", "costo previsto", "costi previsti", "spesa", "budget spesa", "costo stimato", "spesa stimata"]},
]

# ---- artigiano: the equipment (Attrezzatura), the tools of the organization; a tool's QR is linked to one of them
# and, scanned, shows who has it (Prendi / Restituisci): "Ce l'ha" and "Dal" are kept up to date from there ----
ATTREZZI_KEY = "artigiano_attrezzatura"
ATTREZZI_NAME = "Attrezzatura"
MAINT_FREQ_OPTIONS = ["ogni mese", "ogni 3 mesi", "ogni 6 mesi", "ogni anno", "ogni 2 anni"]
ATTREZZI_FIELDS = [
    {"key": "nome", "label": "Nome", "type": "text"},
    {"key": "marca_modello", "label": "Marca e modello", "type": "text", "aliases": ["marca", "modello"]},
    {"key": "matricola", "label": "Matricola", "type": "text", "aliases": ["numero di serie", "seriale", "n. serie"]},
    {"key": "data_acquisto", "label": "Data acquisto", "type": "date", "aliases": ["acquistato il", "data di acquisto"]},
    {"key": "prezzo", "label": "Prezzo", "type": "number", "aliases": ["costo", "prezzo di acquisto", "importo"]},
    {"key": "ultima_revisione", "label": "Data ultima revisione / riparazione", "type": "date",
     "aliases": ["ultima revisione", "ultima manutenzione", "ultima riparazione", "data ultima revisione", "data ultima manutenzione"]},
    {"key": "frequenza_manutenzione", "label": "Frequenza manutenzione consigliata", "type": "select", "options": MAINT_FREQ_OPTIONS,
     "aliases": ["frequenza manutenzione", "manutenzione", "frequenza revisione", "revisione ogni"]},
    {"key": "rivenditore", "label": "Rivenditore", "type": "text", "aliases": ["fornitore", "negozio", "venditore"]},
    {"key": "note", "label": "Note", "type": "textarea"},
    {"key": "link", "label": "Link utili", "type": "textarea", "aliases": ["link", "links", "siti", "sito"]},
    {"key": "preso_da", "label": "Ce l'ha", "type": "text"},
    {"key": "preso_il", "label": "Dal", "type": "date"},
]


# ---- the maintenance of a tool: when the next one is due, from the last one and how often it is advised ----
_FREQ_WORDS = {"mensile": (1, "m"), "bimestrale": (2, "m"), "trimestrale": (3, "m"), "quadrimestrale": (4, "m"),
               "semestrale": (6, "m"), "annuale": (1, "y"), "biennale": (2, "y"), "triennale": (3, "y"),
               "settimanale": (1, "w"), "quindicinale": (15, "d")}
_UNITS = {"giorno": "d", "giorni": "d", "gg": "d", "settimana": "w", "settimane": "w", "mese": "m", "mesi": "m",
          "anno": "y", "anni": "y"}


def parse_frequency(value) -> Optional[tuple]:
    """How often a maintenance is advised -> (n, unit) with unit d / w / m / y, or None when it can't be read:
    "ogni 6 mesi", "6 mesi", "ogni anno", "annuale", "90 giorni", "ogni 2 anni", "semestrale"."""
    import re
    v = " ".join(str(value or "").lower().replace("ogni", " ").split())
    if not v:
        return None
    if v in _FREQ_WORDS:
        return _FREQ_WORDS[v]
    m = re.fullmatch(r"(\d{1,3})?\s*([a-z]+)", v)
    if not m or m.group(2) not in _UNITS:
        return None
    n = int(m.group(1) or 1)
    return (n, _UNITS[m.group(2)]) if n > 0 else None


def next_maintenance(last_iso, frequency) -> Optional[str]:
    """The day of the next maintenance (ISO), from the last one and the frequency; None if one of them is missing or
    can't be read (then no reminder)."""
    from datetime import date, timedelta
    import calendar
    f = parse_frequency(frequency)
    try:
        last = date.fromisoformat(str(last_iso or "")[:10])
    except ValueError:
        return None
    if not f:
        return None
    n, unit = f
    if unit == "d":
        return (last + timedelta(days=n)).isoformat()
    if unit == "w":
        return (last + timedelta(weeks=n)).isoformat()
    months = n * (12 if unit == "y" else 1)
    y, m = divmod(last.month - 1 + months, 12)
    y, m = last.year + y, m + 1
    return date(y, m, min(last.day, calendar.monthrange(y, m)[1])).isoformat()


def order_fields(fields: list, base: list, mapping: dict) -> list:
    """The base attributes in the base order, then the others the list already had."""
    pos = {mapping.get(b["key"]): i for i, b in enumerate(base)}
    return sorted(fields, key=lambda f: pos.get(f.get("key"), len(base)))


def norm_stato(stato: str) -> str:
    """A commessa's state in today's names (the old ones read as the new: preventivo -> preventivo
    inviato, in corso -> in lavorazione, chiusa -> completata); empty -> nuova."""
    s = " ".join((stato or "").lower().replace("_", " ").split())
    return LEGACY_STATI.get(s, s) or "nuova"


def is_closed(stato: str) -> bool:
    return norm_stato(stato) in CLOSED_STATI

PACKS = {
    "artigiano": {
        "label": "Artigiani e piccole imprese",
        "team": True,                    # the owner gets a team (collaborators come later)
        "system_lists": [CLIENTI_KEY, ATTREZZI_KEY],
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
        names = {_norm(b["label"]), *(_norm(a) for a in b.get("aliases") or [])}
        same = next((f for f in fields if _norm(f.get("label")) == _norm(b["label"])), None) \
            or next((f for f in fields if _norm(f.get("label")) in names and f.get("key") not in mapping.values()), None)
        if same:
            mapping[b["key"]] = same["key"]
            if b.get("options") and not same.get("options") and same.get("type") in (None, "text", "select"):
                same["type"], same["options"] = "select", list(b["options"])
            continue
        key, n = b["key"], 2
        while key in keys:
            key, n = f"{b['key']}_{n}", n + 1
        keys.add(key)
        fields.append({**{k: v for k, v in b.items() if k != "aliases"}, "key": key, "options": b.get("options"), "ref_collection_id": None})
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
