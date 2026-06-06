"""User endpoints."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.core.security import hash_password
from server.db import get_session
from server.models.models import User
from server.schemas.users import UserCreate, UserResponse

router = APIRouter()


@router.get("", response_model=List[UserResponse])
async def list_users(request: Request, session: AsyncSession = Depends(get_session)):
    """
    List all users.
    
    Requires authentication.
    """
    # User info is available from middleware
    if not hasattr(request.state, "user"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    result = await session.execute(select(User))
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    """
    Get a specific user by ID.
    
    Requires authentication.
    """
    if not hasattr(request.state, "user"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalars().first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return user


@router.post("", response_model=UserResponse)
async def create_user(
    user: UserCreate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    """
    Create a new user.
    
    Requires authentication.
    """
    if not hasattr(request.state, "user"):
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    result = await session.execute(select(User).where(User.username == user.username))
    existing_user = result.scalars().first()
    if existing_user:
        raise HTTPException(status_code=409, detail="Username already exists")

    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hash_password(user.password),
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    return new_user
