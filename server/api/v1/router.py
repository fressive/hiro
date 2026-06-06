"""API v1 router - aggregates all v1 endpoints."""

from fastapi import APIRouter

from server.api.v1.endpoints import session, users, items, auth, install, llm, rag, health, mcp, tokens
from server.core.installation import is_application_installed

router = APIRouter()

# Include endpoint routers
router.include_router(auth.router, prefix="/auth", tags=["auth"])
router.include_router(users.router, prefix="/users", tags=["users"])
router.include_router(items.router, prefix="/items", tags=["items"])
router.include_router(session.router, prefix="/agent", tags=["agent"])
router.include_router(llm.router, prefix="/llm", tags=["llm"])
router.include_router(rag.router, prefix="/rag", tags=["rag"])
router.include_router(mcp.router, prefix="/mcp", tags=["mcp"])
router.include_router(tokens.router, prefix="/tokens", tags=["tokens"])
router.include_router(health.router, prefix="/health", tags=["health"])

if not is_application_installed():
    router.include_router(install.router, prefix="/install", tags=["install"])
