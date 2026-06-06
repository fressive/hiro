"""Installation schemas."""

from typing import List, Optional

from pydantic import BaseModel, Field


class InstallationStatusResponse(BaseModel):
    """Installation status response schema."""

    installed: bool


class InstallationRequest(BaseModel):
    """Application installation request schema."""

    database_url: str
    admin_username: str
    admin_email: Optional[str] = None
    admin_password: str = Field(..., max_length=72)


class InstallationResponse(BaseModel):
    """Application installation response schema."""

    installed: bool
    message: str


class DatabaseCheckRequest(BaseModel):
    """Database connection check request schema."""

    database_url: str


class DatabaseCheckResponse(BaseModel):
    """Database connection check response schema."""

    success: bool
    message: str


class SystemCheckItem(BaseModel):
    """System check item schema."""

    name: str
    exists: bool
    message: Optional[str] = None


class SystemCheckResponse(BaseModel):
    """System check response schema."""

    success: bool
    items: List[SystemCheckItem]
