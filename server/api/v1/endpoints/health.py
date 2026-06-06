"""Authentication endpoints."""

from fastapi import APIRouter
from server.core.installation import is_application_installed

router = APIRouter()

@router.get("")
def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "installed": is_application_installed(),
    }