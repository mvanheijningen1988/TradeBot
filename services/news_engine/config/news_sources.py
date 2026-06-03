"""RSS news source configuration.

Sources are checked against this allowlist before fetching.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class NewsSource:
    """A single RSS news source."""

    name: str
    url: str


DEFAULT_SOURCES: list[NewsSource] = [
    NewsSource(
        name="CoinDesk",
        url="https://www.coindesk.com/arc/outboundfeeds/rss/",
    ),
    NewsSource(
        name="CoinTelegraph",
        url="https://cointelegraph.com/rss",
    ),
    NewsSource(
        name="Decrypt",
        url="https://decrypt.co/feed",
    ),
    NewsSource(
        name="BeInCrypto",
        url="https://beincrypto.com/feed/",
    ),
]


def get_allowed_urls() -> set[str]:
    """Return set of allowed RSS feed URLs for validation."""
    return {s.url for s in DEFAULT_SOURCES}
