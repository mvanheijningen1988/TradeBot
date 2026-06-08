"""News collector — fetches and deduplicates articles from RSS feeds and pages.

Collects articles from all configured RSS sources, normalises
timestamps, prevents duplicates via URL and content hash, and
returns structured Article objects.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

from services.news_engine.collector.rss_client import RssClient
from services.news_engine.config.news_sources import (
    DEFAULT_SOURCES,
    NewsSource,
)
from services.news_engine.signals.signal_models import Article

logger = logging.getLogger(__name__)

_MAX_SEEN = 10_000
_MAX_SCRAPED_LINKS = 10
_ARTICLE_LINK_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class NewsCollector:
    """Collect articles from RSS and scraped sources with deduplication."""

    def __init__(
        self,
        sources: list[NewsSource] | None = None,
        rss_client: RssClient | None = None,
    ) -> None:
        """Initialize a collector instance.

        Args:
            sources: Optional source override. Defaults to configured
                ``DEFAULT_SOURCES``.
            rss_client: Optional HTTP/feed client for dependency injection.
        """
        self._sources = sources or DEFAULT_SOURCES
        self._client = rss_client or RssClient()
        self._seen_urls: set[str] = set()
        self._seen_hashes: set[str] = set()
        self._sync_rss_allowlist()

    def _sync_rss_allowlist(self) -> None:
        """Update RSS client allowlist from currently configured sources."""
        rss_urls = [
            source.url
            for source in self._sources
            if source.source_type == "rss"
        ]
        self._client.set_allowed_urls(rss_urls)

    def update_sources(self, sources: list[NewsSource]) -> None:
        """Replace active source list for subsequent collect cycles.

        Args:
            sources: New source definitions.
        """
        if sources:
            self._sources = sources
            self._sync_rss_allowlist()
            logger.info(
                "News collector: %d active feeds updated.",
                len(sources),
            )

    async def collect(self) -> list[Article]:
        """Fetch all configured sources and return new articles.

        Returns:
            Deduplicated list of parsed ``Article`` objects.
        """
        articles: list[Article] = []
        for source in self._sources:
            if source.source_type == "scrape":
                scraped = await self._collect_scraped_source(source)
                articles.extend(scraped)
                continue

            entries = await self._client.fetch_feed(source.url)
            for entry in entries:
                article = self._parse_entry(entry, source)
                if article and not self._is_duplicate(article):
                    self._mark_seen(article)
                    articles.append(article)
        logger.info("Collected %d new articles.", len(articles))
        return articles

    def _parse_entry(
        self, entry: dict[str, Any], source: NewsSource
    ) -> Article | None:
        """Convert one feed entry payload into an ``Article``.

        Args:
            entry: Feed parser item payload.
            source: Source metadata used for attribution and weighting.

        Returns:
            Parsed article, or ``None`` when required fields are missing.
        """
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
            source=source.name,
            source_type=source.source_type,
            source_weight=source.weight,
            timestamp=timestamp,
            summary=entry.get("summary", ""),
            content=content,
            content_hash=content_hash,
        )

    async def _collect_scraped_source(
        self,
        source: NewsSource,
    ) -> list[Article]:
        """Scrape source pages and produce article candidates.

        Args:
            source: Scrape-enabled source definition.

        Returns:
            List of deduplicated scraped articles.
        """
        page = await self._client.fetch_page(source.url)
        if not page:
            return []

        links = self._extract_article_links(page, source.url)
        if links:
            articles: list[Article] = []
            for link in links[:_MAX_SCRAPED_LINKS]:
                article = await self._scrape_article(link, source)
                if article and not self._is_duplicate(article):
                    self._mark_seen(article)
                    articles.append(article)
            if articles:
                return articles

        article = self._scrape_page(source.url, page, source)
        if article and not self._is_duplicate(article):
            self._mark_seen(article)
            return [article]
        return []

    async def _scrape_article(
        self,
        url: str,
        source: NewsSource,
    ) -> Article | None:
        """Scrape one linked page and parse it to an article.

        Args:
            url: Absolute page url.
            source: Source metadata.

        Returns:
            Parsed article or ``None`` when page fetch fails.
        """
        page = await self._client.fetch_page(url)
        if not page:
            return None
        return self._scrape_page(url, page, source)

    def _scrape_page(
        self,
        url: str,
        html: str,
        source: NewsSource,
    ) -> Article | None:
        """Convert scraped HTML to a normalized ``Article``.

        Args:
            url: Page url used for article identity.
            html: Raw html content.
            source: Source metadata.

        Returns:
            Parsed article or ``None`` when no useful content exists.
        """
        title = self._extract_title(html)
        text = self._extract_main_text(html)
        if not title and not text:
            return None

        cleaned = _WHITESPACE_RE.sub(" ", unescape(text)).strip()
        if not cleaned and not title:
            return None

        timestamp = datetime.now(timezone.utc)
        content_hash = hashlib.sha256(
            (title + cleaned).encode("utf-8")
        ).hexdigest()
        return Article(
            title=title or cleaned[:120] or source.name,
            url=url,
            source=source.name,
            source_type=source.source_type,
            source_weight=source.weight,
            timestamp=timestamp,
            summary=cleaned[:320],
            content=cleaned,
            content_hash=content_hash,
        )

    def _extract_article_links(self, html: str, base_url: str) -> list[str]:
        """Extract likely in-domain article links from listing html.

        Args:
            html: Listing page html content.
            base_url: Canonical source url used for resolution and filtering.

        Returns:
            Unique absolute article urls (bounded by internal scrape limit).
        """
        base_domain = urlparse(base_url).netloc.lower()
        candidates: list[str] = []
        seen: set[str] = set()

        for match in _ARTICLE_LINK_RE.findall(html):
            if match.startswith(("#", "javascript:")):
                continue
            absolute = urljoin(base_url, match)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if parsed.netloc.lower() != base_domain:
                continue
            lowered = absolute.lower()
            if not any(
                token in lowered
                for token in ("news", "article", "post", "blog", "story")
            ):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            candidates.append(absolute)
            if len(candidates) >= _MAX_SCRAPED_LINKS:
                break

        return candidates

    def _extract_title(self, html: str) -> str:
        """Extract best-effort title text from html.

        Args:
            html: Page html.

        Returns:
            Cleaned title text or empty string.
        """
        patterns = [
            (
                r'<meta[^>]+property=["\']og:title["\']'
                r'[^>]+content=["\']([^"\']+)["\']'
            ),
            r'<title[^>]*>(.*?)</title>',
            r'<h1[^>]*>(.*?)</h1>',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                return self._clean_html(match.group(1))
        return ""

    def _extract_main_text(self, html: str) -> str:
        """Extract best-effort article text from html.

        Args:
            html: Page html.

        Returns:
            Cleaned body text or empty string.
        """
        patterns = [
            (
                r'<meta[^>]+property=["\']og:description["\']'
                r'[^>]+content=["\']([^"\']+)["\']'
            ),
            r'<article[^>]*>(.*?)</article>',
            r'<main[^>]*>(.*?)</main>',
            r'<body[^>]*>(.*?)</body>',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
            if match:
                return self._clean_html(match.group(1))
        return ""

    def _clean_html(self, value: str) -> str:
        """Remove html tags/entities and normalize whitespace.

        Args:
            value: Raw html/text segment.

        Returns:
            Clean plain-text value.
        """
        text = unescape(_TAG_RE.sub(" ", value))
        return _WHITESPACE_RE.sub(" ", text).strip()

    def _parse_timestamp(self, entry: dict[str, Any]) -> datetime:
        """Parse publication timestamp from feed entry.

        Args:
            entry: Feed parser item payload.

        Returns:
            Timezone-aware UTC datetime, falling back to current UTC time.
        """
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
        """Check whether an article url/content hash was already processed.

        Args:
            article: Candidate article.

        Returns:
            ``True`` if already seen, else ``False``.
        """
        if article.url in self._seen_urls:
            return True
        if article.content_hash in self._seen_hashes:
            return True
        return False

    def _mark_seen(self, article: Article) -> None:
        """Record processed article identity and prune in-memory sets.

        Args:
            article: Parsed article to mark as processed.
        """
        self._seen_urls.add(article.url)
        self._seen_hashes.add(article.content_hash)
        if len(self._seen_urls) > _MAX_SEEN:
            self._seen_urls = set(list(self._seen_urls)[-_MAX_SEEN:])
        if len(self._seen_hashes) > _MAX_SEEN:
            self._seen_hashes = set(
                list(self._seen_hashes)[-_MAX_SEEN:]
            )

    async def close(self) -> None:
        """Close underlying HTTP resources.

        Returns:
            ``None``.
        """
        await self._client.close()
