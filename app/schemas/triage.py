from pydantic import BaseModel
from typing import Optional, Literal


class TriageRequest(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None


class TriageResponse(BaseModel):
    session_id: str
    severity_medical: Literal["M0", "M1", "M2", "M3"]
    severity_psychological: Literal["P0", "P1", "P2", "P3"]
    recommended_action: str
    message: str