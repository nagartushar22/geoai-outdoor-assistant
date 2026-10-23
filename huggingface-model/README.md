---
license: apache-2.0
base_model: Qwen/Qwen3-1.7B
pipeline_tag: text-generation
tags:
  - geoai
  - outdoor-recommendation
  - qwen3
  - gguf
  - llama-cpp
---

# GeoAI Outdoor Assistant — Qwen3-1.7B Q8_0

This repository packages the **Qwen3-1.7B Q8_0 GGUF checkpoint** used by the GeoAI Outdoor Assistant demo. It is a public mirror of the upstream quantized artifact; the weights are not newly trained or fine-tuned. No adapter is included.

- Upstream quantized model: [Qwen/Qwen3-1.7B-GGUF](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF)
- Upstream base model: [Qwen/Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B)
- Artifact: `Qwen3-1.7B-Q8_0.gguf` (Q8_0 quantization)
- License: Apache-2.0; see the included `LICENSE` and upstream repository.
- Training/fine-tuning: none performed by this project.

## What the model does in the demo

The model interprets a user's outdoor activity request and extracts fields such as activity, location, time window, and search radius. The surrounding application then retrieves current information from public services, ranks candidate places, and formats the answer. **Live map, weather, air-quality, and route data come from application API calls; they are not embedded in this model or its weights.**

The application uses OpenStreetMap through Nominatim and Overpass, Open-Meteo Forecast and Air Quality APIs, and OSRM for route estimates. Their availability and returned coverage can vary.

## Run locally with llama.cpp

Install a recent build of [llama.cpp](https://github.com/ggml-org/llama.cpp), download `Qwen3-1.7B-Q8_0.gguf` from this repository, then start the OpenAI-compatible server:

```bash
llama-server -m Qwen3-1.7B-Q8_0.gguf --host 127.0.0.1 --port 8080
```

Send a chat request to `http://127.0.0.1:8080/v1/chat/completions` with a JSON body such as:

```json
{
  "model": "Qwen3-1.7B-Q8_0.gguf",
  "messages": [
    {"role": "user", "content": "Find an easy 5 km hiking route near Boulder tomorrow morning."}
  ],
  "temperature": 0.2
}
```

This starts the language model only. To reproduce live GeoAI recommendations, run the separate application from the project source repository and configure its model endpoint and data-service access as described in that project's README.

## Limitations

This checkpoint is a general-purpose language model, not a geospatial database or a safety authority. It may misinterpret requests or generate incorrect text. Verify locations, routes, forecasts, air-quality readings, and any safety-critical information with their original sources.
