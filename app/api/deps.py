"""Shared FastAPI dependencies."""
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str = Security(_api_key_header)) -> str:
    """Dependency that enforces API key authentication on write endpoints."""
    if not key or key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Supply X-API-Key header.",
        )
    return key
