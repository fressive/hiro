"""Item schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class ItemBase(BaseModel):
    """Base item schema."""

    name: str
    description: Optional[str] = None


class ItemCreate(ItemBase):
    """Item creation schema."""

    pass


class ItemResponse(ItemBase):
    """Item response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[int] = None
