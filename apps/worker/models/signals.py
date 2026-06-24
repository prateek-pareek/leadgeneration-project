"""Structured output for AI signal classification."""

from pydantic import BaseModel, Field
from typing import Literal


class SignalAnalysis(BaseModel):
    help_seeker_type: Literal["agency", "freelancer", "either", "employee", "unknown", "none"]
    intent_strength: float = Field(ge=0.0, le=1.0)
    intent_type: Literal["explicit", "implicit", "indirect", "none"]
    signals: list[str] = Field(default_factory=list)
    engagement_play: Literal["social_comment", "dm", "cold_email", "outreach", "skip"]
    reasoning: str = ""
    service_categories: list[str] = Field(default_factory=list)
