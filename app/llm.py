
import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app import config


class ModelUnavailable(RuntimeError):
    """Raised when the configured language model cannot respond."""
    pass


class LocalModel:
    def __init__(self) -> None:
        self.base_url = config.LLM_BASE_URL.rstrip("/")
        self.model_name = config.LLM_MODEL

    async def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 500,
    ) -> str:
        """Send a chat completion request to the configured LLM."""

        if not self.model_name:
            raise ModelUnavailable("LLM_MODEL is not configured.")

        if not config.HF_TOKEN:
            raise ModelUnavailable("HF_TOKEN is not configured.")

        body = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "stream": False,
        }

        headers = {
            "Authorization": f"Bearer {config.HF_TOKEN}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=config.LLM_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=body,
                    headers=headers,
                )

                response.raise_for_status()
                payload = response.json()

            content = payload["choices"][0]["message"]["content"]

            if not isinstance(content, str) or not content.strip():
                raise ModelUnavailable(
                    "The AI model returned an empty response."
                )

            return content.strip()

        except httpx.HTTPStatusError as exc:
            # Do not expose the token or authorization headers.
            status = exc.response.status_code

            if status == 401 or status == 403:
                message = (
                    "Hugging Face authentication or provider permission "
                    "failed. Check HF_TOKEN and its Inference Providers access."
                )
            elif status == 429:
                message = (
                    "Hugging Face rate limit or provider quota reached. "
                    "Check your account usage and try again later."
                )
            elif status == 400:
                message = (
                    "Hugging Face rejected the request. Check LLM_MODEL "
                    "and the request format."
                )
            elif status >= 500:
                message = (
                    "The Hugging Face service or selected inference provider "
                    "is temporarily unavailable."
                )
            else:
                message = f"Hugging Face returned HTTP {status}."

            raise ModelUnavailable(message) from exc

        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelUnavailable(
                f"AI request failed: {type(exc).__name__}."
            ) from exc

    async def is_ready(self) -> bool:
        """Check whether the model configuration is present."""

        if "router.huggingface.co" in self.base_url:
            return bool(
                config.HF_TOKEN
                and self.model_name
                and config.LLM_TIMEOUT_SECONDS > 0
            )

        health_url = self.base_url.removesuffix("/v1") + "/health"

        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(health_url)
            return response.is_success
        except httpx.HTTPError:
            return False

    async def extract_intent(
        self,
        question: str,
        radius_override: float | None,
    ) -> dict:
        """Extract activity, location, time, and radius from a request."""

        now = datetime.now(
            ZoneInfo(config.APP_TIMEZONE)
        ).isoformat(timespec="minutes")

        radius_rule = (
            f"Use {radius_override:g} km as the search radius."
            if radius_override is not None
            else "If the user gives no radius, use 10 km."
        )

        system = (
            "Extract fields from an outdoor-activity request. "
            "Return exactly one JSON object without Markdown. "
            "Do not invent a location or time. "
            "Allowed activity values: running, cycling, golf, cricket, "
            "football, tennis, hiking, picnic, outdoor_event, photography. "
            "Use null for missing location or time. "
            f"The current local time is {now} in timezone "
            f"{config.APP_TIMEZONE}. Convert relative dates using this time. "
            "Return times in local ISO format YYYY-MM-DDTHH:MM, using "
            "start_local and end_local. For vague periods such as tomorrow "
            "morning or this weekend, choose a sensible local interval. "
            "If no time period is stated, use null for both times. "
            "Keep personal_notes short and include only details the user "
            f"stated. {radius_rule} "
            'Schema: {"activity": string, "location": string|null, '
            '"radius_km": number, "start_local": string|null, '
            '"end_local": string|null, "personal_notes": [string]}'
        )

        raw = await self.chat(
            system,
            f"Current local time: {now}\nUser request: {question}",
            max_tokens=350,
        )

        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            raise ModelUnavailable(
                "The model returned an invalid intent response."
            )

        try:
            intent = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ModelUnavailable(
                "The model returned malformed JSON for the request."
            ) from exc

        if not isinstance(intent, dict):
            raise ModelUnavailable(
                "The model returned an invalid intent response."
            )

        allowed = {
            "running",
            "cycling",
            "golf",
            "cricket",
            "football",
            "tennis",
            "hiking",
            "picnic",
            "outdoor_event",
            "photography",
        }

        activity = intent.get("activity")
        intent["activity"] = (
            activity.casefold().strip()
            if isinstance(activity, str)
            else ""
        )

        if intent["activity"] not in allowed:
            intent["activity"] = ""

        location = intent.get("location")
        intent["location"] = (
            location.strip()[:200]
            if isinstance(location, str) and location.strip()
            else None
        )

        for field in ("start_local", "end_local"):
            value = intent.get(field)
            intent[field] = (
                value.strip()[:40]
                if isinstance(value, str) and value.strip()
                else None
            )

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
            note.strip()[:80]
            for note in notes
            if isinstance(note, str) and note.strip()
        ][:8]

        if radius_override is not None:
            intent["radius_km"] = radius_override

        return intent

    async def explain(self, facts: dict) -> str:
        """Explain recommendations using only the supplied facts."""

        system = (
            "Explain outdoor recommendations in plain language. "
            "Use only the supplied facts. Do not add weather, venue, safety, "
            "traffic, or medical claims that are absent from the facts. "
            "Make clear that the ranking is guidance, not a guarantee of "
            "safety. Keep the answer concise."
        )

        user = (
            "Write a short recommendation from these verified facts:\n"
            + json.dumps(facts, ensure_ascii=False)
        )

        return (
            await self.chat(system, user, max_tokens=260)
        ).strip()


local_model = LocalModel()
