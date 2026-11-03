"""The forecast for a site (specifica commesse AUT-G1-01, PA-11): one day's rain probability,
wind and temperatures at a position, and whether they may stop the works (the organization's
thresholds). Behind a small interface - `provider` can be swapped (tests, another service);
the default is Open-Meteo (no key needed). Never blocks a reminder: no answer = no forecast.
"""
import logging
from datetime import date
from typing import Awaitable, Callable, Optional

import httpx

logger = logging.getLogger(__name__)
_CACHE: dict = {}


async def open_meteo(lat: float, lon: float, day: date) -> Optional[dict]:
    """-> {"rain_pct", "wind_kmh", "tmin", "tmax", "code"} for that day, or None."""
    params = {"latitude": round(lat, 4), "longitude": round(lon, 4), "timezone": "Europe/Rome",
              "daily": "precipitation_probability_max,wind_speed_10m_max,temperature_2m_max,temperature_2m_min,weather_code",
              "start_date": day.isoformat(), "end_date": day.isoformat()}
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params=params)
        r.raise_for_status()
        d = r.json().get("daily") or {}
    def first(k):
        v = d.get(k) or [None]
        return v[0]
    return {"rain_pct": first("precipitation_probability_max"), "wind_kmh": first("wind_speed_10m_max"),
            "tmin": first("temperature_2m_min"), "tmax": first("temperature_2m_max"), "code": first("weather_code")}


provider: Callable[[float, float, date], Awaitable[Optional[dict]]] = open_meteo


async def forecast(lat: Optional[float], lon: Optional[float], day: date) -> Optional[dict]:
    if lat is None or lon is None:
        return None
    key = (round(lat, 3), round(lon, 3), day.isoformat())
    if key in _CACHE:
        return _CACHE[key]
    try:
        f = await provider(lat, lon, day)
    except Exception:
        logger.warning("forecast not available for %s", key)
        return None
    _CACHE[key] = f
    return f


def alerts(f: Optional[dict], s: dict) -> list:
    """What may stop the works, by the organization's thresholds (rain %, wind km/h, temperatures)."""
    if not f:
        return []
    out = []
    if (f.get("rain_pct") or 0) >= s.get("weather_alert_rain_pct", 60):
        out.append(f"pioggia probabile ({int(f['rain_pct'])}%)")
    if (f.get("wind_kmh") or 0) >= s.get("weather_alert_wind_kmh", 40):
        out.append(f"vento forte ({int(f['wind_kmh'])} km/h)")
    if f.get("tmin") is not None and f["tmin"] <= s.get("weather_alert_temp_min", 0):
        out.append(f"freddo ({round(f['tmin'])} °C)")
    if f.get("tmax") is not None and f["tmax"] >= s.get("weather_alert_temp_max", 35):
        out.append(f"caldo ({round(f['tmax'])} °C)")
    return out


def line(f: Optional[dict], s: dict) -> str:
    """One line for the messages: the forecast and, when it may stop the works, a warning."""
    if not f:
        return ""
    parts = []
    if f.get("tmin") is not None and f.get("tmax") is not None:
        parts.append(f"{round(f['tmin'])}–{round(f['tmax'])} °C")
    if f.get("rain_pct") is not None:
        parts.append(f"pioggia {int(f['rain_pct'])}%")
    if f.get("wind_kmh") is not None:
        parts.append(f"vento {int(f['wind_kmh'])} km/h")
    warn = alerts(f, s)
    return "🌦 Meteo: " + ", ".join(parts) + (f"\n⚠️ Attenzione: {', '.join(warn)} — potrebbe impedire i lavori." if warn else "")
