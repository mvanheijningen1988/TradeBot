"""RSS news source configuration.

Sources are checked against this allowlist before fetching.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsSource:
    """A single configured news source."""

    name: str
    url: str
    source_type: str = "rss"
    weight: float = 1.0


DEFAULT_SOURCES: list[NewsSource] = [
    NewsSource(
        name="CoinDesk",
        url="https://www.coindesk.com/arc/outboundfeeds/rss/",
        source_type="rss",
        weight=1.0,
    ),
    NewsSource(
        name="CoinTelegraph",
        url="https://cointelegraph.com/rss",
        source_type="rss",
        weight=1.0,
    ),
    NewsSource(
        name="Decrypt",
        url="https://decrypt.co/feed",
        source_type="rss",
        weight=1.0,
    ),
    NewsSource(
        name="BeInCrypto",
        url="https://beincrypto.com/feed/",
        source_type="rss",
        weight=1.0,
    ),
]


def get_allowed_urls() -> set[str]:
    """Return set of allowed RSS feed URLs for validation."""
    return {s.url for s in DEFAULT_SOURCES}
