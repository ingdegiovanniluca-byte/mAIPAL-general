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


def parse_command(text: str) -> Optional[dict]:
    """"sono arrivato (dai Rossi) (alle 8)" -> {"action": "start", "at": time|None, "rest": "dai Rossi"};
    "ho finito (alle 17:30)" -> {"action": "stop", ...}; anything longer (a diary entry such as
    "ho finito il massetto") -> None."""
    t = " ".join((text or "").strip().split())
    if not t or len(t) > 80:
        return None
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
    """Worked minutes -> hours to the quarter (8 h 07 -> 8, 8 h 08 -> 8.25)."""
    return round(max(0, minutes) / 15) * 0.25


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
    if len(address) < 5:
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
    assert round_hours(487) == 8.0 and round_hours(488) == 8.25 and fmt_duration(255) == "4 h 15 min"
    assert 1100 < distance_m({"lat": 45.0703, "lon": 7.6869}, {"lat": 45.0703, "lon": 7.7019}) < 1200


if __name__ == "__main__":
    _selftest()
    print("ok")
