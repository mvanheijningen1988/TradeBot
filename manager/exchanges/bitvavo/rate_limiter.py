"""Bitvavo-specific rate limiter.

Bitvavo uses a weight-point system where each API call costs a certain
number of points. The budget resets every second. This module tracks
consumption and throttles requests to avoid hitting limits.

Rate limit weight points per action (from Bitvavo docs):
    ┌────────────────────────┬────────┐
    │ Action                 │ Points │
    ├────────────────────────┼────────┤
    │ getMarkets             │      1 │
    │ getBook                │      1 │
    │ getTrades              │      5 │
    │ getTickerPrice         │      1 │
    │ privateCreateOrder     │      1 │
    │ privateUpdateOrder     │      1 │
    │ privateGetOrder        │      1 │
    │ privateCancelOrder     │      1 │
    │ privateGetOrdersOpen   │ 5/100* │
    │ privateGetOrders       │      5 │
    │ privateCancelOrders    │ 25/100*│
    │ privateGetAccount      │      1 │
    │ privateGetBalance      │      5 │
    │ getServerTime          │      1 │
    └────────────────────────┴────────┘
    * with/without market parameter
"""

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

# Bitvavo allows 1000 weight points per second per IP.
DEFAULT_MAX_POINTS_PER_SECOND = 1000

# Safety margin: reserve 5 % headroom to avoid accidental overruns.
SAFETY_MARGIN = 0.95

# Per-action rate limit weight points (Bitvavo-specific).
RATE_LIMIT_WEIGHTS: dict[str, int] = {
    # Market data
    "getMarkets": 1,
    "getBook": 1,
    "getTrades": 5,
    "getTickerPrice": 1,
    "getTickerBook": 1,
    "getTicker24h": 1,
    "getCandles": 1,
    # Trading
    "privateCreateOrder": 1,
    "privateUpdateOrder": 1,
    "privateGetOrder": 1,
    "privateCancelOrder": 1,
    "privateGetOrdersOpen": 5,       # 5 with market, 100 without
    "privateGetOrdersOpen_all": 100,
    "privateGetOrders": 5,
    "privateCancelOrders": 25,       # 25 with market, 100 without
    "privateCancelOrders_all": 100,
    "privateGetTradeHistory": 5,
    # Account
    "privateGetAccount": 1,
    "privateGetBalance": 5,
    "privateGetMarketFees": 1,
    # Sync
    "getServerTime": 1,
    # Transfer
    "privateGetDepositData": 1,
    "privateGetDepositHistory": 5,
    "privateGetWithdrawalHistory": 5,
}


class BitvavoRateLimiter:
    """Sliding-window rate limiter for the Bitvavo exchange.

    Tracks weight-point consumption and pauses callers when the budget
    for the current second is exhausted.
    """

    def __init__(
        self,
        max_points: int = DEFAULT_MAX_POINTS_PER_SECOND,
    ) -> None:
        self._max_points = int(max_points * SAFETY_MARGIN)
        self._lock = asyncio.Lock()
        self._window_start: float = time.monotonic()
        self._points_used: int = 0

    def get_weight(self, action: str, has_market: bool = True) -> int:
        """Return the rate-limit weight for a given action.

        Args:
            action: The Bitvavo WebSocket action name.
            has_market: Whether the request includes a market parameter.
                        Some endpoints cost more without it.
        """
        if not has_market and f"{action}_all" in RATE_LIMIT_WEIGHTS:
            return RATE_LIMIT_WEIGHTS[f"{action}_all"]
        return RATE_LIMIT_WEIGHTS.get(action, 1)

    async def acquire(self, action: str, has_market: bool = True) -> None:
        """Wait until enough rate-limit budget is available, then consume it.

        Args:
            action: The Bitvavo WebSocket action name.
            has_market: Whether the request includes a market parameter.
        """
        weight = self.get_weight(action, has_market)

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._window_start

            # Reset window every second.
            if elapsed >= 1.0:
                self._window_start = now
                self._points_used = 0

            # If adding this request would exceed budget, wait until reset.
            if self._points_used + weight > self._max_points:
                wait_time = 1.0 - elapsed
                if wait_time > 0:
                    logger.debug(
                        "Rate limit: waiting %.3fs before %s (weight=%d, "
                        "used=%d/%d)",
                        wait_time,
                        action,
                        weight,
                        self._points_used,
                        self._max_points,
                    )
                    await asyncio.sleep(wait_time)
                self._window_start = time.monotonic()
                self._points_used = 0

            self._points_used += weight
            logger.debug(
                "Rate limit: consumed %d points for %s (%d/%d used)",
                weight,
                action,
                self._points_used,
                self._max_points,
            )

    @property
    def points_remaining(self) -> int:
        """Return the approximate number of points still available."""
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            return self._max_points
        return max(0, self._max_points - self._points_used)
