"""Article parser — cleans HTML, normalises text, detects language.

Only English articles are processed.  Non-English articles are
skipped and logged at DEBUG level per the specification.
"""

import logging
import re

from services.news_engine.signals.signal_models import Article, ParsedArticle

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
# Control characters U+0000–U+001F except newline (0x0A) and tab (0x09).
_CONTROL_CHAR_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f]"
)


def _strip_html(text: str) -> str:
    """Remove HTML tags from text."""
    return _HTML_TAG_RE.sub(" ", text)


def _normalise_whitespace(text: str) -> str:
    """Collapse whitespace to single spaces and strip."""
    return _WHITESPACE_RE.sub(" ", text).strip()


def _sanitise(text: str) -> str:
    """Remove control characters per the security spec."""
    return _CONTROL_CHAR_RE.sub("", text)


def _is_english(text: str) -> bool:
    """Simple heuristic language detection.

    Checks that the majority of characters are in the Basic Latin
    range, which works well for distinguishing English from
    non-Latin scripts.  For Latin-alphabet non-English, this is
    a best-effort filter.
    """
    if not text:
        return False
    ascii_count = sum(1 for c in text if c.isascii() and c.isalpha())
    alpha_count = sum(1 for c in text if c.isalpha())
    if alpha_count == 0:
        return False
    return (ascii_count / alpha_count) > 0.85


class ArticleParser:
    """Cleans and normalises raw articles for analysis."""

    def __init__(
        self,
        include_words: set[str] | None = None,
        exclude_words: set[str] | None = None,
    ) -> None:
        self._include_words: set[str] = include_words or set()
        self._exclude_words: set[str] = exclude_words or set()

    def update_filters(
        self,
        include_words: set[str],
        exclude_words: set[str],
    ) -> None:
        """Replace include/exclude word filter sets."""
        self._include_words = include_words
        self._exclude_words = exclude_words

    def parse(self, article: Article) -> ParsedArticle | None:
        """Clean an article and combine title + content.

        Returns None and logs if the article is non-English, or if it
        fails the active include/exclude word filters.
        """
        raw_text = f"{article.title} {article.content or article.summary}"
        cleaned = _strip_html(raw_text)
        cleaned = _sanitise(cleaned)
        cleaned = _normalise_whitespace(cleaned)

        if not _is_english(cleaned):
            logger.debug(
                "Skipping non-English article: %s", article.url
            )
            return None

        text_lower = cleaned.lower()

        # Include filter: at least one word must be present.
        if self._include_words:
            if not any(w in text_lower for w in self._include_words):
                logger.debug(
                    "Article excluded (include filter): %s",
                    article.url,
                )
                return None

        # Exclude filter: reject if any excluded word is present.
        if self._exclude_words:
            hit = next(
                (w for w in self._exclude_words if w in text_lower),
                None,
            )
            if hit:
                logger.debug(
                    "Article excluded by word '%s': %s",
                    hit,
                    article.url,
                )
                return None

        return ParsedArticle(
            text=cleaned,
            title=article.title,
            url=article.url,
            source=article.source,
            source_type=article.source_type,
            source_weight=article.source_weight,
            timestamp=article.timestamp,
        )
