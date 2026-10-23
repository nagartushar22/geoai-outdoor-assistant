import asyncio
import math
import time
from typing import Any

import httpx

from app import config


class DataSourceError(RuntimeError):
    pass


class TTLCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def put(self, key: str, value: Any, ttl: int = 600) -> None:
        self._data[key] = (time.monotonic() + ttl, value)


cache = TTLCache()
_nominatim_lock = asyncio.Lock()
_last_nominatim_call = 0.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


async def _nominatim_search(params: dict) -> list[dict]:
    """Make a throttled, identified, end-user-triggered Nominatim request."""
    global _last_nominatim_call
    async with _nominatim_lock:
        delay = 1.05 - (time.monotonic() - _last_nominatim_call)
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(
                timeout=15.0, headers={"User-Agent": config.OSM_USER_AGENT}
            ) as client:
                _last_nominatim_call = time.monotonic()
                response = await client.get(config.NOMINATIM_URL, params=params)
                response.raise_for_status()
                results = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DataSourceError("The OpenStreetMap search is unavailable right now.") from exc
    if not isinstance(results, list):
        raise DataSourceError("The OpenStreetMap search returned an unexpected response.")
    return results


async def geocode(place: str) -> dict:
    key = "geocode:" + place.strip().casefold()
    cached = cache.get(key)
    if cached is not None:
        return cached

    results = await _nominatim_search(
        {"q": place, "format": "jsonv2", "limit": 1}
    )

    if not results:
        raise DataSourceError(f"I could not find the location ‘{place}’. Please be more specific.")
    item = results[0]
    found = {
        "lat": float(item["lat"]),
        "lon": float(item["lon"]),
        "display_name": item.get("display_name", place),
    }
    cache.put(key, found, ttl=86_400)
    return found


def _overpass_query(lat: float, lon: float, radius_m: int) -> str:
    return f"""[out:json][timeout:20];
(
  nwr(around:{radius_m},{lat},{lon})[leisure~\"^(park|pitch|sports_centre|golf_course|track|nature_reserve|recreation_ground|garden)$\"];
  nwr(around:{radius_m},{lat},{lon})[amenity=picnic_site];
  nwr(around:{radius_m},{lat},{lon})[tourism~\"^(viewpoint|attraction)$\"];
  nwr(around:{radius_m},{lat},{lon})[route~\"^(hiking|foot|bicycle|mtb)$\"];
  nwr(around:{radius_m},{lat},{lon})[natural~\"^(wood|water|beach|wetland)$\"];
  nwr(around:{radius_m},{lat},{lon})[landuse~\"^(forest|industrial)$\"];
  nwr(around:{radius_m},{lat},{lon})[man_made=works];
  nwr(around:{radius_m},{lat},{lon})[highway~\"^(motorway|trunk|primary|secondary)$\"];
);
out center 180;"""


async def nearby_osm(lat: float, lon: float, radius_km: float) -> list[dict]:
    key = f"osm:{lat:.4f}:{lon:.4f}:{radius_km:.1f}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    payload = None
    last_error: Exception | None = None
    query = _overpass_query(lat, lon, int(radius_km * 1000))
    for endpoint in config.OVERPASS_URLS:
        try:
            async with httpx.AsyncClient(
                timeout=config.OVERPASS_TIMEOUT_SECONDS,
                headers={"User-Agent": config.OSM_USER_AGENT},
            ) as client:
                response = await client.post(endpoint, data={"data": query})
                response.raise_for_status()
                payload = response.json()
            break
        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
    if payload is None:
        raise DataSourceError(
            "The OpenStreetMap place search is unavailable. Please try again shortly."
        ) from last_error

    elements = []
    for item in payload.get("elements", []):
        tags = item.get("tags", {})
        center = item.get("center", {})
        item_lat = item.get("lat", center.get("lat"))
        item_lon = item.get("lon", center.get("lon"))
        if item_lat is None or item_lon is None:
            continue
        elements.append(
            {
                "id": f"{item.get('type')}:{item.get('id')}",
                "lat": float(item_lat),
                "lon": float(item_lon),
                "tags": tags,
                "distance_km": haversine_km(lat, lon, float(item_lat), float(item_lon)),
            }
        )
    cache.put(key, elements, ttl=900)
    return elements


async def nearby_nominatim(
    lat: float, lon: float, radius_km: float, activity: str
) -> list[dict]:
    """Small best-match fallback for an interactive request when Overpass is down.

    Nominatim does not return a complete POI inventory, so this deliberately uses
    one bounded search and lets the response disclose that the list may be partial.
    """
    terms = {
        "running": "park",
        "cycling": "cycle route",
        "golf": "golf course",
        "cricket": "cricket ground",
        "football": "football pitch",
        "tennis": "tennis court",
        "hiking": "nature reserve",
        "picnic": "park",
        "outdoor_event": "park",
        "photography": "viewpoint",
    }
    term = terms.get(activity, "park")
    key = f"nominatim-places:{lat:.4f}:{lon:.4f}:{radius_km:.1f}:{term}"
    cached = cache.get(key)
    if cached is not None:
        return cached

    lat_delta = radius_km / 111.0
    cos_lat = max(0.1, abs(math.cos(math.radians(lat))))
    lon_delta = radius_km / (111.0 * cos_lat)
    viewbox = ",".join(
        f"{value:.6f}"
        for value in (lon - lon_delta, lat + lat_delta, lon + lon_delta, lat - lat_delta)
    )
    results = await _nominatim_search(
        {
            "q": term,
            "format": "jsonv2",
            "limit": 10,
            "layer": "poi",
            "viewbox": viewbox,
            "bounded": 1,
            "extratags": 1,
        }
    )

    leisure_types = {
        "park", "pitch", "sports_centre", "golf_course", "track",
        "nature_reserve", "recreation_ground", "garden",
    }
    tourism_types = {"viewpoint", "attraction"}
    elements = []
    for item in results:
        try:
            item_lat, item_lon = float(item["lat"]), float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue
        item_type = str(item.get("type", "")).casefold()
        raw_tags = item.get("extratags") or {}
        tags = {str(k): str(v) for k, v in raw_tags.items()}
        name = item.get("name")
        if not name:
            name = str(item.get("display_name", "")).split(",", 1)[0].strip()
        if name:
            tags.setdefault("name", str(name))
        if item_type in leisure_types:
            tags.setdefault("leisure", item_type)
        elif item_type in tourism_types:
            tags.setdefault("tourism", item_type)
        elif item_type == "picnic_site":
            tags.setdefault("amenity", "picnic_site")
        elif item_type in {"wood", "beach"}:
            tags.setdefault("natural", item_type)
        else:
            continue
        osm_type = str(item.get("osm_type", "place")).casefold()
        osm_id = item.get("osm_id", item.get("place_id", "unknown"))
        elements.append(
            {
                "id": f"{osm_type}:{osm_id}",
                "lat": item_lat,
                "lon": item_lon,
                "tags": tags,
                "distance_km": haversine_km(lat, lon, item_lat, item_lon),
            }
        )
    cache.put(key, elements, ttl=900)
    return elements


async def fetch_weather(lat: float, lon: float) -> dict:
    key = f"weather:{lat:.3f}:{lon:.3f}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": ",".join(
            [
                "temperature_2m",
                "apparent_temperature",
                "precipitation_probability",
                "precipitation",
                "wind_speed_10m",
                "wind_direction_10m",
                "wind_gusts_10m",
                "uv_index",
                "is_day",
            ]
        ),
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.APP_TIMEZONE,
    }
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            response.raise_for_status()
            weather = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise DataSourceError("The weather forecast service is unavailable.") from exc
    cache.put(key, weather, ttl=900)
    return weather


async def fetch_air_quality(lat: float, lon: float) -> dict:
    key = f"air:{lat:.3f}:{lon:.3f}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "us_aqi,pm2_5,pm10",
        "forecast_days": config.FORECAST_DAYS,
        "timezone": config.APP_TIMEZONE,
    }
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.get(
                "https://air-quality-api.open-meteo.com/v1/air-quality", params=params
            )
            response.raise_for_status()
            air = response.json()
    except (httpx.HTTPError, ValueError):
        air = {"hourly": {"time": [], "us_aqi": [], "pm2_5": [], "pm10": []}, "unavailable": True}
    cache.put(key, air, ttl=900)
    return air


async def route_estimate(origin: tuple[float, float], destination: tuple[float, float]) -> dict | None:
    # OSRM returns a route estimate from its road graph; this is not live traffic.
    coords = f"{origin[1]},{origin[0]};{destination[1]},{destination[0]}"
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.get(
                f"{config.OSRM_URL}/route/v1/driving/{coords}",
                params={"overview": "false", "steps": "false"},
            )
            response.raise_for_status()
            routes = response.json().get("routes", [])
            if not routes:
                return None
            return {
                "duration_minutes": round(routes[0]["duration"] / 60),
                "distance_km": round(routes[0]["distance"] / 1000, 1),
            }
    except (httpx.HTTPError, ValueError, KeyError, IndexError):
        return None

