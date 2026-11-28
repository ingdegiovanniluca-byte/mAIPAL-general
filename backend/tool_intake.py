"""A tool added to the Attrezzatura list from what is sent in the chat: a photo of the tool (its plate, its label), of
its booklet, a receipt, or a PDF (the manual, the invoice). The model reads only what is written or clearly visible -
never invents a serial number, a price or a date - and the user confirms before anything is saved; the files go in
the tool's own folder (mAIPAL/Attrezzatura/<tool>) and stay attached to it in the app.
Kept free of server imports so it can be tested on its own."""
import json
import re
from datetime import date
from typing import Optional

import verticals as vx

FIELDS = ("nome", "marca_modello", "matricola", "data_acquisto", "prezzo", "ultima_revisione", "frequenza_manutenzione",
          "rivenditore", "note", "link")
LABELS = {f["key"]: f["label"] for f in vx.ATTREZZI_FIELDS}
MAX_FILES = 5
MAX_BYTES = 20 * 1024 * 1024
IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "heic", "heif")
DOC_EXTS = ("pdf", "docx", "txt")

_RULES = (
    "Rispondi SOLO con un JSON con queste chiavi (stringhe; null se l'informazione non c'è):\n"
    '{"nome": ..., "marca_modello": ..., "matricola": ..., "data_acquisto": ..., "prezzo": ..., "ultima_revisione": ..., '
    '"frequenza_manutenzione": ..., "rivenditore": ..., "note": ..., "link": ..., "documento": ...}\n'
    "- nome: che attrezzo è, breve e in italiano (es. «Trapano a percussione», «Smerigliatrice angolare», «Generatore»). "
    "Se ci sono marca o modello, NON metterli nel nome.\n"
    "- marca_modello: marca e modello come sono scritti (es. «Makita GA9020», «Hilti TE 30»).\n"
    "- matricola: il numero di serie / matricola / S/N / Serial No. esattamente come è scritto.\n"
    "- data_acquisto: la data di acquisto (scontrino, fattura, garanzia) in formato AAAA-MM-GG.\n"
    "- prezzo: il prezzo pagato per l'attrezzo, solo il numero (es. 249.90).\n"
    "- ultima_revisione: la data dell'ultima revisione / manutenzione / riparazione scritta, in formato AAAA-MM-GG.\n"
    "- frequenza_manutenzione: ogni quanto va fatta la manutenzione secondo il manuale (es. «ogni 6 mesi», «ogni anno», "
    "«ogni 100 ore» -> scrivilo come è); solo se è scritta.\n"
    "- rivenditore: il negozio / rivenditore che l'ha venduto.\n"
    "- note: al massimo una riga di dati tecnici utili scritti (potenza, tensione, peso), se ci sono.\n"
    "- link: un indirizzo web scritto (sito del produttore, pagina dei ricambi), se c'è.\n"
    "- documento: \"manuale\", \"libretto\", \"scontrino\", \"fattura\", \"garanzia\", \"targhetta\" o \"foto\" (una foto "
    "dell'attrezzo) - cosa è il file.\n"
    "REGOLA FONDAMENTALE: scrivi SOLO quello che è scritto o chiaramente visibile. Non dedurre, non stimare, non "
    "inventare: una matricola, un prezzo o una data che non leggi -> null. La marca solo se il nome o il logo si leggono."
)

SYSTEM_IMAGE = "Leggi la foto di un attrezzo da lavoro o di un suo documento (targhetta, libretto, manuale, scontrino).\n" + _RULES
SYSTEM_TEXT = "Leggi il testo di un documento di un attrezzo da lavoro (manuale, libretto, fattura, garanzia).\n" + _RULES


def ext_of(name: str) -> str:
    return (name or "").rsplit(".", 1)[-1].lower() if "." in (name or "") else ""


def kind_of(name: str) -> Optional[str]:
    """"image" / "doc" for the files read here, None for the others."""
    e = ext_of(name)
    return "image" if e in IMAGE_EXTS else "doc" if e in DOC_EXTS else None


def _date(v) -> Optional[str]:
    s = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s) or None
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})$", s)
        if not m:
            return None
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return None


def _price(v) -> Optional[float]:
    s = str(v if v is not None else "").strip().replace("€", "").replace("EUR", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        p = round(float(s), 2)
    except ValueError:
        return None
    return p if 0 < p < 10_000_000 else None


def _frequency(v) -> Optional[str]:
    """The advised maintenance as the list's menu says it when it can ("ogni 6 mesi"), else as written."""
    s = " ".join(str(v or "").split())[:60]
    if not s:
        return None
    f = vx.parse_frequency(s)
    if f:
        n, unit = f
        months = n * 12 if unit == "y" else n if unit == "m" else None
        menu = {1: "ogni mese", 3: "ogni 3 mesi", 6: "ogni 6 mesi", 12: "ogni anno", 24: "ogni 2 anni"}
        if months in menu:
            return menu[months]
    return s


def parse_reply(raw: str) -> dict:
    """The model's answer -> the tool's fields, checked: dates as dates, the price as a number, nothing empty."""
    m = re.search(r"\{[\s\S]*\}", raw or "")
    try:
        data = json.loads(m.group(0)) if m else {}
    except (ValueError, TypeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = {}
    for k in FIELDS:
        v = data.get(k)
        if v is None or (isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/d", "-")):
            continue
        if k in ("data_acquisto", "ultima_revisione"):
            v = _date(v)
        elif k == "prezzo":
            v = _price(v)
        elif k == "frequenza_manutenzione":
            v = _frequency(v)
        elif k == "link":
            v = str(v).strip()
            v = v if re.match(r"^(https?://|www\.)\S+$", v) else None
            v = ("https://" + v) if v and v.startswith("www.") else v
        else:
            v = " ".join(str(v).split())[:300 if k == "note" else 120]
        if v not in (None, ""):
            out[k] = v
    doc = str(data.get("documento") or "").strip().lower()
    return {"fields": out, "document": doc if doc in ("manuale", "libretto", "scontrino", "fattura", "garanzia", "targhetta", "foto") else ""}


def merge(reads: list) -> dict:
    """The fields read from each file into one tool: the first value found for each field wins (the files in the order
    they were sent), the notes and links put together."""
    out = {}
    for r in reads:
        for k, v in (r.get("fields") or {}).items():
            if k in ("note", "link") and k in out and v not in out[k].split("\n"):
                out[k] = f"{out[k]}\n{v}"[:600]
            elif k not in out:
                out[k] = v
    return out


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def match_item(fields: dict, items: list, fmap: dict, said: str = "") -> Optional[dict]:
    """The tool of the list the files are about: the same serial number, else the same make and model, else its name
    written in the message ("il manuale del flessibile Makita"), else the same name. None: a new tool."""
    key = lambda b: fmap.get(b, b)
    val = lambda it, b: _norm((it.get("data") or {}).get(key(b)))
    for base in ("matricola", "marca_modello"):
        want = _norm(fields.get(base))
        if len(want) >= 4:
            hit = next((it for it in items if val(it, base) == want), None)
            if hit:
                return hit
    said_n = _norm(said)
    if said_n:
        named = [it for it in items if len(val(it, "nome")) >= 4 and val(it, "nome") in said_n]
        named += [it for it in items if len(val(it, "marca_modello")) >= 4 and val(it, "marca_modello") in said_n and it not in named]
        if len(named) == 1:
            return named[0]
    want = _norm(fields.get("nome"))
    if want:
        same = [it for it in items if val(it, "nome") == want]
        if len(same) == 1:
            return same[0]
    return None


def fill_missing(existing: dict, fields: dict, fmap: dict) -> dict:
    """What a known tool gets from the files: only the fields it doesn't have yet (what is already written stays);
    the links and the notes added to the ones there."""
    upd = {}
    for k, v in fields.items():
        real = fmap.get(k, k)
        cur = existing.get(real)
        if cur in (None, ""):
            upd[real] = v
        elif k in ("link", "note") and str(v) not in str(cur):
            upd[real] = f"{cur}\n{v}"[:1000]
    return upd


def summary(fields: dict) -> list:
    """[(label, value)] in the list's order, for the card to confirm."""
    out = []
    for k in FIELDS:
        if k in fields:
            v = fields[k]
            if k in ("data_acquisto", "ultima_revisione"):
                y, mo, d = v.split("-")
                v = f"{d}/{mo}/{y}"
            elif k == "prezzo":
                v = f"€ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            out.append((LABELS.get(k, k), str(v)))
    return out
