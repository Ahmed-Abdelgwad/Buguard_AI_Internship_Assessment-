"""Shared FastAPI dependencies — API key auth with role-based access control.

Two roles:
  admin  — full access: import assets, lifecycle refresh, all read operations
  reader — read-only: list assets, AI analysis, graph; cannot import or mutate

Environment variables:
  API_KEY        → admin key   (default: "changeme")
  READER_API_KEY → reader key  (default: "readonly")
"""
import enum

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from app.config import settings

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


class Role(str, enum.Enum):
    admin = "admin"
    reader = "reader"


def _resolve_role(key: str | None) -> Role | None:
    """Return the role for a given key, or None if the key is invalid/missing."""
    if not key:
        return None
    if key == settings.api_key:
        return Role.admin
    if key == settings.reader_api_key:
        return Role.reader
    return None


def require_admin(key: str = Security(_api_key_header)) -> str:
    """Dependency: requires admin role. Used on write/mutating endpoints."""
    if _resolve_role(key) == Role.admin:
        return key
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin API key required. Supply X-API-Key header with an admin key.",
    )


def require_reader(key: str = Security(_api_key_header)) -> str:
    """Dependency: requires at least reader role (admin key is also accepted)."""
    role = _resolve_role(key)
    if role in (Role.admin, Role.reader):
        return key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API key required. Supply X-API-Key header (admin or reader key).",
    )


# Backward-compatible alias so existing usages of require_api_key still work
require_api_key = require_admin
