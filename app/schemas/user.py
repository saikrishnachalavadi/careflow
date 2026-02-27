from pydantic import BaseModel
from typing import Literal
from datetime import datetime


class User(BaseModel):
    id: str
    phone: str
    created_at: datetime
    otc_attempts_used: int = 0
    otc_privilege_status: Literal["ACTIVE", "LOCKED"] = "ACTIVE"
    abuse_strikes: int = 0