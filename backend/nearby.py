"""The clients near me (or near a place): "dammi i clienti vicino a me", "chi ho vicino entro 5 km",
"cantieri aperti vicino a me", "clienti vicino a Moncalieri". The question read from the words
(no model), the straight-line distance for the list, the road distance for the first ones
(OSRM, behind a swappable `router`; no answer = the straight line). Kept free of server imports.
"""
import difflib
import logging
import math
import re
from typing import Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_RADIUS_KM = 10
ROAD_FIRST = 3

_NEAR = re.compile(r"\bvicin[oiae]\s+(?:a|al|alla|allo|ai|alle|agli|ad|in|da|entro|nel\s+raggio)\b|\bho\s+vicin[oiae]\b|\bvicin[oiae]\s*\?|\b(?:qui|qua|più)\s+vicin[oiae]\b|\bnei\s+dintorni\b|\bnelle\s+vicinanze\b|"
                   r"\bintorno\s+a\s+me\b|\bqui\s+intorno\b|\bnei\s+paraggi\b|\battorno\s+a\s+me\b|\bin\s+zona\b", re.I)
# a request, not a note ("sono vicino al cantiere, arrivo tra 10 minuti" is not one)
_ASK = re.compile(r"^\s*(?:dammi|dimmi|elenc\w*|mostra\w*|trova\w*|cerca\w*|quali|quale|chi|quanti|quante|ci\s+sono|c'è|ho\s+(?:client|cantier|commess)|"
                  r"lista|l'elenco|elenco|fammi|che\s+client\w*|clienti|cantieri|commesse|preventivi|manutenzioni|dove\s+posso|posso)\b", re.I)
_WHO = re.compile(r"\b(?:client[ei]|cantier[ei]|commess[ae]|lavori|chi\b|dove\s+(?:posso|passo)|visit\w*|manutenzion\w*|preventiv\w*|opportunit\w*)", re.I)
_ME = re.compile(r"\b(?:a\s+me|da\s+me|qui|qua|dove\s+sono|mia\s+posizione|intorno\s+a\s+me|attorno\s+a\s+me|in\s+zona|nei\s+paraggi|nei\s+dintorni)\b", re.I)
_PLACE = re.compile(r"\bvicin[oiae]\s+(?:a|al|alla|allo|ai|alle|agli|ad|in)\s+(?!me\b|noi\b)(.+?)(?:,?\s+entro\b|,?\s+nel\s+raggio\b|,?\s+a\s+meno\b|[?!;]|\.\s|\.$|$)", re.I)
_RADIUS = re.compile(r"\b(?:entro|nel\s+raggio\s+di|a\s+meno\s+di|raggio)\s+(\d+(?:[.,]\d+)?)\s*(km|chilometri|kilometri|m|metri)\b", re.I)


_WHO_WORDS = ("clienti", "cliente", "cantieri", "cantiere", "commesse", "commessa")


def _who(t: str) -> bool:
    """Who is asked for, also misspelled ("clinenti", "clineti", "cantireri")."""
    if _WHO.search(t):
        return True
    return any(_who_word(w) for w in re.findall(r"[a-zà-ù]{6,}", t.lower()))


def _who_plural(w: str) -> bool:
    """A list asked for, misspelled at the start ("clinenti vicino a me"); "cantiere vicino al bar, arrivo" is a note."""
    w = w.lower()
    return w not in ("cliente", "cantiere", "commessa") and bool(difflib.get_close_matches(w, ("clienti", "cantieri", "commesse"), n=1, cutoff=0.7))


def _who_word(w: str) -> bool:
    return bool(difflib.get_close_matches(w.lower(), _WHO_WORDS, n=1, cutoff=0.7))


def said(text: str) -> Optional[dict]:
    """The question, or None: {"me": bool (my position needed), "place": str|None, "radius_km": float|None,
    "filter": "aperte"|"preventivi"|"manutenzione"|"opportunita"|None}"""
    t = " ".join((text or "").split())
    if not t or not _NEAR.search(t) or not _who(t) or not (_ASK.search(t) or t.rstrip().endswith("?")
                                                                        or _who_plural((t.split() or [""])[0])):
        return None
    m = _PLACE.search(t)
    place = m.group(1).strip(" .,") if m else None
    if place:   # "vicino a al cantiere di Luca": the doubled preposition out
        place = re.sub(r"^(?:(?:a|al|alla|allo|ai|alle|agli|ad|in)\s+)+(?=\S)", "", place, flags=re.I).strip() or None
    if place and re.fullmatch(r"(?:me|noi|qui|qua|casa\s+mia)", place, re.I):
        place = None
    r = _RADIUS.search(t)
    radius = None
    if r:
        radius = float(r.group(1).replace(",", "."))
        if r.group(2).lower().startswith("m") and r.group(2).lower() not in ("km",):
            radius = radius / 1000
    low = (t.replace(m.group(0), " ") if m else t).lower()   # the place's words don't make a filter
    flt = ("manutenzione" if "manutenz" in low else "preventivi" if "preventiv" in low
           else "opportunita" if re.search(r"opportunit|posso\s+(?:andare|passare)|visitare|andare\s+a\s+trovare|passare\s+a\s+trovare", low)
           else "aperte" if re.search(r"\b(?:aperte?|in\s+corso|in\s+lavorazione|cantier)", low) else None)
    return {"me": not place, "place": place, "radius_km": radius, "filter": flt}


def _num(x: float) -> str:
    return f"{x:g}".replace(".", ",")


def km(m: Optional[float]) -> str:
    if m is None:
        return ""
    return f"{int(round(m))} m" if m < 1000 else f"{m / 1000:.1f} km".replace(".", ",")


def maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}"


def distance_m(a: dict, b: dict) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


async def osrm(a: dict, b: dict) -> Optional[dict]:
    """The road between two points (OSRM's public server) -> {"m", "min"} or None."""
    url = f"https://router.project-osrm.org/route/v1/driving/{a['lon']:.6f},{a['lat']:.6f};{b['lon']:.6f},{b['lat']:.6f}"
    try:
        async with httpx.AsyncClient(timeout=6.0, headers={"User-Agent": "mAIPAL/1.0 (vicino a me)"}) as cl:
            r = await cl.get(url, params={"overview": "false"})
            r.raise_for_status()
            route = (r.json().get("routes") or [None])[0]
    except Exception as e:
        logger.warning("road distance not available: %s", str(e)[:200])
        return None
    if not route:
        return None
    return {"m": float(route["distance"]), "min": round(float(route["duration"]) / 60)}


router: Callable[[dict, dict], Awaitable[Optional[dict]]] = osrm


def message(res: dict) -> str:
    """The answer as text (Telegram, and the chat's plain version)."""
    where = res.get("where") or (f"vicino a {res['place']}" if res.get("place") else "vicino a te")
    rows = res["rows"]
    if not rows:
        out = f"📍 Nessun cliente {where} entro {_num(res['radius_km'])} km."
        if res.get("nearest"):
            n = res["nearest"]
            out += f" Il più vicino è {n['name']}, a {km(n['distance_m'])}: chiedimi «entro {math.ceil(n['distance_m'] / 1000)} km» per vederlo."
    else:
        out = f"📍 {len(rows)} {'cliente' if len(rows) == 1 else 'clienti'} {where} entro {_num(res['radius_km'])} km:"
        for i, r in enumerate(rows, 1):
            dist = (f"{km(r['road_m'])} su strada, {r['road_min']} min" if r.get("road_m") is not None else km(r["distance_m"]))
            line = f"\n{i}. *{r['name']}* — {dist}"
            if r.get("via"):
                line += f" ({r['via']})"
            for c in r.get("commesse") or []:
                line += f"\n   🏗 {c['title']} · {c['stato']}"
            for o in r.get("opportunities") or []:
                line += f"\n   💡 {o}"
            if r.get("phone"):
                line += f"\n   📞 {r['phone']}"
            line += f"\n   🧭 {r['maps']}"
            out += line
    missing = res.get("missing") or {}
    if missing.get("no_address") or missing.get("not_found") or missing.get("pending"):
        bits = ([f"{missing['no_address']} senza indirizzo"] if missing.get("no_address") else []) + \
               ([f"{missing['not_found']} con un indirizzo che non trovo"] if missing.get("not_found") else []) + \
               ([f"{missing['pending']} ancora da localizzare (riprova tra qualche minuto)"] if missing.get("pending") else [])
        out += "\n\nNon nell'elenco: " + ", ".join(bits) + "."
    return out
