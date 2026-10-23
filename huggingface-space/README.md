---
title: GeoAI Outdoor Assistant
emoji: 🌍
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8000
short_description: Local Qwen model with live outdoor place and forecast data.
models:
  - Qwen/Qwen3-1.7B-GGUF
---

# GeoAI Outdoor Assistant

Ask for an outdoor activity, place, and time. The app uses Qwen3-1.7B to parse the request, searches mapped places, fetches weather and air-quality forecasts, and ranks options with a transparent project heuristic.

## Model

This Space runs the upstream `Qwen/Qwen3-1.7B-GGUF` Q8_0 weights unchanged through `llama.cpp`. It downloads the approximately 1.83 GB model on first startup; this project does not contain a fine-tune or adapter.

## Live data

- OpenStreetMap data through Nominatim and Overpass.
- Hourly weather and air-quality forecasts from Open-Meteo.
- Optional OSRM route-duration estimates; these are not live traffic.

If Overpass is unavailable, the app uses one bounded Nominatim search. That fallback returns best matches, not a complete venue list. Map data is © OpenStreetMap contributors. The app follows the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/).

Forecasts can be incomplete or differ from local measurements. The ranking is a prototype heuristic, not medical advice or a safety guarantee. Check current local advisories before planning outdoor activities.

## API

The Space page provides a web form. The API is available at `/docs`; send `POST /recommend` with JSON such as:

```json
{
  "question": "Find a place for jogging within 5 km of Powai, Mumbai tomorrow morning.",
  "radius_km": 5
}
```

## Credits and licensing

The app source is MIT-licensed. The unchanged Qwen base model and GGUF artifact retain their upstream licensing and attribution. The Space downloads those public model files at startup rather than republishing them.
