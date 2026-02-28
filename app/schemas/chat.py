from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    user_id: str
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    message: str
    action: Optional[str] = None  # emergency_services | doctors | pharmacy | labs | crisis_helplines | psychological
    doctor_specialty: Optional[str] = None  # e.g. pediatrician (when action is doctors); None when using doctor_suggestion_text
    doctor_suggestion_text: Optional[str] = None  # LLM-generated short sentence suggesting which doctor type (when action is doctors)
    session_id: str
