"""Authentication middleware."""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from sqlalchemy import select
from datetime import datetime, timezone

from server.core.config import settings
from server.core.security import verify_token, verify_password
from server.db import AsyncSessionLocal
from server.models.token import APIToken


class AuthMiddleware(BaseHTTPMiddleware):
    """Authentication middleware for validating API requests."""

    # Public endpoints that don't require authentication
    PUBLIC_ROUTES = {
        "/api/v1/auth/login",
        "/api/v1/install",
        "/api/v1/install/status",
        "/api/v1/install/check-db",
        "/api/v1/health",
    }

    async def dispatch(self, request: Request, call_next):
        """Process the request and validate authentication if needed."""
        
        # Skip authentication for public endpoints
        if request.url.path in self.PUBLIC_ROUTES or request.url.path.startswith("/docs"):
            return await call_next(request)

        # Get Authorization header
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            # Check for API Key header as alternative
            api_key = request.headers.get(settings.api_key_header)
            if not api_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Missing authentication credentials"},
                )
            
            # Validate API Key against database
            async with AsyncSessionLocal() as session:
                # Fetch all tokens to verify (since they are hashed with salt)
                result = await session.execute(select(APIToken))
                token_records = result.scalars().all()
                
                matched_token = None
                for t in token_records:
                    if verify_password(api_key, t.hashed_token):
                        matched_token = t
                        break
                
                if not matched_token:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid API Key"},
                    )
                
                # Update last used time
                matched_token.last_used_at = datetime.now(timezone.utc)
                await session.commit()
                
                request.state.user = {"sub": f"api_token_{matched_token.id}", "name": matched_token.name, "role": "api"}
        else:
            # Extract Bearer token
            try:
                scheme, token = auth_header.split()
                if scheme.lower() != "bearer":
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid authentication scheme"},
                    )
                
                payload = verify_token(token)
                if not payload:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Invalid or expired token"},
                    )
                
                request.state.user = payload
            except ValueError:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid authorization header"},
                )

        response = await call_next(request)
        return response
