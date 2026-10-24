
import os
from dotenv import load_dotenv

load_dotenv()


def env(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


# Hosted Hugging Face Inference API
LLM_BASE_URL = env(
    "LLM_BASE_URL",
    "https://router.huggingface.co/v1",
).rstrip("/")

LLM_MODEL = env(
    "LLM_MODEL",
    "openai/gpt-oss-20b:fastest",
)

LLM_TIMEOUT_SECONDS = float(env("LLM_TIMEOUT_SECONDS", "90"))
HF_TOKEN = env("HF_TOKEN", "")

# OpenStreetMap data sources
OSM_USER_AGENT = env(
    "OSM_USER_AGENT",
    "GeoAIOutdoorAssistant/0.1 (contact: you@example.com)",
)

NOMINATIM_URL = env(
    "NOMINATIM_URL",
    "https://nominatim.openstreetmap.org/search",
)

OVERPASS_URL = env(
    "OVERPASS_URL",
    "https://overpass-api.de/api/interpreter",
)

OVERPASS_FALLBACK_URLS = tuple(
    url.strip().rstrip("/")
    for url in env(
        "OVERPASS_FALLBACK_URLS",
        "https://overpass.private.coffee/api/interpreter",
    ).split(",")
    if url.strip()
)

OVERPASS_URLS = (OVERPASS_URL.rstrip("/"), *OVERPASS_FALLBACK_URLS)
OVERPASS_TIMEOUT_SECONDS = float(
    env("OVERPASS_TIMEOUT_SECONDS", "8")
)

OSRM_URL = env(
    "OSRM_URL",
    "https://router.project-osrm.org",
).rstrip("/")

# Optional protection for the public recommendation endpoint
API_KEY = env("API_KEY", "")

# India local time
APP_TIMEZONE = env("APP_TIMEZONE", "Asia/Kolkata")

MAX_RADIUS_KM = 40
FORECAST_DAYS = 5
