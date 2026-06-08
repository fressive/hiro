"""LLM configuration schemas."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class LLMConfigBase(BaseModel):
    """Base LLM configuration schema."""

    name: str
    provider: str
    base_url: Optional[str] = None
    api_key: str
    model: str
    enable_1m_context: Optional[bool] = False


class LLMConfigCreate(LLMConfigBase):
    """LLM configuration creation schema."""

    pass


class LLMConfigUpdate(BaseModel):
    """LLM configuration update schema."""

    name: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    enable_1m_context: Optional[bool] = None


class LLMConfigResponse(BaseModel):
    """LLM configuration response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    provider: str
    base_url: Optional[str] = None
    model: str
    enable_1m_context: bool

class LLMTestRequest(BaseModel):
    """LLM test request schema."""

    id: Optional[int] = None
    name: Optional[str] = None
    provider: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: str
    enable_1m_context: Optional[bool] = None


class LLMTestResponse(BaseModel):
    """LLM test response schema."""

    success: bool
    message: str
