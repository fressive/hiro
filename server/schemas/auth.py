"""Authentication schemas."""

from pydantic import BaseModel


class TokenResponse(BaseModel):
    """Token response schema."""

    access_token: str
    token_type: str = "bearer"
