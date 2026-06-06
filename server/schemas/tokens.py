"""API token schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class APITokenBase(BaseModel):
    """Base API token schema."""

    name: str


class APITokenCreate(APITokenBase):
    """API token creation schema."""

    pass


class APITokenResponse(APITokenBase):
    """API token response schema (for listing)."""

    id: int
    created_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class APITokenCreated(APITokenResponse):
    """API token response schema (returned only once upon creation)."""

    token: str
