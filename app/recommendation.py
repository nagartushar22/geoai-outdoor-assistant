import asyncio
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app import config
from app.data_sources import (
    DataSourceError,
    fetch_air_quality,
    fetch_weather,
    geocode,
    nearby_nominatim,
    nearby_osm,
    route_estimate,
)
from app.llm import ModelUnavailable, local_model
from app.schemas import CandidateRecommendation, RecommendationResponse
from app.scoring import ACTIVITY_LABELS, get_candidate_places, rank_place


ALLOWED_ACTIVITIES = set(ACTIVITY_LABELS)


def _parse_window(intent: dict) -> tuple[datetime, datetime] | None:
    start_text, end_text = intent.get("start_local"), intent.get("end_local")
    if not start_text or not end_text:
        return None
    try:
        start = datetime.fromisoformat(start_text)
        end = datetime.fromisoformat(end_text)
    except (TypeError, ValueError):
        return None
    zone = ZoneInfo(config.APP_TIMEZONE)
    if start.tzinfo is None:
        start = start.replace(tzinfo=zone)
    if end.tzinfo is None:
        end = end.replace(tzinfo=zone)
    start, end = start.astimezone(zone), end.astimezone(zone)
    now = datetime.now(zone)
    if end <= start or end < now - timedelta(minutes=15):
        return None
    if end > now + timedelta(days=config.FORECAST_DAYS):
        return None
    if start < now:
        start = now.replace(minute=0, second=0, microsecond=0)
        if start < now:
            start += timedelta(hours=1)
    if end <= start:
        return None
    return start, end


def _window_from_question(question: str) -> tuple[datetime, datetime] | None:
    """Resolve common relative day + time-of-day phrases without relying on the LLM."""
    text = question.casefold()
    zone = ZoneInfo(config.APP_TIMEZONE)
    now = datetime.now(zone)
    day = None

    if re.search(r"\bday after tomorrow\b", text):
        day = (now + timedelta(days=2)).date()
    elif re.search(r"\btomorrow\b", text):
        day = (now + timedelta(days=1)).date()
    elif re.search(r"\btoday\b|\btonight\b", text):
        day = now.date()
    else:
        weekday_names = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        for offset, name in enumerate(weekday_names):
            if re.search(rf"\b{name}\b", text):
                days_ahead = (offset - now.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                day = (now + timedelta(days=days_ahead)).date()
                break

    if day is None:
        return None

    periods = {
        "morning": (6, 9),
        "afternoon": (12, 16),
        "evening": (17, 20),
        "tonight": (19, 22),
        "night": (19, 22),
        "noon": (11, 13),
    }
    period = next((key for key in periods if re.search(rf"\b{key}\b", text)), None)
    if period is None:
        return None
    start_hour, end_hour = periods[period]
    start = datetime(day.year, day.month, day.day, start_hour, tzinfo=zone)
    end = datetime(day.year, day.month, day.day, end_hour, tzinfo=zone)
    if start < now:
        start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    if start >= end:
        return None
    if end <= now:
        return None
    return start, end


async def _fetch_candidate_data(place: dict) -> tuple[dict, dict]:
    weather, air = await asyncio.gather(
        fetch_weather(place["lat"], place["lon"]),
        fetch_air_quality(place["lat"], place["lon"]),
        return_exceptions=True,
    )
    if isinstance(weather, Exception):
        raise weather
    if isinstance(air, Exception):
        air = {"hourly": {"time": [], "us_aqi": [], "pm2_5": [], "pm10": []}, "unavailable": True}
    return weather, air


async def make_recommendation(question: str, radius_override: float | None) -> RecommendationResponse:
    intent = await local_model.extract_intent(question, radius_override)
    activity = str(intent.get("activity", "")).casefold().strip()
    location = intent.get("location")
    if activity not in ALLOWED_ACTIVITIES:
        return RecommendationResponse(
            status="clarification",
            answer="Which outdoor activity should I plan for? I support running, cycling, golf, cricket, football, tennis, hiking, picnics, outdoor events, and photography.",
        )
    if not location:
        return RecommendationResponse(
            status="clarification",
            answer="Which city, neighborhood, or starting point should I search near?",
            activity=activity,
        )
    window = _parse_window(intent) or _window_from_question(question)
    if window is None:
        return RecommendationResponse(
            status="clarification",
            answer="What day and time should I compare? Please choose a period within the next five days.",
            activity=activity,
        )

    try:
        origin = await geocode(str(location))
        radius = float(intent.get("radius_km") or radius_override or 10)
        radius = min(config.MAX_RADIUS_KM, max(1, radius))
    except DataSourceError as exc:
        return RecommendationResponse(
            status="error", answer=str(exc), activity=activity,
            sources=["Nominatim"],
        )

    place_search_fallback = False
    try:
        elements = await nearby_osm(origin["lat"], origin["lon"], radius)
    except DataSourceError:
        try:
            elements = await nearby_nominatim(
                origin["lat"], origin["lon"], radius, activity
            )
            place_search_fallback = True
        except DataSourceError as exc:
            return RecommendationResponse(
                status="error",
                answer=str(exc),
                activity=activity,
                sources=["Nominatim", "OpenStreetMap Overpass API"],
            )

    places = get_candidate_places(elements, activity, origin, radius)
    if not places:
        return RecommendationResponse(
            status="error",
            answer=f"I did not find a mapped place suitable for {ACTIVITY_LABELS[activity]} within {radius:g} km of {location}. Try a larger radius or a more specific neighborhood.",
            activity=activity,
            sources=(
                ["© OpenStreetMap contributors", "Nominatim bounded place search"]
                if place_search_fallback
                else ["© OpenStreetMap contributors", "Nominatim", "Overpass API"]
            ),
        )

    limit = asyncio.Semaphore(4)

    async def score_one(place: dict):
        async with limit:
            try:
                weather, air = await _fetch_candidate_data(place)
            except Exception:
                return None
        return rank_place(
            place, activity, elements, weather, air,
            window[0].isoformat(timespec="minutes"),
            window[1].isoformat(timespec="minutes"),
            intent.get("personal_notes") or [],
        )

    scored = await asyncio.gather(*(score_one(place) for place in places))
    results = [item for item in scored if item]
    if not results:
        return RecommendationResponse(
            status="error",
            answer="I found possible places, but could not retrieve matching forecasts for the requested time. Try again or choose a time within the next few days.",
            activity=activity,
            sources=["Open-Meteo Forecast API", "Open-Meteo Air Quality API"],
        )

    results.sort(key=lambda item: item["_sort"], reverse=True)
    top = results[:3]
    routes = await asyncio.gather(
        *(
            route_estimate(
                (origin["lat"], origin["lon"]),
                (item["_place"]["lat"], item["_place"]["lon"]),
            )
            for item in top
        ),
        return_exceptions=True,
    )
    for item, route in zip(top, routes):
        if isinstance(route, dict):
            item["estimated_drive_minutes"] = route["duration_minutes"]

    output = []
    for item in top:
        output.append(
            CandidateRecommendation(
                name=item["name"],
                activity_match=item["activity_match"],
                distance_km=item["distance_km"],
                estimated_drive_minutes=item.get("estimated_drive_minutes"),
                best_time=item["best_time"],
                score=item["score"],
                temperature_c=item["temperature_c"],
                rain_probability_percent=item["rain_probability_percent"],
                wind_kmh=item["wind_kmh"],
                us_aqi=item["us_aqi"],
                context=item["context"],
                reasons=item["reasons"],
            )
        )

    # Keep the final factual recommendation templated from validated data. The
    # model interprets the query; numeric ranking and user-visible facts stay in code.
    best = output[0]
    drive = (
        f" Estimated drive: about {best.estimated_drive_minutes} minutes (not live traffic)."
        if best.estimated_drive_minutes is not None else ""
    )
    weather_bits = []
    if best.temperature_c is not None:
        weather_bits.append(f"feels-like {best.temperature_c:g} °C")
    if best.rain_probability_percent is not None:
        weather_bits.append(f"rain chance {best.rain_probability_percent:g}%")
    if best.wind_kmh is not None:
        weather_bits.append(f"wind {best.wind_kmh:g} km/h")
    if best.us_aqi is not None:
        weather_bits.append(f"forecast US AQI {best.us_aqi:g}")
    conditions = "; ".join(weather_bits) if weather_bits else "forecast details are incomplete"
    answer = (
        f"For {ACTIVITY_LABELS[activity]}, the highest-scoring mapped option is {best.name} "
        f"at {best.best_time}, about {best.distance_km:g} km from {location}. "
        f"Conditions: {conditions}.{drive} This is a heuristic ranking, not a safety guarantee."
    )
    if best.us_aqi is not None and best.us_aqi >= 151:
        if best.us_aqi <= 200:
            aqi_category = "Unhealthy"
        elif best.us_aqi <= 300:
            aqi_category = "Very Unhealthy"
        else:
            aqi_category = "Hazardous"
        answer = (
            f"Caution for {ACTIVITY_LABELS[activity]} near {location}: the forecast US AQI is "
            f"{best.us_aqi:g} ({aqi_category}) at {best.best_time}. The top mapped match is "
            f"{best.name}, about {best.distance_km:g} km away, but its score is not a safety "
            "clearance. Check local official air-quality guidance before planning outdoor activity."
        )
    limitations = [
        "The suitability score is a transparent project heuristic, not an official activity-safety or medical assessment.",
        "OSRM travel duration is a route estimate and does not include live traffic.",
        "Mapped roads, parks, water, and industry can be incomplete or outdated; nearby industrial features are not pollution measurements.",
        "Air-quality forecasts are regional grid estimates, not measurements at the exact venue.",
    ]
    if place_search_fallback:
        limitations.append(
            "Overpass was unavailable, so Nominatim supplied only its best matching named places; the venue list may be incomplete."
        )
    if any((item["us_aqi"] is None) for item in top):
        limitations.append("Air-quality forecast data was unavailable for one or more options.")
    return RecommendationResponse(
        status="ok",
        answer=answer,
        activity=activity,
        candidates=output,
        sources=[
            "© OpenStreetMap contributors",
            "Nominatim (location search)",
            *(
                ["Nominatim (bounded place search fallback)"]
                if place_search_fallback
                else ["OpenStreetMap Overpass API"]
            ),
            "Open-Meteo Forecast API",
            "Open-Meteo Air Quality API",
            *(["US EPA AQI categories"] if best.us_aqi is not None and best.us_aqi >= 151 else []),
            "OSRM (estimated route duration)",
        ],
        data_updated_at=datetime.now(ZoneInfo(config.APP_TIMEZONE)).isoformat(timespec="seconds"),
        limitations=limitations,
    )

