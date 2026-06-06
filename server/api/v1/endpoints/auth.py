"""Authentication endpoints."""

from fastapi import APIRouter, HTTPException, Depends
from datetime import timedelta
from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession
from server.models.schemas import TokenResponse
from server.core.security import create_access_token, verify_password
from server.db import get_session
from server.models.models import User


router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(username: str, password: str, session: AsyncSession = Depends(get_session)):
    """Generate a JWT token for authentication using DB-stored users."""
    if not username or not password:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Try to find user in DB
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalars().first()

    if user and verify_password(password, user.hashed_password):
        access_token = create_access_token(
            data={"sub": username, "role": "user"},
            expires_delta=timedelta(hours=24),
        )
        return {"access_token": access_token, "token_type": "bearer"}

    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.post("/refresh")
async def refresh_token():
    """Refresh an expired token. TODO: Implement token refresh logic."""
    return {"message": "Token refresh not yet implemented"}
