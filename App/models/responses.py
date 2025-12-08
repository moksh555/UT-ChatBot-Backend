"""
Response models.
"""

from pydantic import BaseModel
from typing import Optional


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """User data response."""
    user_id: str
    email: str
    full_name: Optional[str] = None
    created_at: str


class ChatResponse(BaseModel):
    """Chat response."""
    thread_id: str
    user_message: str
    model_response: str