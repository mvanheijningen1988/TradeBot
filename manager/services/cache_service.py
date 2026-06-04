"""In-memory cache service with TTL support.

Used for caching exchange data:
    - Markets: 24 h TTL
    - Fees: 5 min TTL
"""

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)


class CacheEntry:
    """Single cached value with expiry."""

    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: int) -> None:
        self.value = value
        self.expires_at = time.monotonic() + ttl

    @property
    def expired(self) -> bool:
        """Return True when the entry has passed its monotonic expiry."""
        return time.monotonic() >= self.expires_at


class CacheService:
    """Simple key-based in-memory cache with TTL."""

    def __init__(self) -> None:
        self._store: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Optional[Any]:
        """Return cached value or None if missing/expired."""
        entry = self._store.get(key)
        if entry is None or entry.expired:
            self._store.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl: int) -> None:
        """Store a value with TTL in seconds."""
        self._store[key] = CacheEntry(value, ttl)
        logger.debug("Cache set: %s (ttl=%ds)", key, ttl)

    def invalidate(self, key: str) -> None:
        """Remove a specific cache entry."""
        self._store.pop(key, None)

    def clear(self) -> None:
        """Remove all cached keys regardless of their expiry."""
        self._store.clear()
