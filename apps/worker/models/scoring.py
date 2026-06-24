from pydantic import BaseModel, Field
from typing import Literal


class DimensionScores(BaseModel):
    buying_intent: int = Field(default=0, ge=0, le=25)
    decision_maker: int = Field(default=0, ge=0, le=20)
    recency: int = Field(default=0, ge=0, le=15)
    service_fit: int = Field(default=0, ge=0, le=15)
    company_legitimacy: int = Field(default=0, ge=0, le=10)
    urgency: int = Field(default=0, ge=0, le=8)
    engagement: int = Field(default=0, ge=0, le=4)
    reply_likelihood: int = Field(default=0, ge=0, le=3)


class LeadScore(BaseModel):
    score: int = Field(ge=0, le=100)
    bucket: Literal["hot", "warm", "cold", "ignore"]
    dimension_scores: DimensionScores
    top_signals: list[str] = []
    explanation: str
    recommended_action: str
