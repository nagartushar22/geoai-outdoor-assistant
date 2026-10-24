
import json
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app import config


class ModelUnavailable(RuntimeError):
    """Raised when the language model cannot respond."""
    pass


class LocalModel:
    def __init__(self) -> None:
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model_name = os.getenv(
            "LLM_MODEL", "gemini-2.5-flash"
        ).strip()
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    async def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = 500,
    ) -> str:
        """Send a text-generation request to Google Gemini."""

        if not self.api_key:
            raise ModelUnavailable(
                "GEMINI_API_KEY is missing from the environment."
            )

        if not self.model_name:
            raise ModelUnavailable("LLM_MODEL is not configured.")

        url = (
            f"{self.base_url}/{self.model_name}:generateContent"
        )

        body = {
            "systemInstruction": {
                "parts": [{"text": system}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": max_tokens,
            },
        }

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(
                timeout=config.LLM_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    url,
                    json=body,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()

            candidates = payload.get("candidates", [])
            if not candidates:
                feedback = payload.get("promptFeedback", {})
                reason = feedback.get("blockReason")
                if reason:
                    raise ModelUnavailable(
                        f"Gemini blocked the request: {reason}."
                    )
                raise ModelUnavailable(
                    "Gemini returned no response candidates."
                )

            parts = (
                candidates[0]
                .get("content", {})
                .get("parts", [])
            )
            answer = "".join(
                part.get("text", "")
                for part in parts
                if isinstance(part, dict)
            ).strip()

            if not answer:
                raise ModelUnavailable(
                    "Gemini returned an empty response."
                )

            return answer

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code

            # Never include the request headers or API key in errors.
            if status == 400:
                message = (
                    "Gemini rejected the request. Check the model name "
                    "and request format."
                )
            elif status == 401 or status == 403:
                message = (
                    "Gemini authentication or project access failed. "
                    "Check GEMINI_API_KEY and Google AI Studio eligibility."
                )
            elif status == 404:
                message = (
                    "The Gemini model was not found. Check LLM_MODEL "
                    "against the currently available models."
                )
            elif status == 429:
                message = (
                    "Gemini rate limit or quota reached. Check your "
                    "Google AI Studio usage and quota."
                )
            elif status >= 500:
                message = (
                    "The Gemini service is temporarily unavailable."
                )
            else:
                message = f"Gemini returned HTTP {status}."

            raise ModelUnavailable(message) from exc

        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ModelUnavailable(
                f"Gemini request failed: {type(exc).__name__}."
            ) from exc

    async def is_ready(self) -> bool:
        """Check local configuration without making a paid request."""
        return bool(
            self.api_key
            and self.model_name
            and config.LLM_TIMEOUT_SECONDS > 0
        )

    async def extract_intent(
        self,
        question: str,
        radius_override: float | None,
    ) -> dict:
        """Extract activity, location, time, and radius."""

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
            "running", "cycling", "golf", "cricket", "football",
            "tennis", "hiking", "picnic", "outdoor_event",
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
        """Explain recommendations using only supplied facts."""

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
