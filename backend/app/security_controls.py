from __future__ import annotations

import hashlib
import os
import threading
import time
from collections import defaultdict
from typing import Iterable

from fastapi import HTTPException, Request

RISKLENS_ENV = os.getenv("RISKLENS_ENV", "development").strip().lower()
REDIS_URL = os.getenv("RISKLENS_REDIS_URL", "").strip()
if RISKLENS_ENV == "production" and not REDIS_URL:
    raise RuntimeError("RISKLENS_REDIS_URL is required for production rate limiting")
if RISKLENS_ENV == "production" and not REDIS_URL.lower().startswith("rediss://"):
    raise RuntimeError("Production rate limiting requires a TLS-protected rediss:// Redis URL")

_redis = None
if REDIS_URL:
    try:
        from redis import Redis
        from redis.exceptions import RedisError

        _redis = Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=2)
    except Exception as exc:
        if RISKLENS_ENV == "production":
            raise RuntimeError("Could not initialize the configured Redis rate limiter") from exc
        _redis = None
else:
    RedisError = Exception

_lock = threading.Lock()
_windows: dict[str, tuple[int, float]] = {}
_REDIS_SCRIPT = """
local count = redis.call('INCR', KEYS[1])
if count == 1 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {count, ttl}
"""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identity(request: Request) -> str:
    # Do not trust X-Forwarded-For unless the application is configured behind
    # a proxy that explicitly strips and rewrites that header.
    return request.client.host if request.client else "unknown-client"


def _consume(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    if _redis is not None:
        try:
            count, ttl = _redis.eval(_REDIS_SCRIPT, 1, key, window_seconds)
            retry_after = max(1, int(ttl or window_seconds))
            return int(count) <= limit, retry_after
        except Exception as exc:
            if RISKLENS_ENV == "production":
                raise HTTPException(
                    status_code=503,
                    detail="Rate-limiting service is temporarily unavailable",
                    headers={"Retry-After": "5"},
                ) from exc
    now = time.monotonic()
    with _lock:
        count, expires_at = _windows.get(key, (0, now + window_seconds))
        if now >= expires_at:
            count, expires_at = 0, now + window_seconds
        count += 1
        _windows[key] = (count, expires_at)
        # Bound memory growth in the local-only fallback.
        if len(_windows) > 20_000:
            for old_key, (_, expiry) in list(_windows.items()):
                if expiry <= now:
                    _windows.pop(old_key, None)
        return count <= limit, max(1, int(expires_at - now))


def enforce_rate_limit(
    request: Request,
    bucket: str,
    limit: int,
    window_seconds: int,
    identities: Iterable[str] | None = None,
) -> None:
    client_id = _identity(request)
    values = [f"ip:{client_id}"]
    if identities:
        values.extend(f"identity:{value.strip().lower()}" for value in identities if value)
    for value in values:
        allowed, retry_after = _consume(
            f"risklens:rate:{bucket}:{_digest(value)}",
            limit,
            window_seconds,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )
