"""Free-text edits to "Liste" (Collections) from chat or Telegram - e.g. "aggiungi
Mario Rossi alla lista clienti" or "elimina Utente 2 dalla lezione di pilates del
lunedì mattina".

Same design philosophy as vet_reports.py: the LLM only extracts structured intent
(which operation, roughly which list/item, and field values) - it never picks a
specific item/sub-item id itself. Which actual record is targeted is resolved
deterministically in Python (match_candidates), and when more than one record is an
equally good match, the caller gets back an "ambiguous" result to show the user for
disambiguation instead of letting the model silently guess and edit the wrong record.
"""
import json
import logging
import os
import re

import openai

logger = logging.getLogger(__name__)

MODEL = "gpt-4o"

VALID_OPS = {
    "add_item", "delete_item", "update_item", "clear_items",
    "add_sub_item", "delete_sub_item", "update_sub_item", "clear_sub_items",
    "bulk_add_items",
}

_STOPWORDS_IT = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "da", "in", "con", "su", "per",
    "tra", "fra", "e", "o", "a", "del", "dello", "della", "dei", "degli", "delle", "al", "allo",
    "alla", "ai", "agli", "alle", "dal", "dallo", "dalla", "dai", "dagli", "dalle", "questo",
    "questa", "questi", "queste", "quel", "quella", "mio", "mia", "miei", "mie", "che", "non",
    "lista", "campo", "elemento",
}


async def interpret_list_request(text: str, catalog: list[dict], kb_context: str = "") -> dict:
    """Asks the LLM to classify a free-text request into a structured intent, given the
    user's actual lists and their field schemas. Returns
    {"op": ..., "collection_id": ... | None, "item_query": "...", "sub_item_query": "...",
    "fields": {...}, "sub_items": [...], "items": [...]}. Never invents a collection_id
    outside the given catalog (validated by the caller, not here). `kb_context`, when given,
    is text pulled from the user's own uploaded documents (e.g. an OCR'd schedule) that may
    be needed to fulfil a bulk request like "un campo per ogni orario delle lezioni"."""
    catalog_desc = json.dumps([
        {
            "id": c["id"], "name": c["name"],
            "campo_fields": [{"key": f.get("key"), "label": f.get("label")} for f in (c.get("fields") or [])],
            "elemento_fields": [{"key": f.get("key"), "label": f.get("label")} for f in (c.get("sub_item_fields") or [])],
        }
        for c in catalog
    ], ensure_ascii=False)
    context_block = (
        f"\n\nCONTESTO da documenti caricati dall'utente (usalo SOLO se serve per estrarre dati come orari, nomi, "
        f"date richiesti dall'utente - es. un elenco di orari da cui creare più Campi):\n{kb_context}\n"
    ) if kb_context else ""
    system = (
        "Sei l'assistente che interpreta richieste di modifica di 'Liste' personali strutturate su 3 livelli: "
        "Lista -> Campo (elemento di primo livello, es. un cliente o una lezione) -> Elemento (annidato dentro un "
        "Campo, opzionale, es. una persona iscritta a una lezione). "
        f"Liste disponibili dell'utente (usa SOLO questi id, non inventarne altri):\n{catalog_desc}"
        f"{context_block}\n\n"
        "Determina quale operazione l'utente vuole fare, una tra:\n"
        "- add_item: aggiungere UN nuovo Campo a una lista (es. un nuovo cliente, un nuovo prodotto). Se la stessa "
        "richiesta chiede ANCHE di popolare il nuovo Campo con uno o più Elementi (es. 'crea la lezione di pilates "
        "del martedì mattina e aggiungi utente1, utente2 e utente3'), includi TUTTI quegli elementi in 'sub_items' "
        "nella stessa risposta - non servono richieste separate.\n"
        "- bulk_add_items: creare PIÙ Campi distinti in un colpo solo, uno per ciascuno di una serie di voci simili "
        "che l'utente descrive o che compaiono nel CONTESTO sopra (es. 'crea un campo per ogni orario in cui è "
        "prevista una lezione di pilates' quando gli orari sono elencati in un documento caricato in precedenza). "
        "Usala SOLO quando è chiaro che vanno creati PIÙ Campi separati (non un solo Campo con più Elementi "
        "annidati, che è add_item con 'sub_items').\n"
        "- delete_item: eliminare UN Campo esistente specifico\n"
        "- update_item: modificare i valori di un Campo esistente\n"
        "- clear_items: eliminare TUTTI i Campi di una lista (l'utente dice esplicitamente 'tutti/tutte/tutto/svuota "
        "la lista', non un elemento specifico)\n"
        "- add_sub_item: aggiungere uno o più nuovi Elementi dentro un Campo GIÀ esistente. Se l'utente nomina PIÙ "
        "elementi da aggiungere (es. 'aggiungi utente1, utente2 e utente3 alla lezione di pilates del martedì'), "
        "metti UN oggetto per ciascuno in 'sub_items' (non usare 'fields' per uno solo e perdere gli altri).\n"
        "- delete_sub_item: eliminare UN Elemento annidato specifico da un Campo\n"
        "- update_sub_item: modificare i valori di un Elemento annidato\n"
        "- clear_sub_items: eliminare TUTTI gli Elementi annidati di un Campo (l'utente dice esplicitamente "
        "'tutti/tutte/tutto/svuota', es. 'cancella tutte le persone dalla lezione di pilates del lunedì mattina' - "
        "qui item_query identifica IL CAMPO 'lezione di pilates del lunedì mattina', non le singole persone)\n\n"
        "IMPORTANTE: usa clear_items/clear_sub_items SOLO quando l'utente chiede esplicitamente di eliminare TUTTO/"
        "TUTTI/TUTTE in un colpo solo - per l'eliminazione di uno o più elementi nominati singolarmente usa sempre "
        "delete_item/delete_sub_item (uno per ciascun elemento nominato).\n\n"
        "Rispondi SOLO con un JSON valido in questo formato: "
        '{"op": "...", "collection_id": "id della lista scelta dal catalogo, o null se non sei sicuro di quale lista", '
        '"item_query": "testo breve che identifica il Campo bersaglio (es. nome cliente, nome lezione), vuoto se non applicabile", '
        '"sub_item_query": "testo breve che identifica l\'Elemento annidato bersaglio, vuoto se non applicabile", '
        '"fields": {"key del campo dallo schema": "valore"}, '
        '"sub_items": [{"key del campo elemento dallo schema": "valore"}, ...], '
        '"items": [{"key del campo dallo schema": "valore"}, ...]}. '
        "Usa 'items' SOLO per bulk_add_items (un oggetto per ciascun nuovo Campo da creare, con le key di "
        "campo_fields della lista scelta); usa 'sub_items' per gli Elementi annidati come descritto sopra. "
        "Per 'fields' e per ogni oggetto di 'sub_items'/'items' usa ESATTAMENTE la 'key' (non la 'label') definita "
        "nello schema della lista scelta (campo_fields per 'fields' di add_item/update_item e per ogni oggetto di "
        "'items', elemento_fields per 'fields' di add_sub_item/update_sub_item e per ogni oggetto di 'sub_items'). "
        "Includi SOLO i valori esplicitamente forniti dall'utente o chiaramente presenti nel CONTESTO, non inventare "
        "dati. Ometti 'sub_items'/'items' (lista vuota) se non applicabile."
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = await client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=4096,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
    )
    raw = resp.choices[0].message.content or ""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("Nessun JSON nella risposta del modello")
    parsed = json.loads(match.group(0))
    raw_sub_items = parsed.get("sub_items")
    sub_items = [s for s in raw_sub_items if isinstance(s, dict)] if isinstance(raw_sub_items, list) else []
    raw_items = parsed.get("items")
    items = [it for it in raw_items if isinstance(it, dict)] if isinstance(raw_items, list) else []
    return {
        "op": parsed.get("op"),
        "collection_id": parsed.get("collection_id") or None,
        "item_query": (parsed.get("item_query") or "").strip(),
        "sub_item_query": (parsed.get("sub_item_query") or "").strip(),
        "fields": parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {},
        "sub_items": sub_items,
        "items": items,
    }


def normalize_fields(fields_in: dict, field_defs: list[dict]) -> dict:
    """Remaps whatever keys the LLM (or a re-post from the frontend) sent onto the
    collection's actual field keys, matching by key or by label (case-insensitive) so a
    model that echoes a label instead of a key doesn't silently drop the value."""
    if not fields_in:
        return {}
    by_key = {f["key"]: f["key"] for f in field_defs if f.get("key")}
    by_label = {(f.get("label") or "").strip().lower(): f["key"] for f in field_defs if f.get("key")}
    out = {}
    for k, v in fields_in.items():
        if v is None or str(v).strip() == "":
            continue
        kk = str(k).strip()
        canon = by_key.get(kk) or by_label.get(kk.lower())
        out[canon or kk] = v
    return out


def item_display(item: dict) -> str:
    data = item.get("data") or {}
    parts = [str(v).strip() for v in data.values() if str(v or "").strip()]
    return " · ".join(parts) if parts else "(vuoto)"


async def classify_save_intent(text: str, list_names: list[str]) -> str:
    """Cheap pre-classification used to merge "salva informazione" and "modifica lista"
    into a single chat action: is this free text an instruction to add/edit/remove a
    record in one of the user's existing Liste, or just generic information to save as a
    note? Falls back to 'info_upload' (the safe default - nothing gets deleted) on any
    error or when the user has no lists at all."""
    if not list_names:
        return "info_upload"
    names_desc = ", ".join(f'"{n}"' for n in list_names[:50])
    system = (
        "Devi classificare una frase in una di due categorie:\n"
        "- 'list_update': l'utente vuole aggiungere, modificare o rimuovere uno o PIÙ elementi (anche in blocco/"
        f"massa) in una delle sue liste esistenti ({names_desc}). Rientra qui anche una richiesta di creare PIÙ "
        "Campi in un colpo solo, uno per ciascuna voce simile (es. un orario, un giorno, una riga di un documento "
        "caricato in precedenza) - non serve che l'utente elenchi i valori esatti nel messaggio, può bastare che "
        "descriva il criterio (es. 'un campo per ogni orario in cui c'è lezione'). Esempi: 'aggiungi Mario alla "
        "lista clienti', 'elimina Utente 2 dalla lezione di pilates del lunedì mattina', 'cambia il telefono di "
        "Luca', 'crea nella lista lezioni pilates un campo per ogni giorno e orario in cui è prevista una "
        "lezione', 'aggiungi un elemento per ciascuna voce dell'elenco che ho caricato'.\n"
        "- 'info_upload': qualunque altra informazione generica da salvare/ricordare (una nota, un documento, "
        "un fatto), che non è un'istruzione di modifica su una lista specifica.\n"
        'Rispondi SOLO con un JSON: {"kind": "list_update"} oppure {"kind": "info_upload"}.'
    )
    try:
        client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = await client.chat.completions.create(
            model="gpt-4o-mini", max_completion_tokens=20,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
        )
        raw = resp.choices[0].message.content or ""
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            if parsed.get("kind") in ("list_update", "info_upload"):
                return parsed["kind"]
    except Exception:
        logger.exception("classify_save_intent failed")
    return "info_upload"


def match_candidates(query_text: str, candidates: list[tuple[str, str]]) -> list[str]:
    """Deterministic (non-LLM) matching of a free-text query against (id, display_text)
    candidates: a near-exact substring match wins outright, otherwise the candidate(s) with
    the most overlapping significant words. Returns the ids tied for the best score (empty
    if nothing matches) - more than one id means real ambiguity the caller must resolve,
    mirroring find_matching_patients() in vet_reports.py."""
    ql = (query_text or "").strip().lower()
    if not ql or not candidates:
        return []
    qtok = set(re.findall(r"\w+", ql)) - _STOPWORDS_IT
    scored = []
    for cid, disp in candidates:
        dl = (disp or "").strip().lower()
        if not dl:
            continue
        score = 0
        if ql in dl or dl in ql:
            score = 1000
        dtok = set(re.findall(r"\w+", dl)) - _STOPWORDS_IT
        score += len(qtok & dtok) * 10
        if score > 0:
            scored.append((score, cid))
    if not scored:
        return []
    top = max(s for s, _ in scored)
    return [cid for s, cid in scored if s == top]
