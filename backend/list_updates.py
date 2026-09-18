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

VALID_OPS = {"add_item", "delete_item", "update_item", "add_sub_item", "delete_sub_item", "update_sub_item"}

_STOPWORDS_IT = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "da", "in", "con", "su", "per",
    "tra", "fra", "e", "o", "a", "del", "dello", "della", "dei", "degli", "delle", "al", "allo",
    "alla", "ai", "agli", "alle", "dal", "dallo", "dalla", "dai", "dagli", "dalle", "questo",
    "questa", "questi", "queste", "quel", "quella", "mio", "mia", "miei", "mie", "che", "non",
    "lista", "campo", "elemento",
}


async def interpret_list_request(text: str, catalog: list[dict]) -> dict:
    """Asks the LLM to classify a free-text request into a structured intent, given the
    user's actual lists and their field schemas. Returns
    {"op": ..., "collection_id": ... | None, "item_query": "...", "sub_item_query": "...",
    "fields": {...}}. Never invents a collection_id outside the given catalog (validated by
    the caller, not here)."""
    catalog_desc = json.dumps([
        {
            "id": c["id"], "name": c["name"],
            "campo_fields": [{"key": f.get("key"), "label": f.get("label")} for f in (c.get("fields") or [])],
            "elemento_fields": [{"key": f.get("key"), "label": f.get("label")} for f in (c.get("sub_item_fields") or [])],
        }
        for c in catalog
    ], ensure_ascii=False)
    system = (
        "Sei l'assistente che interpreta richieste di modifica di 'Liste' personali strutturate su 3 livelli: "
        "Lista -> Campo (elemento di primo livello, es. un cliente o una lezione) -> Elemento (annidato dentro un "
        "Campo, opzionale, es. una persona iscritta a una lezione). "
        f"Liste disponibili dell'utente (usa SOLO questi id, non inventarne altri):\n{catalog_desc}\n\n"
        "Determina quale operazione l'utente vuole fare, una tra:\n"
        "- add_item: aggiungere un nuovo Campo a una lista (es. un nuovo cliente, un nuovo prodotto)\n"
        "- delete_item: eliminare un Campo esistente\n"
        "- update_item: modificare i valori di un Campo esistente\n"
        "- add_sub_item: aggiungere un nuovo Elemento annidato dentro un Campo esistente\n"
        "- delete_sub_item: eliminare un Elemento annidato da un Campo\n"
        "- update_sub_item: modificare i valori di un Elemento annidato\n\n"
        "Rispondi SOLO con un JSON valido in questo formato: "
        '{"op": "...", "collection_id": "id della lista scelta dal catalogo, o null se non sei sicuro di quale lista", '
        '"item_query": "testo breve che identifica il Campo bersaglio (es. nome cliente, nome lezione), vuoto se non applicabile", '
        '"sub_item_query": "testo breve che identifica l\'Elemento annidato bersaglio, vuoto se non applicabile", '
        '"fields": {"key del campo dallo schema": "valore"}}. '
        "Per 'fields' usa ESATTAMENTE la 'key' (non la 'label') definita nello schema della lista scelta "
        "(campo_fields per add_item/update_item, elemento_fields per add_sub_item/update_sub_item). Includi in "
        "'fields' SOLO i valori esplicitamente forniti dall'utente, non inventare dati."
    )
    client = openai.AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])
    resp = await client.chat.completions.create(
        model=MODEL,
        max_completion_tokens=1024,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
    )
    raw = resp.choices[0].message.content or ""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("Nessun JSON nella risposta del modello")
    parsed = json.loads(match.group(0))
    return {
        "op": parsed.get("op"),
        "collection_id": parsed.get("collection_id") or None,
        "item_query": (parsed.get("item_query") or "").strip(),
        "sub_item_query": (parsed.get("sub_item_query") or "").strip(),
        "fields": parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {},
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
        "- 'list_update': l'utente vuole aggiungere, modificare o rimuovere un elemento specifico "
        f"in una delle sue liste esistenti ({names_desc}). Es. 'aggiungi Mario alla lista clienti', "
        "'elimina Utente 2 dalla lezione di pilates del lunedì mattina', 'cambia il telefono di Luca'.\n"
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
