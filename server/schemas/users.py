"""User schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserBase(BaseModel):
    """Base user schema."""

    username: str
    email: Optional[str] = None


class UserCreate(UserBase):
    """User creation schema."""

    password: str = Field(..., max_length=72)


class UserResponse(UserBase):
    """User response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
