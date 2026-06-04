"""Async RSS feed client with rate-limit backoff.

Fetches RSS feeds using aiohttp, validates against the allowlist,
and parses with feedparser.  Applies exponential backoff on HTTP
429/503 responses per the SKILL.md specification.
"""

import asyncio
import logging
from typing import Any, Optional

import aiohttp
import feedparser

from services.news_engine.config.news_sources import get_allowed_urls

logger = logging.getLogger(__name__)

_INITIAL_BACKOFF = 30
_MAX_BACKOFF = 600


class RssClient:
    """Async RSS feed fetcher with per-feed backoff tracking."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._backoff: dict[str, float] = {}

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def fetch_feed(self, url: str) -> list[dict[str, Any]]:
        """Fetch and parse an RSS feed, returning raw entry dicts."""
        allowed = get_allowed_urls()
        if url not in allowed:
            logger.warning(
                "RSS URL not in allowlist, skipping: %s", url
            )
            return []

        backoff = self._backoff.get(url, 0)
        if backoff > 0:
            logger.debug(
                "Backing off %s for %.0fs", url, backoff
            )
            await asyncio.sleep(backoff)

        session = await self._ensure_session()
        try:
            async with session.get(url) as resp:
                if resp.status in (429, 503):
                    new_backoff = min(
                        (self._backoff.get(url, _INITIAL_BACKOFF / 2)) * 2,
                        _MAX_BACKOFF,
                    )
                    self._backoff[url] = max(new_backoff, _INITIAL_BACKOFF)
                    logger.warning(
                        "HTTP %d from %s, backoff %.0fs",
                        resp.status,
                        url,
                        self._backoff[url],
                    )
                    return []

                self._backoff.pop(url, None)
                raw = await resp.text()

                # Validate it looks like RSS/Atom XML.
                if "<rss" not in raw[:500] and "<feed" not in raw[:500]:
                    logger.warning(
                        "Response from %s is not valid RSS/Atom XML",
                        url,
                    )
                    return []

                feed = feedparser.parse(raw)
                return feed.entries or []

        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            logger.error("Failed to fetch %s: %s", url, exc)
            return []

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
