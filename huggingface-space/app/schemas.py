from typing import Literal

from pydantic import BaseModel, Field


Activity = Literal[
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
]


class RecommendationRequest(BaseModel):
    question: str = Field(min_length=5, max_length=1200)
    radius_km: float | None = Field(default=None, gt=0, le=40)


class CandidateRecommendation(BaseModel):
    name: str
    activity_match: str
    distance_km: float
    estimated_drive_minutes: int | None = None
    best_time: str
    score: int
    temperature_c: float | None = None
    rain_probability_percent: float | None = None
    wind_kmh: float | None = None
    us_aqi: float | None = None
    context: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class RecommendationResponse(BaseModel):
    status: Literal["ok", "clarification", "error"]
    answer: str
    activity: str | None = None
    candidates: list[CandidateRecommendation] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    data_updated_at: str | None = None
    limitations: list[str] = Field(default_factory=list)

