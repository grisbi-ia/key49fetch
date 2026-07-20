"""Key49-Fetch REST API — Authentication module.

Simple API key authentication via X-API-Key header.
Configure via API_KEY or API_KEYS (comma-separated) env var.
If no key is configured, auth is disabled (dev mode).
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_403_FORBIDDEN

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Load keys once at module level
_configured_keys: Optional[set[str]] = None


def _load_keys() -> set[str] | None:
    """Load API keys from environment. Returns None if auth is disabled."""
    global _configured_keys
    if _configured_keys is not None:
        return _configured_keys

    single = os.environ.get("API_KEY", "").strip()
    multi = os.environ.get("API_KEYS", "").strip()

    keys: set[str] = set()
    if single:
        keys.add(single)
    if multi:
        keys.update(k.strip() for k in multi.split(",") if k.strip())

    _configured_keys = keys if keys else None
    return _configured_keys


async def verify_api_key(api_key: str = Security(API_KEY_HEADER)) -> str:
    """FastAPI dependency: validate X-API-Key header.

    Returns the validated key or raises 403.
    If no keys are configured, auth is bypassed (dev mode).
    """
    keys = _load_keys()

    if keys is None:
        # No keys configured → dev mode, allow all
        return api_key or "dev-mode"

    if not api_key:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Missing X-API-Key header",
        )

    if api_key not in keys:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key
