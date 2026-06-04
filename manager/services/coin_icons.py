"""Coin icon service.

Fetches and caches the coin_map.json from the cryptocurrency-icons
repository so the UI can display recognisable icons in dropdowns.
"""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

COIN_MAP_URL = (
    "https://raw.githubusercontent.com/ErikThiart/"
    "cryptocurrency-icons/refs/heads/master/coin_map.json"
)


class CoinIconService:
    """Loads and serves cryptocurrency icon mappings."""

    def __init__(self) -> None:
        self._icons: dict[str, dict[str, Any]] = {}
        self._loaded = False

    async def load(self) -> None:
        """Fetch coin_map.json and index by symbol."""
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(COIN_MAP_URL)
                resp.raise_for_status()
                data = resp.json()

            for entry in data:
                symbol = entry.get("symbol", "").upper()
                if symbol:
                    self._icons[symbol] = entry
            self._loaded = True
            logger.info("Loaded %d coin icons.", len(self._icons))
        except Exception:
            logger.exception("Failed to load coin icons.")

    def get_icon(self, symbol: str) -> Optional[dict]:
        """Return icon data for a given asset symbol."""
        return self._icons.get(symbol.upper())

    def get_all(self) -> dict[str, dict]:
        """Return the full icon mapping."""
        return self._icons

    @property
    def loaded(self) -> bool:
        """Return whether coin icon mappings have been loaded in memory."""
        return self._loaded
