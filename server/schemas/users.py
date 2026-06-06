"""User schemas."""

from typing import Optional

from pydantic import BaseModel, Field


class UserBase(BaseModel):
    """Base user schema."""

    username: str
    email: Optional[str] = None


class UserCreate(UserBase):
    """User creation schema."""

    password: str = Field(..., max_length=72)


class UserResponse(UserBase):
    """User response schema."""

    id: Optional[int] = None

    class Config:
        from_attributes = True
