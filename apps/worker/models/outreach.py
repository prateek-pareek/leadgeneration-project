from pydantic import BaseModel
from typing import Optional


class OutreachDraftOutput(BaseModel):
    subject: Optional[str] = None
    body: str
    personalization_notes: str = ""
