"""Async RSS feed client with rate-limit backoff.

Fetches RSS feeds using aiohttp, validates against the allowlist,
and parses with feedparser.  Applies exponential backoff on HTTP
429/503 responses per the SKILL.md specification.
"""

import asyncio
import logging
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
import feedparser

from services.news_engine.config.news_sources import get_allowed_urls

logger = logging.getLogger(__name__)

_INITIAL_BACKOFF = 30
_MAX_BACKOFF = 600


class RssClient:
    """Async RSS feed fetcher with per-feed backoff tracking."""

    def __init__(self) -> None:
        """Initialize HTTP session holder and per-source backoff map."""
        self._session: Optional[aiohttp.ClientSession] = None
        self._backoff: dict[str, float] = {}
        self._allowed_urls: set[str] = set(get_allowed_urls())

    def set_allowed_urls(self, urls: list[str] | set[str]) -> None:
        """Replace feed allowlist with runtime-configured source URLs.

        Args:
            urls: Allowed feed URLs.
        """
        self._allowed_urls = {u for u in urls if u}

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Create or reuse the internal aiohttp session.

        Returns:
            Active ``aiohttp.ClientSession`` instance.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    async def fetch_feed(self, url: str) -> list[dict[str, Any]]:
        """Fetch and parse one RSS/Atom feed.

        Args:
            url: Feed url.

        Returns:
            List of raw feed entries, or empty list on failure/validation
            issues/backoff responses.
        """
        if self._allowed_urls and url not in self._allowed_urls:
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

        session = self._ensure_session()
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

        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.exception("Failed to fetch %s", url)
            return []

    async def fetch_page(self, url: str) -> str:
        """Fetch generic html content for scrape-style sources.

        Args:
            url: Page url.

        Returns:
            Page html on success, otherwise empty string.
        """
        if urlparse(url).scheme not in ("http", "https"):
            logger.warning("Unsupported URL scheme for scraping: %s", url)
            return ""
        session = self._ensure_session()
        try:
            async with session.get(url) as resp:
                if resp.status >= 400:
                    logger.warning(
                        "HTML fetch failed for %s with status %d",
                        url,
                        resp.status,
                    )
                    return ""
                return await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            logger.exception("Failed to fetch page %s", url)
            return ""

    async def close(self) -> None:
        """Close underlying aiohttp session when open."""
        if self._session and not self._session.closed:
            await self._session.close()
