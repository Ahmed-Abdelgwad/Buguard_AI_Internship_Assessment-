"""Lightweight TTL cache for LangChain chain results.

Usage:
    result = chain_cache.get(key)
    if result is None:
        result = run_expensive_chain(...)
        chain_cache.set(key, result)
"""
import hashlib
import json
from typing import Any, Optional

from cachetools import TTLCache

from app.config import settings

_cache: TTLCache = TTLCache(
    maxsize=settings.cache_maxsize,
    ttl=settings.cache_ttl,
)


def _make_key(chain_name: str, payload: Any) -> str:
    raw = chain_name + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def get(chain_name: str, payload: Any) -> Optional[Any]:
    return _cache.get(_make_key(chain_name, payload))


def set(chain_name: str, payload: Any, value: Any) -> None:
    _cache[_make_key(chain_name, payload)] = value


def invalidate(chain_name: str, payload: Any) -> None:
    key = _make_key(chain_name, payload)
    _cache.pop(key, None)


def clear() -> None:
    _cache.clear()
