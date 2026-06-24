from pydantic import BaseModel
from typing import Literal


class CommentVariant(BaseModel):
    type: Literal["concise", "insightful", "founder_friendly"]
    text: str
    tone: str


class CommentDraftOutput(BaseModel):
    variants: list[CommentVariant]
    context_used: str = ""


class SafetyResult(BaseModel):
    safe: bool
    violations: list[str] = []
    severity: Literal["none", "low", "high"] = "none"
    reasoning: str = ""
