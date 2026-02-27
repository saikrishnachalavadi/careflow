from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    message: str
    action: Optional[str] = None  # emergency_services | doctors | pharmacy | labs | crisis_helplines | psychological
    doctor_specialty: Optional[str] = None  # e.g. pediatrician, general_physician (when action is doctors)
    session_id: str
