"""API Token endpoints."""

import secrets
from typing import List
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.security import hash_password
from server.db import get_session
from server.models.token import APIToken
from server.schemas.tokens import APITokenCreate, APITokenResponse, APITokenCreated

router = APIRouter()


@router.get("", response_model=List[APITokenResponse])
async def list_tokens(session: AsyncSession = Depends(get_session)):
    """List all API tokens."""
    result = await session.execute(select(APIToken).order_by(APIToken.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=APITokenCreated)
async def create_token(
    payload: APITokenCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new API token."""
    # Generate a secure random token
    token_value = f"hiro_{secrets.token_urlsafe(32)}"
    
    new_token = APIToken(
        name=payload.name,
        hashed_token=hash_password(token_value),
    )
    session.add(new_token)
    await session.commit()
    await session.refresh(new_token)
    
    # Manually construct response to include plain token
    return APITokenCreated(
        id=new_token.id,
        name=new_token.name,
        token=token_value,
        created_at=new_token.created_at,
        last_used_at=new_token.last_used_at
    )


@router.delete("/{token_id}")
async def delete_token(
    token_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete an API token."""
    result = await session.execute(select(APIToken).where(APIToken.id == token_id))
    token = result.scalars().first()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")
    
    await session.delete(token)
    await session.commit()
    
    return {"message": "Token deleted"}
