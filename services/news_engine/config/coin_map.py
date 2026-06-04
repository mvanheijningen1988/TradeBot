"""Coin mapping configuration with hot-reload support.

Loads the coin mapping from an external JSON file and checks for
changes every processing cycle based on file modification timestamp.
"""

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "coin_mapping.json")


class CoinMap:
    """Configurable coin mapping with hot-reload support."""

    def __init__(self, path: str = _DEFAULT_PATH) -> None:
        self._path = path
        self._last_mtime: float = 0
        self._name_to_symbol: dict[str, str] = {}
        self._symbol_to_name: dict[str, str] = {}
        self._ambiguous_symbols: set[str] = set()
        self._load(fail_on_error=True)

    def _load(self, fail_on_error: bool = False) -> None:
        """Load or reload the mapping file."""
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)

            coins = data.get("coins", {})
            if not isinstance(coins, dict) or not coins:
                raise ValueError("coin mapping is empty or invalid")

            self._name_to_symbol = {
                name.lower(): symbol for name, symbol in coins.items()
            }
            self._symbol_to_name = {
                symbol: name for name, symbol in coins.items()
            }
            self._ambiguous_symbols = set(
                data.get("ambiguous_symbols", [])
            )
            self._last_mtime = os.path.getmtime(self._path)
            logger.info(
                "Coin mapping loaded: %d coins from %s",
                len(coins),
                self._path,
            )
        except Exception as exc:
            if fail_on_error:
                raise RuntimeError(
                    f"Failed to load coin mapping from {self._path}: {exc}"
                ) from exc
            logger.error(
                "Hot-reload of coin mapping failed, retaining previous "
                "mapping: %s",
                exc,
            )

    def check_reload(self) -> None:
        """Reload the mapping file if it has been modified."""
        try:
            mtime = os.path.getmtime(self._path)
            if mtime > self._last_mtime:
                logger.info("Coin mapping file changed, reloading.")
                self._load(fail_on_error=False)
        except OSError:
            logger.error(
                "Cannot stat coin mapping file: %s", self._path
            )

    @property
    def name_to_symbol(self) -> dict[str, str]:
        """Name (lowercase) → symbol mapping."""
        return self._name_to_symbol

    @property
    def symbol_to_name(self) -> dict[str, str]:
        """Symbol → name mapping."""
        return self._symbol_to_name

    @property
    def all_symbols(self) -> set[str]:
        """All known coin symbols."""
        return set(self._symbol_to_name.keys())

    @property
    def ambiguous_symbols(self) -> set[str]:
        """Symbols that are common English words."""
        return self._ambiguous_symbols

    def is_known_symbol(self, symbol: str) -> bool:
        """Check if a symbol exists in the mapping."""
        return symbol in self._symbol_to_name

    def get_symbol_for_name(self, name: str) -> Optional[str]:
        """Look up symbol by coin name (case-insensitive)."""
        return self._name_to_symbol.get(name.lower())

    def load_from_db_data(
        self,
        coins: dict[str, str],
        ambiguous_symbols: list[str],
    ) -> None:
        """Replace the current mapping with data loaded from the database.

        ``coins`` maps coin names to ticker symbols.  ``ambiguous_symbols``
        lists symbols that are common English words and require the full
        name to appear in the article to confirm a mention.
        """
        self._name_to_symbol = {
            n.lower(): s for n, s in coins.items()
        }
        self._symbol_to_name = {s: n for n, s in coins.items()}
        self._ambiguous_symbols = set(ambiguous_symbols)
        logger.info(
            "Coin mapping updated from DB: %d coins, %d ambiguous.",
            len(coins),
            len(ambiguous_symbols),
        )
