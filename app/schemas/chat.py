from pydantic import BaseModel
from typing import List, Optional


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
    remaining_prompts: Optional[int] = None  # set when applicable so UI can show "X messages left"


class BotMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class BotChatRequest(BaseModel):
    message: str
    history: Optional[List[BotMessage]] = None
    user_id: Optional[str] = None  # for anonymous; when absent, auth cookie is used
    session_id: Optional[str] = None


class BotChatResponse(BaseModel):
    reply: str
    remaining_prompts: Optional[int] = None  # same pool as main chat: 6 anon, 20 logged-in, many for tester
