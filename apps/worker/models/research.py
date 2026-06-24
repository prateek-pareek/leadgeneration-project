from pydantic import BaseModel, Field
from typing import Optional


class ResearchBrief(BaseModel):
    company_name: Optional[str] = None
    company_description: str = ""
    company_stage: str = "unknown"
    company_size: str = "unknown"
    founder_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    is_decision_maker: Optional[bool] = None
    pain_points: list[str] = []
    budget_signal: str = "unknown"
    tech_maturity: str = "unknown"
    service_fit: list[str] = []
    engagement_angle: str = ""
    brief_text: str = ""
    confidence_overall: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertain_fields: list[str] = []
    sources_used: list[str] = []
