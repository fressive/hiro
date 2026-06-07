"""LLM configuration endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.db import get_session
from server.models.llm import LLMConfig
from server.schemas.llm import (
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMConfigResponse,
    LLMTestRequest,
    LLMTestResponse,
)

# Use langchain for testing
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage


router = APIRouter()


@router.get("", response_model=List[LLMConfigResponse])
async def list_llm_configs(session: AsyncSession = Depends(get_session)):
    """List all LLM configurations."""
    result = await session.execute(select(LLMConfig))
    return result.scalars().all()


@router.post("", response_model=LLMConfigResponse)
async def create_llm_config(
    payload: LLMConfigCreate, session: AsyncSession = Depends(get_session)
):
    """Create a new LLM configuration."""
    db_config = LLMConfig(
        name=payload.name,
        provider=payload.provider,
        base_url=payload.base_url,
        api_key=payload.api_key,
        model=payload.model,
        enable_1m_context=payload.enable_1m_context,
    )
    session.add(db_config)
    await session.commit()
    await session.refresh(db_config)
    return db_config


@router.post("/test", response_model=LLMTestResponse)
async def test_llm_config(
    payload: LLMTestRequest, session: AsyncSession = Depends(get_session)
):
    """Test an LLM configuration connectivity."""
    try:
        api_key = payload.api_key
        # If testing an existing config and api_key is empty, use the stored one
        if not api_key and payload.id:
            result = await session.execute(
                select(LLMConfig).where(LLMConfig.id == payload.id)
            )
            db_config = result.scalars().first()
            if db_config:
                api_key = db_config.api_key

        if not api_key:
            return LLMTestResponse(success=False, message="API Key is required")

        base_url = payload.base_url or None
        if payload.provider.lower() == "openai":
            kwargs = {}
            if payload.enable_1m_context:
                # For Moonshot and other OpenAI-compatible providers that need this in the body
                kwargs["model_kwargs"] = {"enable_1m_context": True}
            
            llm = ChatOpenAI(
                api_key=api_key,
                base_url=base_url,
                model=payload.model,
                max_retries=1,
                timeout=10,
                **kwargs
            )
        elif payload.provider.lower() == "anthropic":
            kwargs = {}
            if payload.enable_1m_context:
                kwargs["betas"] = ["context-1m-2025-08-07"]
            
            llm = ChatAnthropic(
                api_key=api_key,
                base_url=base_url,
                model=payload.model,
                max_retries=1,
                timeout=10,
                **kwargs
            )
        else:
            return LLMTestResponse(
                success=False, message=f"Unsupported provider: {payload.provider}"
            )

        # Simple ping test
        await llm.ainvoke("hi")
        return LLMTestResponse(success=True, message="LLM test successfully")

    except Exception as e:
        return LLMTestResponse(success=False, message=str(e))


@router.put("/{config_id}", response_model=LLMConfigResponse)
async def update_llm_config(
    config_id: int,
    payload: LLMConfigUpdate,
    session: AsyncSession = Depends(get_session),
):
    """Update an LLM configuration."""
    result = await session.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    db_config = result.scalars().first()
    if not db_config:
        raise HTTPException(status_code=404, detail="Config not found")

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if key == "api_key" and not value:
            continue
        setattr(db_config, key, value)

    await session.commit()
    await session.refresh(db_config)
    return db_config


@router.post("/{config_id}/test", response_model=LLMTestResponse)
async def test_existing_llm_config(
    config_id: int, session: AsyncSession = Depends(get_session)
):
    """Test an existing LLM configuration connectivity."""
    result = await session.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    db_config = result.scalars().first()
    if not db_config:
        raise HTTPException(status_code=404, detail="Config not found")

    try:
        base_url = db_config.base_url or None
        if db_config.provider.lower() == "openai":
            kwargs = {}
            if db_config.enable_1m_context:
                kwargs["model_kwargs"] = {"enable_1m_context": True}
            
            llm = ChatOpenAI(
                api_key=db_config.api_key,
                base_url=base_url,
                model=db_config.model,
                max_retries=1,
                timeout=10,
                **kwargs
            )
        elif db_config.provider.lower() == "anthropic":
            kwargs = {}
            if db_config.enable_1m_context:
                kwargs["betas"] = ["context-1m-2025-08-07"]
            
            llm = ChatAnthropic(
                api_key=db_config.api_key,
                base_url=base_url,
                model=db_config.model,
                max_retries=1,
                timeout=10,
                **kwargs
            )
        else:
            return LLMTestResponse(
                success=False, message=f"Unsupported provider: {db_config.provider}"
            )

        # Simple ping test
        await llm.ainvoke("hi")
        return LLMTestResponse(success=True, message="LLM test successfully")

    except Exception as e:
        return LLMTestResponse(success=False, message=str(e))


@router.delete("/{config_id}")
async def delete_llm_config(config_id: int, session: AsyncSession = Depends(get_session)):
    """Delete an LLM configuration."""
    result = await session.execute(select(LLMConfig).where(LLMConfig.id == config_id))
    db_config = result.scalars().first()
    if not db_config:
        raise HTTPException(status_code=404, detail="Config not found")
    
    await session.delete(db_config)
    await session.commit()
    return {"message": "Config deleted successfully"}
