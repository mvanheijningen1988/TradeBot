"""Spot & Futures Grid Trading strategy.

Places buy orders below the current price and sell orders above it at
fixed intervals to capture profit from price oscillations within a
defined range.

Best for: volatile, sideways-moving markets.

Reference:
    https://www.kucoin.com/support/31130050642329
"""

import asyncio
import logging
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional

from manager.exchanges.base import ExchangeClient
from manager.models import OrderSide, OrderType, TimeInForce
from manager.strategies.base import Strategy, StrategyConfig, StrategyState

logger = logging.getLogger(__name__)


@dataclass
class GridConfig(StrategyConfig):
    """Configuration for the Grid Trading strategy.

    Attributes:
        upper_price: Upper bound of the grid range.
        lower_price: Lower bound of the grid range.
        num_grids: Number of grid levels (determines grid spacing).
        budget_quote: Total quote-currency budget to allocate.
    """

    upper_price: float = 0.0
    lower_price: float = 0.0
    num_grids: int = 10


class GridStrategy(Strategy):
    """Grid trading strategy implementation.

    Grid Profit = Profit Rate per Grid Interval x Investment per Grid x
                  No. of Trades Completed

    Grid Spread = (Upper Price - Lower Price) / Number of Grids
    """

    def __init__(
        self,
        config: GridConfig,
        exchange: ExchangeClient,
    ) -> None:
        super().__init__(config, exchange)
        self._config: GridConfig = config
        self._grid_prices: list[Decimal] = []
        self._order_ids: dict[str, str] = {}  # price_str -> order_id
        self._filled_buys: int = 0
        self._filled_sells: int = 0
        self._total_profit: Decimal = Decimal("0")

    @staticmethod
    def name() -> str:
        return "grid_trading"

    @staticmethod
    def description() -> str:
        return (
            "Places buy orders below and sell orders above the current "
            "price at fixed intervals to arbitrage within a price range."
        )

    @staticmethod
    def default_parameters() -> dict[str, Any]:
        return {
            "upper_price": 0.0,
            "lower_price": 0.0,
            "num_grids": 10,
            "budget_quote": 0.0,
        }

    async def start(self) -> None:
        """Calculate grid levels and place initial orders."""
        cfg = self._config
        if cfg.upper_price <= cfg.lower_price:
            raise ValueError("upper_price must be greater than lower_price.")
        if cfg.num_grids < 2:
            raise ValueError("num_grids must be at least 2.")

        upper = Decimal(str(cfg.upper_price))
        lower = Decimal(str(cfg.lower_price))
        num = cfg.num_grids

        # Build grid price levels (inclusive of boundaries).
        grid_spread = (upper - lower) / num
        self._grid_prices = [
            lower + grid_spread * i for i in range(num + 1)
        ]

        # Get the current price to decide which levels are buys/sells.
        ticker = await self._exchange.get_ticker_price(cfg.market)
        current_price = Decimal(ticker.price)

        budget = Decimal(str(cfg.budget_quote))
        investment_per_grid = budget / num

        logger.info(
            "Grid strategy starting: market=%s range=[%s-%s] grids=%d "
            "spread=%s investment_per_grid=%s",
            cfg.market,
            lower,
            upper,
            num,
            grid_spread,
            investment_per_grid,
        )

        self._state = StrategyState.RUNNING

        # Place buy orders below current price, sell orders above.
        for grid_price in self._grid_prices:
            if grid_price >= current_price:
                # Place sell limit order (need base asset).
                amount = (investment_per_grid / grid_price).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )
                if amount <= 0:
                    continue
                try:
                    order = await self._exchange.create_order(
                        market=cfg.market,
                        side=OrderSide.SELL,
                        order_type=OrderType.LIMIT,
                        operator_id=cfg.operator_id,
                        amount=str(amount),
                        price=str(grid_price),
                        post_only=True,
                    )
                    self._order_ids[str(grid_price)] = order.order_id
                except Exception:
                    logger.exception(
                        "Failed to place sell order at %s", grid_price
                    )
            else:
                # Place buy limit order.
                amount = (investment_per_grid / grid_price).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )
                if amount <= 0:
                    continue
                try:
                    order = await self._exchange.create_order(
                        market=cfg.market,
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        operator_id=cfg.operator_id,
                        amount=str(amount),
                        price=str(grid_price),
                        post_only=True,
                    )
                    self._order_ids[str(grid_price)] = order.order_id
                except Exception:
                    logger.exception(
                        "Failed to place buy order at %s", grid_price
                    )

        logger.info(
            "Grid strategy placed %d orders.", len(self._order_ids)
        )

    async def stop(self) -> None:
        """Cancel all open grid orders."""
        self._state = StrategyState.STOPPED
        cfg = self._config
        for price_str, order_id in list(self._order_ids.items()):
            try:
                await self._exchange.cancel_order(
                    market=cfg.market,
                    order_id=order_id,
                    operator_id=cfg.operator_id,
                )
            except Exception:
                logger.exception(
                    "Failed to cancel order %s at price %s",
                    order_id,
                    price_str,
                )
        self._order_ids.clear()
        logger.info("Grid strategy stopped and orders cancelled.")

    async def on_tick(self, price: str) -> None:
        """No-op for grid strategy — grid orders are passive limit orders."""

    async def on_order_filled(self, order_id: str) -> None:
        """When a buy fills, place a sell one grid level up and vice versa."""
        if self._state != StrategyState.RUNNING:
            return

        cfg = self._config
        # Find the grid level for this order.
        filled_price_str: Optional[str] = None
        for p_str, oid in self._order_ids.items():
            if oid == order_id:
                filled_price_str = p_str
                break

        if filled_price_str is None:
            return

        self._order_ids.pop(filled_price_str, None)
        filled_price = Decimal(filled_price_str)

        # Determine the index in the grid.
        try:
            idx = self._grid_prices.index(filled_price)
        except ValueError:
            return

        budget = Decimal(str(cfg.budget_quote))
        investment_per_grid = budget / cfg.num_grids

        # Determine current price to know if this was a buy or sell fill.
        ticker = await self._exchange.get_ticker_price(cfg.market)
        current_price = Decimal(ticker.price)

        if current_price > filled_price:
            # Buy was filled → place sell one level up.
            self._filled_buys += 1
            if idx + 1 < len(self._grid_prices):
                sell_price = self._grid_prices[idx + 1]
                amount = (investment_per_grid / sell_price).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )
                grid_profit = (sell_price - filled_price) * amount
                self._total_profit += grid_profit
                if amount > 0:
                    try:
                        order = await self._exchange.create_order(
                            market=cfg.market,
                            side=OrderSide.SELL,
                            order_type=OrderType.LIMIT,
                            operator_id=cfg.operator_id,
                            amount=str(amount),
                            price=str(sell_price),
                            post_only=True,
                        )
                        self._order_ids[str(sell_price)] = order.order_id
                    except Exception:
                        logger.exception(
                            "Failed to place counter sell at %s", sell_price
                        )
        else:
            # Sell was filled → place buy one level down.
            self._filled_sells += 1
            if idx - 1 >= 0:
                buy_price = self._grid_prices[idx - 1]
                amount = (investment_per_grid / buy_price).quantize(
                    Decimal("0.00000001"), rounding=ROUND_DOWN
                )
                if amount > 0:
                    try:
                        order = await self._exchange.create_order(
                            market=cfg.market,
                            side=OrderSide.BUY,
                            order_type=OrderType.LIMIT,
                            operator_id=cfg.operator_id,
                            amount=str(amount),
                            price=str(buy_price),
                            post_only=True,
                        )
                        self._order_ids[str(buy_price)] = order.order_id
                    except Exception:
                        logger.exception(
                            "Failed to place counter buy at %s", buy_price
                        )

    def get_status(self) -> dict[str, Any]:
        return {
            "strategy": self.name(),
            "state": self._state.value,
            "market": self._config.market,
            "upper_price": self._config.upper_price,
            "lower_price": self._config.lower_price,
            "num_grids": self._config.num_grids,
            "grid_prices": [str(p) for p in self._grid_prices],
            "active_orders": len(self._order_ids),
            "filled_buys": self._filled_buys,
            "filled_sells": self._filled_sells,
            "total_profit": str(self._total_profit),
        }
