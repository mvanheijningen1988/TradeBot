"""RSI model for short/long horizon signal enrichment.

Computes RSI from recent exchange trades using the standard formula:
RSI = 100 - (100 / (1 + RS)), where RS = avg_gain / avg_loss.
"""

import logging
import time
from typing import Optional

from manager.exchanges.bitvavo.client import BitvavoClient

logger = logging.getLogger(__name__)

_SHORT_PERIOD = 9
_LONG_PERIOD = 14
_MAX_TRADES = 250
_MARKET_CACHE_TTL = 900


class RSIModel:
    """Fetches market prices and computes RSI values per coin."""

    def __init__(self, db=None) -> None:
        self._db = db
        self._market_cache: dict[str, str] = {}
        self._market_cache_ts: float = 0.0

    async def analyse(self, coins: list[str]) -> dict[str, dict]:
        """Return RSI context per coin symbol."""
        if not self._db or not coins:
            return {}

        exchange = await self._get_primary_exchange()
        if not exchange:
            return {}

        client = BitvavoClient(
            api_key=exchange["api_key"],
            api_secret=exchange["api_secret"],
        )

        try:
            await client.connect()
            await client.authenticate()
            market_map = await self._get_market_map(client)
            return await self._analyse_coins(client, set(coins), market_map)
        finally:
            await client.disconnect()

    async def _analyse_coins(
        self,
        client: BitvavoClient,
        coins: set[str],
        market_map: dict[str, str],
    ) -> dict[str, dict]:
        """Compute RSI context for all requested coins."""
        result: dict[str, dict] = {}
        for coin in coins:
            context = await self._analyse_coin(client, coin, market_map)
            if context:
                result[coin] = context
        return result

    async def _analyse_coin(
        self,
        client: BitvavoClient,
        coin: str,
        market_map: dict[str, str],
    ) -> Optional[dict]:
        """Compute RSI context for a single coin symbol."""
        market = market_map.get(coin)
        if not market:
            return None

        try:
            trades = await client.get_trades(market=market, limit=_MAX_TRADES)
        except Exception as exc:
            logger.warning(
                "Failed to fetch trades for %s (%s): %s",
                coin,
                market,
                exc,
            )
            return None

        if not trades:
            return None

        prices = [
            float(t.price)
            for t in sorted(trades, key=lambda t: t.timestamp)
        ]
        short_rsi = self._compute_rsi(prices, _SHORT_PERIOD)
        long_rsi = self._compute_rsi(prices, _LONG_PERIOD)
        if short_rsi is None and long_rsi is None:
            return None

        state_source = short_rsi if short_rsi is not None else long_rsi
        return {
            "market": market,
            "rsi_short": (
                round(short_rsi, 2)
                if short_rsi is not None
                else None
            ),
            "rsi_long": round(long_rsi, 2) if long_rsi is not None else None,
            "rsi_state": self._classify_rsi(state_source),
        }

    async def _get_primary_exchange(self) -> Optional[dict]:
        rows = await self._db.fetch_all(
            "SELECT * FROM exchanges WHERE enabled = 1 ORDER BY id LIMIT 1"
        )
        if not rows:
            return None
        return dict(rows[0])

    async def _get_market_map(
        self,
        client: BitvavoClient,
    ) -> dict[str, str]:
        now = time.time()
        if (
            self._market_cache
            and (now - self._market_cache_ts) < _MARKET_CACHE_TTL
        ):
            return self._market_cache

        markets = await client.get_markets()
        priority = {"EUR": 3, "USDT": 2, "USD": 1}
        selected: dict[str, tuple[int, str]] = {}

        for market in markets:
            if market.status not in ("trading", "active", ""):
                continue

            rank = priority.get(market.quote, 0)
            if rank == 0:
                continue

            current = selected.get(market.base)
            if current is None or rank > current[0]:
                selected[market.base] = (rank, market.market)

        self._market_cache = {base: m for base, (_, m) in selected.items()}
        self._market_cache_ts = now
        return self._market_cache

    @staticmethod
    def _compute_rsi(prices: list[float], period: int) -> Optional[float]:
        if len(prices) < period + 1:
            return None

        deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        recent = deltas[-period:]
        gains = [d for d in recent if d > 0]
        losses = [-d for d in recent if d < 0]

        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period

        if avg_loss == 0:
            return 100.0

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def _classify_rsi(rsi_value: float) -> str:
        if rsi_value > 70:
            return "overbought"
        if rsi_value < 30:
            return "oversold"
        return "neutral"
