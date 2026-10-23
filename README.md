# GeoAI Outdoor Assistant

A working hackathon starter for recommending **where and when** to do an outdoor activity. It runs Qwen3-1.7B locally through `llama.cpp`, fetches public map/weather/air-quality data at request time, ranks place-and-hour options in application code, and exposes an HTTP API plus a small web page.

## Current judging/demo API

The app is reachable through a temporary HTTPS tunnel while the Windows host is online:

- **API base URL:** `https://citations-too-department-raising.trycloudflare.com`
- **Health:** `GET https://citations-too-department-raising.trycloudflare.com/health`
- **Interactive API docs:** `https://citations-too-department-raising.trycloudflare.com/docs`
- **Recommendation:** `POST https://citations-too-department-raising.trycloudflare.com/recommend`

Example request body:

```json
{
  "question": "Good place and time for golf on Saturday within 40 km of Andheri?",
  "radius_km": 40
}
```

This is a temporary Cloudflare Quick Tunnel for a live demonstration, not an always-on hosted service. It has no uptime guarantee. Keep this PC awake and connected to the internet, and keep the local model server, FastAPI app, and tunnel process running. The URL changes if the tunnel is restarted. Do not use this as a guaranteed endpoint for a later judging window; move the same app to an always-on host for that.

## What it supports

Running, cycling, golf, cricket, outdoor football, outdoor tennis, hiking/nature walks, picnics, outdoor events, and photography. The model extracts the activity, location, time range, optional radius, and personal context. Missing location or time prompts a clarification instead of silently inventing one.

## Run locally with Docker

Requirements: Docker Desktop or Docker Engine with Compose, and an internet connection for the first model download and public data requests. The Q8_0 model file is about 1.83 GB; the server also needs memory for the runtime and app.

1. Install and start Docker Desktop.
2. In PowerShell, from this directory, copy and edit the environment file:

   ```bash
   Copy-Item .env.example .env
   ```

   Set `OSM_USER_AGENT` to identify the app and give a monitored contact address.

3. Start the app and model:

   ```bash
   docker compose up --build
   ```

   The model container downloads Qwen3-1.7B-GGUF Q8_0 on first start. The Compose volume keeps its model cache.

4. Open `http://localhost:8000` for the demo page or `http://localhost:8000/docs` for the API.

## Run locally on Windows without Docker

The app can use a separately running `llama.cpp` server. Install the official Windows runtime with WinGet, then open two PowerShell windows in this directory:

```powershell
winget install llama.cpp
```

In the first window, start the model server. It downloads the 1.83 GB Q8_0 model the first time:

```powershell
llama serve -hf Qwen/Qwen3-1.7B-GGUF:Q8_0 --host 127.0.0.1 --port 8080
```

In the second window, create the app environment and start FastAPI:

```powershell
Copy-Item .env.example .env
# Edit .env and set OSM_USER_AGENT to your app name and a monitored contact.
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The `.env` file defaults to the local model at `127.0.0.1:8080`. Open `http://localhost:8000`. For the API, use `http://localhost:8000/docs`.

The model service listens only inside the Compose network. The app's public endpoint is `POST /recommend` with JSON such as:

```json
{
  "question": "Where can I go running tomorrow evening near Powai?",
  "radius_km": 8
}
```

The `radius_km` field is optional and may be between 1 and 40. A request without a radius uses 10 km. Configure `API_KEY` in `.env` to require the `X-API-Key` request header.

## Public deployment

For a CPU-only starting point, use an always-on Linux VM with 4 vCPU, 8 GB RAM, and at least 10 GB free disk. This is a practical estimate for the 1.83 GB Q8_0 weights, runtime memory, and app; validate speed and memory on the chosen host. GPU inference is optional. Both app and model services run together with Docker Compose.

1. Install Docker Engine and the Docker Compose plugin on the VM.
2. Copy this folder to the VM without `.env`, `.venv`, model-cache, or Python cache files.
3. Create `.env` from `.env.example`. Set `OSM_USER_AGENT` to the app name and a monitored contact address. Set a strong `API_KEY` if the judging client can send it.
4. Start the services with `docker compose up -d --build`. The first model download can take a while; watch it with `docker compose logs -f model`. The Compose volume preserves the weights across restarts.
5. Put the app on an HTTPS domain using the VM provider's ingress or a reverse proxy. Allow public HTTPS to the app, but keep model port 8080 internal to Docker. The compose file publishes only the app port 8000.
6. Check `https://YOUR_HOST/health`, then send a `POST /recommend` request. Include `X-API-Key` if `API_KEY` is set. Make sure the endpoint stays online through judging.

Do not put credentials in this repository. If the judges need an unauthenticated endpoint, leave `API_KEY` blank and add request limits at the HTTPS proxy instead.

The app currently assumes Indian local time (`Asia/Kolkata`); change `APP_TIMEZONE` if the deployment is intended for a different region. Relative dates outside the five-day forecast window are rejected with a clarification.

## How the recommendation is made

1. Qwen3 extracts structured request fields. If the question is incomplete, the API asks for the missing field.
2. Nominatim turns the named area into coordinates.
3. Overpass finds mapped outdoor places and nearby mapped roads, green areas, water, and industrial features. If Overpass is unavailable, the app makes one bounded, user-triggered Nominatim search for the requested place type; this returns best matches and may be incomplete.
4. Open-Meteo returns hourly weather and air-quality forecasts for candidate coordinates.
5. A transparent heuristic ranks candidate places and hours. Stronger activity-specific matches, weather comfort, rain, wind, forecast AQI, and mapped context affect the score.
6. OSRM can add a road-network route-duration estimate. It is **not live traffic**.
7. The API returns a factual response, candidate details, source names, data timestamp, and limitations.

## Data sources and attribution

- **Nominatim**: geocoding and a bounded venue-search fallback when Overpass is unavailable. The fallback returns best matches, not a complete place inventory. The app caches lookups and rate-limits requests to at most one per second. Identify the app with `OSM_USER_AGENT`, respect the [Nominatim usage policy](https://operations.osmfoundation.org/policies/nominatim/), and switch providers if asked.
- **OpenStreetMap Overpass API**: candidate venues and mapped features. The app tries the configured primary endpoint and then its configured fallback, with a short configurable timeout before using the Nominatim fallback. Display **© OpenStreetMap contributors**.
- **Open-Meteo Forecast API**: hourly forecast variables (temperature, precipitation probability, wind, UV, daylight).
- **Open-Meteo Air Quality API**: hourly US AQI and particulate forecasts. Forecast values are regional grid estimates, not on-site measurements.
- **OSRM**: route-network estimate when available. No live traffic provider is wired in.

Each source can be unavailable or have incomplete coverage. The API does not fabricate missing venues or weather. Scores and thresholds are prototype heuristics, not official health guidance or a guarantee that conditions are safe. A mapped industrial feature plus wind direction is only a possible context signal, not a pollution measurement. Treat health profiles conservatively and consult local guidance.

## Model repository for the hackathon

Qwen3-1.7B is selected because it is an instruction model below the 3B limit, supports multilingual requests, and is licensed Apache-2.0. The deployment uses the publisher's Q8_0 GGUF file (1.83 GB) through `llama.cpp`. The small model interprets the request; application code retrieves live evidence and scores options. This project does not fine-tune the model because the rulebook supplies no training dataset. The app code is MIT-licensed; the upstream model remains under its stated Apache-2.0 terms. The public Hugging Face model repository is [Tusharnagar22/geoai-outdoor-assistant-qwen3-1.7b-gguf](https://huggingface.co/Tusharnagar22/geoai-outdoor-assistant-qwen3-1.7b-gguf). It contains the Q8_0 model file, model card, and license.

## Main files

- `app/main.py` - HTTP API and demo page.
- `app/llm.py` - local model client and intent extraction.
- `app/data_sources.py` - Nominatim, Overpass, Open-Meteo, and OSRM calls with lightweight caching.
- `app/scoring.py` - place/activity matching and transparent suitability heuristic.
- `app/recommendation.py` - end-to-end orchestration and response creation.
- `compose.yaml` - local/deployment services for app and model.
- `MODEL_CARD.md` - model repository card draft.

## Hackathon handoff checklist

- The public Hugging Face model repository is published at the link above. The model is the upstream Qwen3-1.7B Q8_0 GGUF as-is; there is no fine-tune or adapter.
- The public source repository is [nagartushar22/geoai-outdoor-assistant](https://github.com/nagartushar22/geoai-outdoor-assistant). Excluded `.env`, `.venv`, model weights, logs, and caches from the published files.
- The API URL above is live for a temporary demo while this PC and the tunnel stay up. Use an always-on host to guarantee availability through a later judging window.
- The five-slide presentation explains the problem, architecture, live worked example, base model, no fine-tuning, and limitations. Disclose Codex as a coding assistant used during development.

