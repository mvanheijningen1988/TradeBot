"""Tests for the Bitvavo rate limiter."""

import asyncio
import time

import pytest

from manager.exchanges.bitvavo.rate_limiter import (
    RATE_LIMIT_WEIGHTS,
    BitvavoRateLimiter,
)


class TestRateLimitWeights:
    """Verify that all documented actions have weight entries."""

    def test_create_order_weight(self):
        assert RATE_LIMIT_WEIGHTS["privateCreateOrder"] == 1

    def test_cancel_order_weight(self):
        assert RATE_LIMIT_WEIGHTS["privateCancelOrder"] == 1

    def test_get_orders_weight(self):
        assert RATE_LIMIT_WEIGHTS["privateGetOrders"] == 5

    def test_get_open_orders_with_market(self):
        assert RATE_LIMIT_WEIGHTS["privateGetOrdersOpen"] == 5

    def test_get_open_orders_without_market(self):
        assert RATE_LIMIT_WEIGHTS["privateGetOrdersOpen_all"] == 100

    def test_cancel_orders_with_market(self):
        assert RATE_LIMIT_WEIGHTS["privateCancelOrders"] == 25

    def test_cancel_orders_without_market(self):
        assert RATE_LIMIT_WEIGHTS["privateCancelOrders_all"] == 100

    def test_get_balance_weight(self):
        assert RATE_LIMIT_WEIGHTS["privateGetBalance"] == 5

    def test_get_account_weight(self):
        assert RATE_LIMIT_WEIGHTS["privateGetAccount"] == 1

    def test_get_book_weight(self):
        assert RATE_LIMIT_WEIGHTS["getBook"] == 1

    def test_get_trades_weight(self):
        assert RATE_LIMIT_WEIGHTS["getTrades"] == 5

    def test_get_markets_weight(self):
        assert RATE_LIMIT_WEIGHTS["getMarkets"] == 1

    def test_get_ticker_price_weight(self):
        assert RATE_LIMIT_WEIGHTS["getTickerPrice"] == 1


class TestBitvavoRateLimiter:
    """Test the rate limiter behaviour."""

    @pytest.fixture
    def limiter(self):
        # Use a small budget for testing.
        return BitvavoRateLimiter(max_points=10)

    @pytest.mark.asyncio
    async def test_acquire_consumes_points(self, limiter):
        await limiter.acquire("privateCreateOrder")
        # 10 * 0.95 = 9 max, used 1 → 8 remaining.
        assert limiter.points_remaining == 8

    @pytest.mark.asyncio
    async def test_acquire_multiple(self, limiter):
        await limiter.acquire("privateGetOrders")  # 5 points
        assert limiter.points_remaining == 4

    @pytest.mark.asyncio
    async def test_get_weight_with_market(self, limiter):
        weight = limiter.get_weight("privateGetOrdersOpen", has_market=True)
        assert weight == 5

    @pytest.mark.asyncio
    async def test_get_weight_without_market(self, limiter):
        weight = limiter.get_weight("privateGetOrdersOpen", has_market=False)
        assert weight == 100

    @pytest.mark.asyncio
    async def test_get_weight_unknown_action(self, limiter):
        weight = limiter.get_weight("unknownAction")
        assert weight == 1  # defaults to 1

    @pytest.mark.asyncio
    async def test_points_remaining_resets_after_window(self, limiter):
        await limiter.acquire("privateGetOrders")  # 5 pts
        assert limiter.points_remaining == 4
        # Simulate window reset.
        limiter._window_start = time.monotonic() - 2.0
        assert limiter.points_remaining == 9  # full budget
