"""Coin extractor — detects cryptocurrency mentions in article text.

Uses the configurable coin mapping with whole-word symbol matching
and ambiguous-symbol guard logic per the specification.
"""

import logging
import re

from services.news_engine.config.coin_map import CoinMap

logger = logging.getLogger(__name__)


class CoinExtractor:
    """Detects coin symbols and names in article text."""

    def __init__(self, coin_map: CoinMap) -> None:
        self._coin_map = coin_map
        self._symbol_patterns: dict[str, re.Pattern[str]] = {}
        self._build_patterns()

    def _build_patterns(self) -> None:
        """Build regex patterns for symbol detection."""
        for symbol in self._coin_map.all_symbols:
            self._symbol_patterns[symbol] = re.compile(
                rf"\b{re.escape(symbol)}\b"
            )

    def extract(self, text: str) -> list[str]:
        """Return a deduplicated list of detected coin symbols."""
        detected: set[str] = set()

        # 1. Name-based detection (case-insensitive).
        text_lower = text.lower()
        for name, symbol in self._coin_map.name_to_symbol.items():
            if name in text_lower:
                detected.add(symbol)

        # 2. Symbol-based detection (whole word, uppercase in source).
        for symbol, pattern in self._symbol_patterns.items():
            if pattern.search(text):
                if symbol in self._coin_map.ambiguous_symbols:
                    if not self._confirm_ambiguous(symbol, text_lower):
                        continue
                detected.add(symbol)

        if not detected:
            logger.debug("No coins detected in article text.")
        else:
            logger.debug("Coins detected: %s", detected)

        return sorted(detected)

    def _confirm_ambiguous(
        self, symbol: str, text_lower: str
    ) -> bool:
        """For ambiguous symbols, require the full name to appear."""
        full_name = self._coin_map.symbol_to_name.get(symbol, "")
        if not full_name:
            return False
        return full_name.lower() in text_lower

    def reload(self) -> None:
        """Reload coin map and rebuild patterns."""
        self._coin_map.check_reload()
        self._build_patterns()
