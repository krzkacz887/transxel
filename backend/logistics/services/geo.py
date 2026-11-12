"""
Integracja z zewnętrznymi API map:

* Nominatim (OpenStreetMap) – geokodowanie adresów,
* OSRM – macierz czasów/odległości przejazdu (table) i geometria trasy (route).

Gdy OSRM jest niedostępny, liczymy przybliżenie po linii prostej (haversine),
żeby aplikacja nadal działała (np. offline, w testach).
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass
from typing import Optional, Sequence

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger("logistics")

LatLng = tuple[float, float]


class GeoError(Exception):
    pass


@dataclass
class GeocodeResult:
    lat: float
    lng: float
    display_name: str


def _headers():
    return {"User-Agent": settings.GEO_USER_AGENT, "Accept-Language": "pl"}


def _cache_key(prefix: str, value: str) -> str:
    return f"geo:{prefix}:{hashlib.md5(value.encode('utf-8')).hexdigest()}"


# ----------------------------------------------------------------- Nominatim
def geocode(query: str, limit: int = 5) -> list[GeocodeResult]:
    query = (query or "").strip()
    if not query:
        return []
    key = _cache_key("search", f"{query}|{limit}")
    cached = cache.get(key)
    if cached is not None:
        return cached
    params = {"q": query, "format": "jsonv2", "limit": limit, "addressdetails": 0}
    if settings.GEO_COUNTRY_CODES:
        params["countrycodes"] = settings.GEO_COUNTRY_CODES
    try:
        r = requests.get(f"{settings.NOMINATIM_URL}/search", params=params,
                         headers=_headers(), timeout=settings.GEO_TIMEOUT_S)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError) as exc:
        raise GeoError(f"Błąd geokodowania: {exc}") from exc
    results = [GeocodeResult(float(x["lat"]), float(x["lon"]), x.get("display_name", query)) for x in data]
    cache.set(key, results, 60 * 60 * 24)
    return results


def reverse_geocode(lat: float, lng: float) -> Optional[str]:
    key = _cache_key("reverse", f"{lat:.5f},{lng:.5f}")
    cached = cache.get(key)
    if cached is not None:
        return cached
    try:
        r = requests.get(f"{settings.NOMINATIM_URL}/reverse",
                         params={"lat": lat, "lon": lng, "format": "jsonv2"},
                         headers=_headers(), timeout=settings.GEO_TIMEOUT_S)
        r.raise_for_status()
        name = r.json().get("display_name")
    except (requests.RequestException, ValueError) as exc:
        raise GeoError(f"Błąd geokodowania odwrotnego: {exc}") from exc
    if name:
        cache.set(key, name, 60 * 60 * 24)
    return name


# ---------------------------------------------------------------------- OSRM
def _coords(points: Sequence[LatLng]) -> str:
    # OSRM oczekuje kolejności lng,lat
    return ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in points)


def haversine_m(a: LatLng, b: LatLng) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def _fallback_matrix(points: Sequence[LatLng]):
    cfg = settings.ROUTING
    speed = cfg["FALLBACK_SPEED_KMH"] / 3.6
    detour = cfg["FALLBACK_DETOUR"]
    dist = [[haversine_m(a, b) * detour for b in points] for a in points]
    dur = [[d / speed for d in row] for row in dist]
    return dur, dist


def travel_matrix(points: Sequence[LatLng]) -> tuple[list[list[float]], list[list[float]], str]:
    """Zwraca (czasy_s, odległości_m, źródło). Źródło: 'osrm' albo 'fallback'."""
    if len(points) < 2:
        return [[0.0] * len(points) for _ in points], [[0.0] * len(points) for _ in points], "trivial"
    url = f"{settings.OSRM_URL}/table/v1/driving/{_coords(points)}"
    try:
        r = requests.get(url, params={"annotations": "duration,distance"},
                         headers=_headers(), timeout=settings.GEO_TIMEOUT_S * 2)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "Ok":
            raise GeoError(data.get("message", data.get("code")))
        dur, dist = data["durations"], data["distances"]
        # null = brak połączenia drogowego – zastępujemy szacunkiem
        fb_dur, fb_dist = _fallback_matrix(points)
        for i in range(len(points)):
            for j in range(len(points)):
                if dur[i][j] is None:
                    dur[i][j] = fb_dur[i][j] * 3
                if dist[i][j] is None:
                    dist[i][j] = fb_dist[i][j]
        return dur, dist, "osrm"
    except (requests.RequestException, ValueError, KeyError, GeoError) as exc:
        log.warning("OSRM table niedostępny (%s) – używam przybliżenia", exc)
        dur, dist = _fallback_matrix(points)
        return dur, dist, "fallback"


def route_geometry(points: Sequence[LatLng]) -> dict:
    """Geometria trasy (GeoJSON LineString) przez punkty w podanej kolejności.

    Publiczny OSRM przyjmuje ograniczoną liczbę punktów, więc długie trasy
    dzielimy na odcinki i sklejamy.
    """
    if len(points) < 2:
        return {"type": "LineString", "coordinates": [[p[1], p[0]] for p in points],
                "distance_m": 0, "duration_s": 0, "source": "trivial"}
    chunk = 90
    coords: list[list[float]] = []
    distance = duration = 0.0
    try:
        i = 0
        while i < len(points) - 1:
            part = points[i:i + chunk]
            url = f"{settings.OSRM_URL}/route/v1/driving/{_coords(part)}"
            r = requests.get(url, params={"overview": "full", "geometries": "geojson"},
                             headers=_headers(), timeout=settings.GEO_TIMEOUT_S * 2)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "Ok":
                raise GeoError(data.get("message", data.get("code")))
            route = data["routes"][0]
            seg = route["geometry"]["coordinates"]
            coords.extend(seg if not coords else seg[1:])
            distance += route["distance"]
            duration += route["duration"]
            i += chunk - 1
        return {"type": "LineString", "coordinates": coords,
                "distance_m": distance, "duration_s": duration, "source": "osrm"}
    except (requests.RequestException, ValueError, KeyError, IndexError, GeoError) as exc:
        log.warning("OSRM route niedostępny (%s) – rysuję linie proste", exc)
        _, dist = _fallback_matrix(points)
        speed = settings.ROUTING["FALLBACK_SPEED_KMH"] / 3.6
        d = sum(dist[k][k + 1] for k in range(len(points) - 1))
        return {"type": "LineString", "coordinates": [[p[1], p[0]] for p in points],
                "distance_m": d, "duration_s": d / speed, "source": "fallback"}
