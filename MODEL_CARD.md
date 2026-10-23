---
license: apache-2.0
base_model: Qwen/Qwen3-1.7B
pipeline_tag: text-generation
tags:
  - geoai
  - outdoor-recommendation
  - small-language-model
  - qwen3
---

# GeoAI Outdoor Assistant model setup

This project uses the public, instruction-capable Qwen3-1.7B model without additional training. Inference runs in the project deployment using the Qwen3-1.7B-GGUF Q8_0 artifact and `llama.cpp`; it does not call a hosted large-language-model endpoint.

The model extracts the activity, location, time window, search radius, and explicitly stated personal context from the user's question. Application code retrieves live map, weather, air-quality, and route data, ranks options with a documented heuristic, and formats the response from those returned facts.

## Intended use

Prototype recommendations for outdoor recreation using live public data. The score is not an official safety or medical assessment. Weather, air-quality, and map data may be incomplete or uncertain.

## Data sources

- OpenStreetMap contributors, through Nominatim and Overpass API.
- Open-Meteo Forecast API and Air Quality API.
- OSRM route-duration estimate.

## Base model and license

- Base model: [Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B)
- Base license: Apache-2.0 as listed on the Hugging Face model page.
- No fine-tuning or adapter is included in this project.

