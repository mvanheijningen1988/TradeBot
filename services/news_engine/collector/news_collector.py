"""News collector — fetches and deduplicates articles from RSS feeds.

Collects articles from all configured RSS sources, normalises
timestamps, prevents duplicates via URL and content hash, and
returns structured Article objects.
"""

import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from services.news_engine.collector.rss_client import RssClient
from services.news_engine.config.news_sources import (
    DEFAULT_SOURCES,
    NewsSource,
)
from services.news_engine.signals.signal_models import Article

logger = logging.getLogger(__name__)

_MAX_SEEN = 10_000


class NewsCollector:
    """Async RSS news collector with deduplication."""

    def __init__(
        self,
        sources: list[NewsSource] | None = None,
        rss_client: RssClient | None = None,
    ) -> None:
        self._sources = sources or DEFAULT_SOURCES
        self._client = rss_client or RssClient()
        self._seen_urls: set[str] = set()
        self._seen_hashes: set[str] = set()

    def update_sources(self, sources: list[NewsSource]) -> None:
        """Replace the active source list (takes effect next cycle)."""
        if sources:
            self._sources = sources
            logger.info(
                "News collector: %d active feeds updated.",
                len(sources),
            )

    async def collect(self) -> list[Article]:
        """Fetch all feeds and return new, deduplicated articles."""
        articles: list[Article] = []
        for source in self._sources:
            entries = await self._client.fetch_feed(source.url)
            for entry in entries:
                article = self._parse_entry(entry, source.name)
                if article and not self._is_duplicate(article):
                    self._mark_seen(article)
                    articles.append(article)
        logger.info("Collected %d new articles.", len(articles))
        return articles

    def _parse_entry(
        self, entry: dict[str, Any], source: str
    ) -> Article | None:
        """Convert a feedparser entry to an Article model."""
        url = entry.get("link", "")
        title = entry.get("title", "")
        if not url or not title:
            return None

        content = ""
        if "content" in entry and entry["content"]:
            content = entry["content"][0].get("value", "")
        elif "summary" in entry:
            content = entry.get("summary", "")

        timestamp = self._parse_timestamp(entry)
        content_hash = hashlib.sha256(
            (title + content).encode("utf-8")
        ).hexdigest()

        return Article(
            title=title,
            url=url,
            source=source,
            timestamp=timestamp,
            summary=entry.get("summary", ""),
            content=content,
            content_hash=content_hash,
        )

    def _parse_timestamp(self, entry: dict[str, Any]) -> datetime:
        """Extract and normalise timestamp from feed entry."""
        for field in ("published", "updated"):
            raw = entry.get(field)
            if raw:
                try:
                    return parsedate_to_datetime(raw).astimezone(
                        timezone.utc
                    )
                except (ValueError, TypeError):
                    pass
        return datetime.now(timezone.utc)

    def _is_duplicate(self, article: Article) -> bool:
        """Check if article has been seen before."""
        if article.url in self._seen_urls:
            return True
        if article.content_hash in self._seen_hashes:
            return True
        return False

    def _mark_seen(self, article: Article) -> None:
        """Record article as processed, pruning if needed."""
        self._seen_urls.add(article.url)
        self._seen_hashes.add(article.content_hash)
        if len(self._seen_urls) > _MAX_SEEN:
            self._seen_urls = set(list(self._seen_urls)[-_MAX_SEEN:])
        if len(self._seen_hashes) > _MAX_SEEN:
            self._seen_hashes = set(
                list(self._seen_hashes)[-_MAX_SEEN:]
            )

    async def close(self) -> None:
        """Close the underlying HTTP client and release network resources."""
        await self._client.close()
