import os
from dotenv import load_dotenv


load_dotenv()


def env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


LLM_BASE_URL = env("LLM_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/")
LLM_MODEL = env("LLM_MODEL", "Qwen/Qwen3-1.7B-GGUF:Q8_0")
LLM_TIMEOUT_SECONDS = float(env("LLM_TIMEOUT_SECONDS", "90"))
OSM_USER_AGENT = env(
    "OSM_USER_AGENT", "GeoAIOutdoorAssistant/0.1 (contact: configure OSM contact)"
)
NOMINATIM_URL = env(
    "NOMINATIM_URL", "https://nominatim.openstreetmap.org/search"
)
OVERPASS_URL = env("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
OVERPASS_FALLBACK_URLS = tuple(
    url.strip().rstrip("/")
    for url in env(
        "OVERPASS_FALLBACK_URLS",
        "https://overpass.private.coffee/api/interpreter",
    ).split(",")
    if url.strip()
)
OVERPASS_URLS = (OVERPASS_URL.rstrip("/"), *OVERPASS_FALLBACK_URLS)
OVERPASS_TIMEOUT_SECONDS = float(env("OVERPASS_TIMEOUT_SECONDS", "8"))
OSRM_URL = env("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
API_KEY = env("API_KEY", "")
APP_TIMEZONE = env("APP_TIMEZONE", "Asia/Kolkata")
MAX_RADIUS_KM = 40
FORECAST_DAYS = 5

