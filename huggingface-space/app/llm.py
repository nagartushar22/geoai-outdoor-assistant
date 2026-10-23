import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app import config


class ModelUnavailable(RuntimeError):
    pass


class LocalModel:
    def __init__(self) -> None:
        self.base_url = config.LLM_BASE_URL
        self.model_name = config.LLM_MODEL

    async def chat(self, system: str, user: str, max_tokens: int = 500) -> str:
        body = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user.rstrip() + "\n/no_think"},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
        }
        try:
            async with httpx.AsyncClient(timeout=config.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions", json=body
                )
                response.raise_for_status()
                payload = response.json()
                return payload["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelUnavailable(
                "The local Qwen model is not responding. Start the model service and try again."
            ) from exc

    async def is_ready(self) -> bool:
        health_url = self.base_url.removesuffix("/v1") + "/health"
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(health_url)
            return response.is_success
        except httpx.HTTPError:
            return False

    async def extract_intent(self, question: str, radius_override: float | None) -> dict:
        now = datetime.now(ZoneInfo(config.APP_TIMEZONE)).isoformat(timespec="minutes")
        radius_rule = (
            f"Use {radius_override:g} km as the search radius."
            if radius_override is not None
            else "If the user gives no radius, use 10 km."
        )
        system = (
            "Extract fields from an outdoor-activity request. Return exactly one JSON object, "
            "no markdown. Do not invent a location or a time. Allowed activity values: "
            "running, cycling, golf, cricket, football, tennis, hiking, picnic, outdoor_event, photography. "
            "Use null for missing location or time. Convert relative dates using the supplied current "
            f"local time ({config.APP_TIMEZONE}). Return times in ISO local format YYYY-MM-DDTHH:MM, "
            "with start_local and end_local. For vague periods such as tomorrow morning or this weekend, "
            "choose a sensible local interval. If no time period is stated, return null for both times. "
            "Keep personal_notes short and only include details the user stated. "
            f"{radius_rule} Schema: {{\"activity\": string, \"location\": string|null, "
            "\"radius_km\": number, \"start_local\": string|null, \"end_local\": string|null, "
            "\"personal_notes\": [string]}"
        )
        raw = await self.chat(
            system,
            f"Current local time: {now}\nUser request: {question}",
            max_tokens=350,
        )
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ModelUnavailable("The model returned an invalid intent response.")
        try:
            intent = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ModelUnavailable("The model returned malformed JSON for the request.") from exc
        if not isinstance(intent, dict):
            raise ModelUnavailable("The model returned an invalid intent response.")

        allowed = {
            "running", "cycling", "golf", "cricket", "football", "tennis",
            "hiking", "picnic", "outdoor_event", "photography",
        }
        activity = intent.get("activity")
        intent["activity"] = activity.casefold().strip() if isinstance(activity, str) else ""
        if intent["activity"] not in allowed:
            intent["activity"] = ""

        location = intent.get("location")
        intent["location"] = location.strip()[:200] if isinstance(location, str) and location.strip() else None
        for field in ("start_local", "end_local"):
            value = intent.get(field)
            intent[field] = value.strip()[:40] if isinstance(value, str) and value.strip() else None

        try:
            model_radius = float(intent.get("radius_km", 10))
        except (TypeError, ValueError):
            model_radius = 10.0
        if not 0 < model_radius <= 40:
            model_radius = 10.0
        intent["radius_km"] = model_radius

        notes = intent.get("personal_notes", [])
        if not isinstance(notes, list):
            notes = []
        intent["personal_notes"] = [
            note.strip()[:80] for note in notes if isinstance(note, str) and note.strip()
        ][:8]
        if radius_override is not None:
            intent["radius_km"] = radius_override
        return intent

    async def explain(self, facts: dict) -> str:
        system = (
            "You explain outdoor recommendations in plain language. Use only the supplied facts. "
            "Do not add weather, venue, safety, traffic, or medical claims that are absent from the facts. "
            "Make clear that the ranking is guidance, not a guarantee of safety. Keep the answer concise."
        )
        user = "Write a short recommendation from these verified facts:\n" + json.dumps(
            facts, ensure_ascii=False
        )
        return (await self.chat(system, user, max_tokens=260)).strip()


local_model = LocalModel()

