"""Item schemas."""

from typing import Optional

from pydantic import BaseModel


class ItemBase(BaseModel):
    """Base item schema."""

    name: str
    description: Optional[str] = None


class ItemCreate(ItemBase):
    """Item creation schema."""

    pass


class ItemResponse(ItemBase):
    """Item response schema."""

    id: Optional[int] = None

    class Config:
        from_attributes = True
