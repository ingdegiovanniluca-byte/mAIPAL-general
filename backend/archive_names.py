"""Where a commessa's files go on the administrator's Drive / OneDrive, and their names
(specifica commesse AUT-GEN-06 / AUT-GEN-07):

    mAIPAL/Clienti/<cliente>/<codice> – <commessa>/{Sopralluogo|Preventivi|Lavori|Spese|Report}
    <fase>_AAAAMMGG_<descrizione>.<ext>     e.g. sopralluogo_20261028_tetto.jpg

The description is at most two words from the message (or the file), lowercase, without
accents or special characters, joined by "-"; none found: left out (sopralluogo_20261102.jpg).
A name already used in the same folder gets _02, _03… Kept free of server imports.
"""
import re
import unicodedata
from datetime import date
from typing import Iterable, Optional

PHASES = {"sopralluogo": "Sopralluogo", "preventivo": "Preventivi", "lavori": "Lavori", "spesa": "Spese", "report": "Report"}

_STOP = set("""il lo la i gli le un uno una di a da in con su per tra fra e o ma se che chi cosa come dove quando del dello della dei
degli delle al allo alla ai agli alle dal dalla dai nel nella nei nelle sul sulla sui sulle è sono ho hai ha abbiamo hanno questo
questa questi queste quello quella foto immagine immagini file documento allegato sopralluogo preventivo lavori lavoro spesa spese
report oggi ieri domani mattina pomeriggio sera giorno data del nota note qui ecco ciao invio mando mandato mandata visto vista fatto
fatta fatti gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre lunedi martedi mercoledi
giovedi venerdi sabato domenica cantiere cliente commessa signor signora sig""".split())


def ascii_words(text: str) -> list:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", t)


def describe(text: str, max_words: int = 2) -> str:
    """At most two meaningful words of the text, joined by "-" ("" when none)."""
    words = [w for w in ascii_words(text) if len(w) >= 3 and w not in _STOP and not w.isdigit()]
    out = []
    for w in words:
        if w not in out:
            out.append(w)
        if len(out) == max_words:
            break
    return "-".join(out)


def file_name(phase: str, day: date, description: str = "", ext: str = "jpg", version: Optional[int] = None) -> str:
    """<fase>_AAAAMMGG[_<descrizione>][_vN].<ext>"""
    parts = [phase, day.strftime("%Y%m%d")]
    desc = describe(description) if description else ""
    if desc:
        parts.append(desc)
    if version:
        parts.append(f"v{int(version)}")
    ext = (ext or "bin").lower().lstrip(".")
    return "_".join(parts) + f".{ext}"


def unique(name: str, taken: Iterable[str]) -> str:
    """The name, or with _02, _03… when already used in that folder."""
    taken = set(taken or [])
    if name not in taken:
        return name
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    n = 2
    while True:
        cand = f"{stem}_{n:02d}" + (f".{ext}" if ext else "")
        if cand not in taken:
            return cand
        n += 1


def commessa_folder(code: str, title: str) -> str:
    """<codice> – <nome commessa> (the title alone without a code)."""
    title = " ".join((title or "Commessa").split())
    return f"{code} – {title}" if code else title
