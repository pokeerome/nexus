import math
import os
import threading
import time

from fastapi import Depends, HTTPException

from deps import get_current_user
from models import User

# name -> (max requests, window in seconds). Change the numbers here to tune.
LIMITS = {
    "chat": (20, 60),  # per user
    "agent": (8, 60),  # per user (the agent makes several AI calls per question)
    "search": (30, 60),  # per user
    "upload": (10, 60),  # per user
    "members": (20, 60),  # per user (stops guessing which emails exist)
    "llm_global": (300, 3600),  # everyone together: protects your OpenAI bill
    "signup_global": (30, 3600),  # everyone together: stops mass sign-ups
}
LOGIN_FAIL_LIMIT = (5, 900)  # 5 wrong passwords per email, then wait 15 minutes


def enabled() -> bool:
    return os.getenv("RATE_LIMITS", "on").lower() != "off"


class RateLimiter:
    """Fixed-window counter. Uses Redis when it can, and memory when it can't."""

    def __init__(self, redis_url: str | None = None):
        self._memory: dict[str, list] = {}
        self._lock = threading.Lock()
        self._redis = None
        if redis_url:
            try:
                import redis

                client = redis.Redis.from_url(
                    redis_url, socket_connect_timeout=1, socket_timeout=1
                )
                client.ping()
                self._redis = client
            except Exception as e:
                print("Rate limiter: Redis not available, using memory:", e)

    # -- memory version ----------------------------------------------------
    def _hit_memory(self, key, limit, window):
        now = time.monotonic()
        with self._lock:
            if len(self._memory) > 10000:
                self._memory = {k: v for k, v in self._memory.items() if v[0] > now}
            entry = self._memory.get(key)
            if entry is None or entry[0] <= now:
                entry = [now + window, 0]
                self._memory[key] = entry
            entry[1] += 1
            return entry[1] <= limit, max(1, math.ceil(entry[0] - now))

    def _count_memory(self, key):
        now = time.monotonic()
        with self._lock:
            entry = self._memory.get(key)
            if entry is None or entry[0] <= now:
                return 0, 0
            return entry[1], max(1, math.ceil(entry[0] - now))

    # -- public methods ----------------------------------------------------
    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Count one request. Returns (allowed, seconds until the window resets)."""
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.incr(f"rl:{key}")
                pipe.ttl(f"rl:{key}")
                count, ttl = pipe.execute()
                if ttl < 0:  # no expiry set yet (new key, or a crash left it without one)
                    self._redis.expire(f"rl:{key}", window)
                    ttl = window
                return count <= limit, max(1, ttl)
            except Exception:
                pass  # Redis problem: fall back to memory below
        return self._hit_memory(key, limit, window)

    def count(self, key: str) -> tuple[int, int]:
        """Current count and seconds left, without counting a new request."""
        if self._redis is not None:
            try:
                pipe = self._redis.pipeline()
                pipe.get(f"rl:{key}")
                pipe.ttl(f"rl:{key}")
                value, ttl = pipe.execute()
                return int(value or 0), max(1, ttl) if ttl and ttl > 0 else 0
            except Exception:
                pass
        return self._count_memory(key)

    def reset(self, key: str) -> None:
        if self._redis is not None:
            try:
                self._redis.delete(f"rl:{key}")
            except Exception:
                pass
        with self._lock:
            self._memory.pop(key, None)


limiter = RateLimiter(os.getenv("REDIS_URL"))


def too_many(retry_after: int):
    raise HTTPException(
        status_code=429,
        detail=f"Too many requests. Please try again in {retry_after} seconds.",
        headers={"Retry-After": str(retry_after)},
    )


def rate_limit(name: str):
    """Dependency: at most LIMITS[name] requests per user per window."""

    def checker(user: User = Depends(get_current_user)):
        if not enabled():
            return
        limit, window = LIMITS[name]
        allowed, retry_after = limiter.hit(f"{name}:{user.id}", limit, window)
        if not allowed:
            too_many(retry_after)

    return checker


def rate_limit_global(name: str):
    """Dependency: at most LIMITS[name] requests from everyone together per window."""

    def checker():
        if not enabled():
            return
        limit, window = LIMITS[name]
        allowed, retry_after = limiter.hit(f"{name}:all", limit, window)
        if not allowed:
            too_many(retry_after)

    return checker