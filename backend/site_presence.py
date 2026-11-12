"""Presence on site (artigiano): a collaborator says on Telegram "sono arrivato" and "ho finito"
(or taps the button, which also sends the phone's position): the time in between becomes the
hours of their diary entry for that commessa.

The position is taken only at those two moments, when the collaborator sends it (no tracking):
it is compared with the site's, found from the commessa's address (OpenStreetMap) or set by the
owner, and the owner sees how far from the site the start and the end were.
Kept free of server imports so it can be tested on its own.
"""
import asyncio
import logging
import math
import re
from datetime import datetime, time
from typing import Optional

logger = logging.getLogger(__name__)

ON_SITE_METERS = 300          # within this distance from the site: "in cantiere"
FORGOTTEN_HOURS = 14          # a start without an end after this long is not counted by itself
PAUSES = [30, 60]             # minutes, offered at the end

_TIME = r"(?:\s+(?:alle|dalle|alle ore|ore|dalle ore)\s+(?P<h>\d{1,2})(?:[:.,](?P<m>\d{2}))?)?"
_START = re.compile(
    r"^(?:/inizio|sono arrivat[oaie]|siamo arrivat[ie]|arrivat[oaie]|inizio(?: (?:lavori|turno|a lavorare))?"
    r"|comincio(?: a lavorare)?|inizio la giornata|attacco)"
    r"(?P<rest>(?:\s+(?:in|al|nel) cantiere)?(?:\s+(?:da|dai|dal|dalla|dalle|dagli|presso)\s+[^\d][\w'àèéìòù ]{1,40}?)?)" + _TIME + r"[\s.!]*$",
    re.I)
_STOP = re.compile(
    r"^(?:/fine|ho finito|abbiamo finito|finito|fine(?: (?:lavori|turno|giornata))?|stacco|stacchiamo"
    r"|vado via|andiamo via|me ne vado|chiudo(?: la giornata)?)"
    r"(?:\s+(?:per oggi|per stasera|di lavorare|la giornata|in cantiere))?" + _TIME + r"[\s.!]*$",
    re.I)


# ---- the pauses while on site: "⏸️ Pausa" / "sono in pausa (dalle 12:30)" ... "▶️ Riprendo" / "ho ripreso";
# or the pause said afterwards: "ho fatto mezz'ora di pausa", "pausa pranzo di un'ora", "pausa dalle 12 alle 13"
_PAUSE_WORD = r"(?:una\s+|la\s+)?pausa(?:\s+(?:pranzo|caff[eè]|merenda|sigaretta))?"
_PAUSE_START = re.compile(
    r"^(?:" + _PAUSE_WORD + r"|(?:(?:sono|siamo|vado|andiamo)\s+)?in\s+" + _PAUSE_WORD + r"|(?:faccio|facciamo|inizio|iniziamo)\s+"
    + _PAUSE_WORD + r"|(?:vado|andiamo)\s+a\s+(?:pranzo|mangiare)|(?:stacco|stacchiamo)\s+per\s+(?:il\s+)?pranzo)" + _TIME + r"[\s.!]*$", re.I)
_PAUSE_END = re.compile(
    r"^(?:riprendo|riprendiamo|(?:ho|abbiamo)\s+ripreso|ripres[oi]|fine\s+(?:della\s+)?pausa|finita\s+la\s+pausa|(?:ho|abbiamo)\s+finito\s+la\s+pausa|"
    r"(?:torno|torniamo)\s+al\s+lavoro|(?:sono|siamo)\s+tornat[oaie](?:\s+al\s+lavoro|\s+in\s+cantiere)?|rientrat[oaie]|ricomincio|ricominciamo)"
    r"(?:\s+a\s+lavorare)?" + _TIME + r"[\s.!]*$", re.I)
_DUR = (r"(?P<{}>mezz['’ ]?ora|un['’ ]?ora(?:\s+e\s+mezz[ao])?|\d{{1,3}}(?:[.,]\d)?\s*(?:minuti|min|m|ore|ora|h|')"
        r"(?:\s*e\s*(?:mezz[ao]|\d{{1,2}}(?:\s*(?:minuti|min))?))?|\d{{1,2}}[:.]\d{{2}}\s*(?:ore|h)?)")
_PAUSE_FOR = re.compile(
    r"^(?:(?:ho|abbiamo)\s+fatto\s+|fatto\s+|fatta\s+)?(?:(?:" + _PAUSE_WORD + r")\s+(?:di\s+)?" + _DUR.format("dur") + r"|" + _DUR.format("dur2")
    + r"\s+di\s+" + _PAUSE_WORD + r"|(?:" + _PAUSE_WORD + r")\s+dalle\s+(?P<h1>\d{1,2})(?:[:.,](?P<m1>\d{2}))?\s+alle\s+(?P<h2>\d{1,2})(?:[:.,](?P<m2>\d{2}))?)"
    r"(?:\s+(?:oggi|stamattina|a\s+pranzo))?[\s.!]*$", re.I)


def _duration_min(s: str) -> Optional[int]:
    """ "mezz'ora" 30, "un'ora e mezza" 90, "45 minuti" 45, "1 ora e 30" 90, "1,5 ore" 90, "1:30" 90."""
    t = s.lower().replace("’", "'").strip()
    if re.match(r"mezz", t):
        return 30
    if re.match(r"un'? ?ora", t):
        return 90 if re.search(r"e\s+mezz", t) else 60
    m = re.match(r"(\d{1,2})[:.](\d{2})", t)
    if m and not re.search(r"min", t):
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.match(r"(\d{1,3}(?:[.,]\d)?)\s*(minuti|min|m|ore|ora|h|')", t)
    if not m:
        return None
    n = float(m.group(1).replace(",", "."))
    mins = n * 60 if m.group(2) in ("ore", "ora", "h") else n
    rest = t[m.end():]
    if re.search(r"e\s*mezz", rest):
        mins += 30
    else:
        r2 = re.search(r"e\s*(\d{1,2})", rest)
        if r2:
            mins += int(r2.group(1))
    return int(round(mins))


def _parse_pause(t: str) -> Optional[dict]:
    m = _PAUSE_FOR.match(t)
    if m:
        if m.group("h1"):
            h1, m1, h2, m2 = int(m.group("h1")), int(m.group("m1") or 0), int(m.group("h2")), int(m.group("m2") or 0)
            if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59 or (h2 * 60 + m2) <= (h1 * 60 + m1):
                return None
            return {"action": "pause_add", "minutes": (h2 * 60 + m2) - (h1 * 60 + m1), "from": time(h1, m1), "to": time(h2, m2), "at": None, "rest": ""}
        mins = _duration_min(m.group("dur") or m.group("dur2") or "")
        return {"action": "pause_add", "minutes": mins, "at": None, "rest": ""} if mins and 0 < mins <= 600 else None
    for action, rx in (("pause_start", _PAUSE_START), ("pause_end", _PAUSE_END)):
        m = rx.match(t)
        if m:
            at = None
            if m.group("h"):
                h, mi = int(m.group("h")), int(m.group("m") or 0)
                if h > 23 or mi > 59:
                    return None
                at = time(h, mi)
            return {"action": action, "at": at, "rest": ""}
    return None


def parse_command(text: str) -> Optional[dict]:
    """"sono arrivato (dai Rossi) (alle 8)" -> {"action": "start", "at": time|None, "rest": "dai Rossi"};
    "ho finito (alle 17:30)" -> {"action": "stop", ...}; "sono in pausa" / "riprendo" -> "pause_start" /
    "pause_end"; "ho fatto mezz'ora di pausa" -> {"action": "pause_add", "minutes": 30}; anything longer
    (a diary entry such as "ho finito il massetto") -> None."""
    t = " ".join((text or "").strip().split())
    t = re.sub(r"^[^\w/']+", "", t).strip()       # the buttons' emoji ("⏸️ Pausa", "▶️ Riprendo")
    if not t or len(t) > 80:
        return None
    pause = _parse_pause(t)
    if pause:
        return pause
    for action, rx in (("start", _START), ("stop", _STOP)):
        m = rx.match(t)
        if m:
            at = None
            if m.group("h"):
                h, mi = int(m.group("h")), int(m.group("m") or 0)
                if h > 23 or mi > 59:
                    return None
                at = time(h, mi)
            rest = (m.groupdict().get("rest") or "").strip()
            rest = re.sub(r"^(?:in|al|nel) cantiere\s*", "", rest, flags=re.I).strip()
            return {"action": action, "at": at, "rest": rest}
    return None


def distance_m(a: Optional[dict], b: Optional[dict]) -> Optional[int]:
    """Meters between two {"lat", "lon"} (None when one is missing)."""
    if not a or not b or a.get("lat") is None or b.get("lat") is None:
        return None
    r = 6371000.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.asin(math.sqrt(h))))


def distance_text(m: Optional[int]) -> str:
    if m is None:
        return ""
    if m <= ON_SITE_METERS:
        return "in cantiere" if m < 50 else f"a {m} m dal cantiere"
    return f"a {m / 1000:.1f} km dal cantiere".replace(".", ",") if m >= 1000 else f"a {m} m dal cantiere"


def far(m: Optional[int]) -> bool:
    return m is not None and m > ON_SITE_METERS


def round_hours(minutes: int) -> float:
    """Worked minutes -> hours to the half hour: past the last half hour, more than 15 minutes
    go up, up to 15 go down (1 h 15 -> 1, 1 h 16 -> 1.5, 1 h 45 -> 1.5, 1 h 46 -> 2)."""
    halves, rest = divmod(max(0, int(minutes)), 30)
    return (halves + (1 if rest > 15 else 0)) * 0.5


def fmt_duration(minutes: int) -> str:
    h, m = divmod(max(0, int(minutes)), 60)
    return f"{h} h {m:02d} min" if h and m else f"{h} h" if h else f"{m} min"


def hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def maps_link(loc: Optional[dict]) -> str:
    return f"https://maps.google.com/?q={loc['lat']:.6f},{loc['lon']:.6f}" if loc else ""


async def geocode(address: str) -> Optional[dict]:
    """The address's coordinates from OpenStreetMap (Nominatim) -> {"lat", "lon"} or None."""
    address = " ".join((address or "").split())
    if len(address) < 3:          # "Bra", "Asti": a town is enough
        return None
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": "mAIPAL/1.0 (cantieri)"}) as cl:
            r = await cl.get("https://nominatim.openstreetmap.org/search",
                             params={"q": address, "format": "json", "limit": 1, "countrycodes": "it", "accept-language": "it"})
            r.raise_for_status()
            hits = r.json()
    except Exception as e:
        logger.warning("geocoding failed for %r: %s", address[:80], str(e)[:200])
        return None
    if not hits:
        return None
    return {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"])}


def nearest(loc: dict, sites: list) -> Optional[tuple]:
    """[(site_id, {"lat","lon"}), ...] -> (site_id, meters) of the nearest within ON_SITE_METERS * 2."""
    best = None
    for sid, geo in sites:
        d = distance_m(loc, geo)
        if d is not None and (best is None or d < best[1]):
            best = (sid, d)
    return best if best and best[1] <= ON_SITE_METERS * 2 else None


def _selftest():
    assert parse_command("Sono arrivato")["action"] == "start"
    assert parse_command("sono arrivato in cantiere alle 8")["at"] == time(8, 0)
    assert parse_command("sono arrivato dai Rossi")["rest"] == "dai Rossi"
    assert parse_command("ho finito alle 17:30")["at"] == time(17, 30)
    assert parse_command("ho finito per oggi")["action"] == "stop"
    assert parse_command("ho finito il massetto del bagno") is None
    assert parse_command("Oggi 4 ore, posato il corrugato") is None
    assert parse_command("inizio a montare i sanitari") is None
    assert parse_command("Finito!")["action"] == "stop" and parse_command("arrivato")["action"] == "start"
    assert parse_command("sono arrivato dai Rossi alle 8:15") == {"action": "start", "at": time(8, 15), "rest": "dai Rossi"}
    assert parse_command("/fine")["action"] == "stop" and parse_command("ho finito alle 25") is None
    assert [round_hours(m) for m in (60, 75, 76, 90, 105, 106, 10, 16)] == [1.0, 1.0, 1.5, 1.5, 1.5, 2.0, 0.0, 0.5]
    assert fmt_duration(255) == "4 h 15 min"
    assert 1100 < distance_m({"lat": 45.0703, "lon": 7.6869}, {"lat": 45.0703, "lon": 7.7019}) < 1200


if __name__ == "__main__":
    _selftest()
    print("ok")


# ---- "quanti operai ci sono in cantiere?", "chi è in cantiere adesso?", "chi sta lavorando dai Rossi?",
# "chi è stato in cantiere oggi?": a question about the presences (the ones registered with
# «sono arrivato» / 📍), answered from them, not from the notes saved.
import re as _re
_PRES_WHO = _re.compile(r"\b(?:chi|quant[ie]|quali|nessuno|qualcuno|c'[eè]|ci\s+sono|ci\s+sta|presenti|presenz\w*|operai|operaio|"
                        r"collaborator\w*|squadr\w*|dipendent\w*|persone|ragazzi|elettricist\w*|idraulic\w*|muratori)\b", _re.I)
_PRES_WHERE = _re.compile(r"\b(?:in\s+cantier\w*|sul\s+cantiere|nei\s+cantieri|al\s+cantiere|ai\s+cantieri|cantier\w*|"
                          r"al\s+lavoro|a\s+lavorare|sta(?:nno)?\s+lavorando|lavora(?:no)?\s+(?:oggi|adesso|ora)|"
                          r"(?:è|e'|sono)\s+arrivat\w*|ha(?:nno)?\s+(?:iniziato|finito|timbrato)|presenze|presenti)\b", _re.I)


def presence_question(text: str) -> bool:
    t = " ".join((text or "").split())
    return bool(t) and bool(_PRES_WHO.search(t)) and bool(_PRES_WHERE.search(t))
