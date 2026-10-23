from datetime import datetime
from math import atan2, cos, degrees, radians, sin
from zoneinfo import ZoneInfo

from app import config
from app.data_sources import haversine_km


ACTIVITY_LABELS = {
    "running": "running or jogging",
    "cycling": "cycling",
    "golf": "golf",
    "cricket": "cricket",
    "football": "outdoor football",
    "tennis": "outdoor tennis",
    "hiking": "hiking or a nature walk",
    "picnic": "a picnic or park outing",
    "outdoor_event": "an outdoor event or gathering",
    "photography": "outdoor photography",
}

ACTIVE = {"running", "cycling", "cricket", "football", "tennis", "hiking"}


def _sports(tags: dict) -> set[str]:
    raw = tags.get("sport", tags.get("sports", ""))
    return {part.strip().casefold() for part in raw.replace(";", ",").split(",") if part.strip()}


def is_candidate(tags: dict) -> bool:
    return bool(
        tags.get("leisure") in {
            "park", "pitch", "sports_centre", "golf_course", "track",
            "nature_reserve", "recreation_ground", "garden",
        }
        or tags.get("amenity") == "picnic_site"
        or tags.get("tourism") in {"viewpoint", "attraction"}
        or tags.get("route") in {"hiking", "foot", "bicycle", "mtb"}
        or tags.get("natural") in {"wood", "beach"}
    )


def activity_match(tags: dict, activity: str) -> tuple[bool, str]:
    leisure = tags.get("leisure", "")
    sports = _sports(tags)
    route = tags.get("route", "")
    if activity == "golf":
        exact = leisure == "golf_course" or "golf" in sports
    elif activity == "cricket":
        exact = "cricket" in sports
    elif activity == "football":
        exact = bool(sports & {"soccer", "football"})
    elif activity == "tennis":
        exact = "tennis" in sports
    elif activity == "running":
        exact = leisure == "track" or "running" in sports
    elif activity == "cycling":
        exact = route in {"bicycle", "mtb"} or "cycling" in sports
    elif activity == "hiking":
        exact = route in {"hiking", "foot"} or tags.get("natural") in {"wood", "beach"} or tags.get("leisure") == "nature_reserve"
    elif activity == "picnic":
        exact = tags.get("amenity") == "picnic_site" or leisure in {"park", "garden", "recreation_ground"}
    elif activity == "outdoor_event":
        exact = leisure in {"park", "recreation_ground", "sports_centre"} or tags.get("tourism") == "attraction"
    elif activity == "photography":
        exact = tags.get("tourism") in {"viewpoint", "attraction"} or tags.get("natural") in {"wood", "beach"} or leisure in {"park", "garden"}
    else:
        exact = False

    if exact:
        return True, "Mapped for this activity"

    # General green space is an honest fallback for activities without a mapped specialist venue.
    fallback = leisure in {"park", "recreation_ground", "garden", "sports_centre"} or tags.get("amenity") == "picnic_site"
    if fallback and activity not in {"golf", "cricket", "football", "tennis"}:
        return True, "General outdoor space; verify activity access"
    if fallback and activity in {"cricket", "football", "tennis"} and leisure == "sports_centre":
        return True, "Sports centre; specific field availability is not confirmed"
    if fallback and activity in {"cricket", "football", "tennis"} and leisure == "pitch" and not sports:
        return True, "Mapped pitch; sport type is not specified"
    return False, ""


def get_candidate_places(elements: list[dict], activity: str, origin: dict, radius_km: float) -> list[dict]:
    matches = []
    seen: set[tuple[str, int, int]] = set()
    for element in elements:
        tags = element["tags"]
        if not is_candidate(tags):
            continue
        distance = haversine_km(origin["lat"], origin["lon"], element["lat"], element["lon"])
        if distance > radius_km:
            continue
        matched, match_reason = activity_match(tags, activity)
        if not matched:
            continue
        name = tags.get("name") or tags.get("name:en")
        if not name:
            kind = tags.get("leisure") or tags.get("tourism") or tags.get("amenity") or "outdoor place"
            name = f"Unnamed mapped {kind} ({element['id']})"
        key = (name.casefold(), round(element["lat"] * 10000), round(element["lon"] * 10000))
        if key in seen:
            continue
        seen.add(key)
        matches.append({**element, "name": name, "match_reason": match_reason, "distance_km": distance})
    matches.sort(key=lambda place: ("General outdoor space" in place["match_reason"], place["distance_km"]))
    return matches[:8]


def _bearing_degrees(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = radians(lat1), radians(lat2)
    dl = radians(lon2 - lon1)
    y = sin(dl) * cos(p2)
    x = cos(p1) * sin(p2) - sin(p1) * cos(p2) * cos(dl)
    return (degrees(atan2(y, x)) + 360) % 360


def _angle_gap(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def _series_by_time(data: dict, key: str) -> dict[str, float | int | None]:
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    values = hourly.get(key, [])
    return {t: values[i] if i < len(values) else None for i, t in enumerate(times)}


def _local_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(config.APP_TIMEZONE))
    return parsed.astimezone(ZoneInfo(config.APP_TIMEZONE))


def _format_hour(value: datetime) -> str:
    hour = value.strftime("%I").lstrip("0") or "12"
    return f"{value.strftime('%a %d %b')}, {hour}:{value.strftime('%M %p')}"


def _nearby_context(place: dict, elements: list[dict], wind_direction: float | None) -> tuple[list[str], int]:
    context: list[str] = []
    score_adjustment = 0
    nearby_green = False
    nearby_roads: list[float] = []
    upwind_industry = False
    nearby_water = False
    for feature in elements:
        if feature["id"] == place["id"]:
            continue
        tags = feature["tags"]
        distance = haversine_km(place["lat"], place["lon"], feature["lat"], feature["lon"])
        if distance > 5:
            continue
        if (tags.get("leisure") in {"park", "garden", "nature_reserve"} or tags.get("landuse") == "forest" or tags.get("natural") == "wood") and distance <= 0.5:
            nearby_green = True
        if tags.get("natural") in {"water", "wetland"} or tags.get("waterway") or tags.get("landuse") == "reservoir":
            if distance <= 0.5:
                nearby_water = True
        if tags.get("highway") in {"motorway", "trunk", "primary", "secondary"} and distance <= 0.3:
            nearby_roads.append(distance)
        industrial = tags.get("landuse") == "industrial" or tags.get("man_made") == "works" or bool(tags.get("industrial"))
        if industrial and distance <= 5 and wind_direction is not None:
            source_bearing = _bearing_degrees(place["lat"], place["lon"], feature["lat"], feature["lon"])
            if _angle_gap(source_bearing, wind_direction) <= 45:
                upwind_industry = True

    if nearby_green:
        context.append("Mapped green space nearby")
        score_adjustment += 5
    if nearby_water:
        context.append("Mapped water feature within about 500 m")
        score_adjustment += 2
    if nearby_roads:
        context.append("Mapped major road within about 300 m")
        score_adjustment -= 5
    if upwind_industry:
        context.append("Mapped industrial feature may be upwind; this is not a pollution measurement")
        score_adjustment -= 8
    return context, score_adjustment


def _activity_weights(activity: str) -> dict[str, float]:
    if activity in ACTIVE:
        return {"rain": 0.30, "wind": 0.20, "aqi": 0.25, "heat": 0.25}
    if activity in {"outdoor_event", "photography"}:
        return {"rain": 0.35, "wind": 0.15, "aqi": 0.20, "heat": 0.30}
    return {"rain": 0.30, "wind": 0.15, "aqi": 0.25, "heat": 0.30}


def rank_place(
    place: dict,
    activity: str,
    elements: list[dict],
    weather: dict,
    air: dict,
    start_local: str,
    end_local: str,
    personal_notes: list[str],
) -> dict | None:
    wx = weather.get("hourly", {})
    if not wx.get("time"):
        return None
    aqi_by_time = _series_by_time(air, "us_aqi")
    start, end = _local_datetime(start_local), _local_datetime(end_local)
    weights = _activity_weights(activity)
    sensitive_profile = any(
        note.casefold().find(term) >= 0
        for note in personal_notes
        for term in ("asthma", "child", "children", "senior", "pregnan")
    )
    best = None
    for index, time_text in enumerate(wx["time"]):
        try:
            when = _local_datetime(time_text)
        except ValueError:
            continue
        if when < start or when > end:
            continue

        def val(key: str, default: float | None = None):
            values = wx.get(key, [])
            return values[index] if index < len(values) and values[index] is not None else default

        temperature = val("apparent_temperature", val("temperature_2m"))
        rain = val("precipitation_probability", 0)
        wind = val("wind_speed_10m", 0)
        gust = val("wind_gusts_10m", wind)
        uv = val("uv_index", 0)
        daylight = val("is_day", 1)
        aqi = aqi_by_time.get(time_text)
        score = 100.0
        reasons = []
        if temperature is not None:
            target_midpoint = 22 if activity in ACTIVE else 24
            heat_weight = 1.0 if activity in ACTIVE else 0.75
            temp_penalty = max(0, abs(float(temperature) - target_midpoint) - 4) * 2.0 * heat_weight
            score -= temp_penalty * weights["heat"] * 2
            reasons.append(f"feels-like temperature {float(temperature):.0f} °C")
        if rain is not None:
            score -= float(rain) * weights["rain"] * 0.48
            reasons.append(f"rain chance {float(rain):.0f}%")
        if wind is not None:
            score -= max(0, float(wind) - 15) * weights["wind"] * 1.4
            reasons.append(f"wind {float(wind):.0f} km/h")
        if gust is not None:
            score -= max(0, float(gust) - 35) * 0.35
        if aqi is not None:
            factor = 1.45 if sensitive_profile else 1.0
            score -= max(0, float(aqi) - 50) * weights["aqi"] * 0.35 * factor
            reasons.append(f"forecast US AQI {float(aqi):.0f}")
        if uv is not None:
            score -= max(0, float(uv) - 6) * 1.5
        if not bool(daylight) and activity in {"running", "cycling", "hiking", "picnic", "cricket", "football", "tennis", "golf"}:
            score -= 10
            reasons.append("forecast is after daylight")

        context, context_adjustment = _nearby_context(
            place, elements, val("wind_direction_10m")
        )
        score += context_adjustment
        if place["match_reason"] == "Mapped for this activity":
            score += 8
        elif "General outdoor" in place["match_reason"] or "not confirmed" in place["match_reason"]:
            score -= 8
        score -= max(0, place["distance_km"] - 5) * 0.65
        entry = {
            "name": place["name"],
            "activity_match": place["match_reason"],
            "distance_km": round(place["distance_km"], 1),
            "best_time": _format_hour(when),
            "score": max(0, min(100, round(score))),
            "temperature_c": round(float(temperature), 1) if temperature is not None else None,
            "rain_probability_percent": round(float(rain), 1) if rain is not None else None,
            "wind_kmh": round(float(wind), 1) if wind is not None else None,
            "us_aqi": round(float(aqi), 1) if aqi is not None else None,
            "context": context,
            "reasons": reasons,
            "_sort": score,
            "_place": place,
        }
        if best is None or score > best["_sort"]:
            best = entry
    return best

