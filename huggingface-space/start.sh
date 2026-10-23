#!/usr/bin/env bash
set -Eeuo pipefail

/app/llama-server \
  -hf Qwen/Qwen3-1.7B-GGUF:Q8_0 \
  --host 127.0.0.1 \
  --port 8080 \
  --ctx-size "${LLM_CONTEXT_SIZE:-4096}" \
  --threads "${LLM_THREADS:-2}" \
  --alias Qwen3-1.7B &
model_pid=$!

/opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &
app_pid=$!

shutdown() {
  kill "$app_pid" "$model_pid" 2>/dev/null || true
  wait "$app_pid" 2>/dev/null || true
  wait "$model_pid" 2>/dev/null || true
}
trap shutdown EXIT INT TERM

wait -n "$model_pid" "$app_pid"
