FROM ghcr.io/ggml-org/llama.cpp:server

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY requirements.txt ./requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY start.sh ./start.sh
RUN chmod +x /workspace/start.sh

ENV PATH="/opt/venv/bin:${PATH}" \
    LLM_BASE_URL="http://127.0.0.1:8080/v1" \
    LLM_MODEL="Qwen3-1.7B" \
    OSM_USER_AGENT="GeoAIOutdoorAssistant/0.1 (Hugging Face Space)" \
    APP_TIMEZONE="Asia/Kolkata"

EXPOSE 8000
ENTRYPOINT ["/bin/bash", "/workspace/start.sh"]
