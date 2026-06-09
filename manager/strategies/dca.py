"""Dollar Cost Averaging (DCA) strategy.

Automates recurring purchases of a fixed quote-currency amount of a
chosen crypto at regular intervals (e.g. daily, weekly) regardless of
price.

Best for: long-term accumulation, reducing the impact of short-term
volatility, and building a portfolio without timing the market.
"""

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from manager.exchanges.base import ExchangeClient
from manager.models import OrderSide, OrderType
from manager.strategies.base import Strategy, StrategyConfig, StrategyState

logger = logging.getLogger(__name__)


class DCAInterval:
    """Supported DCA intervals in seconds."""

    HOURLY = 3600
    DAILY = 86400
    WEEKLY = 604800
    BIWEEKLY = 1209600
    MONTHLY = 2592000  # 30 days approx


# Map friendly names to seconds.
INTERVAL_MAP: dict[str, int] = {
    "hourly": DCAInterval.HOURLY,
    "daily": DCAInterval.DAILY,
    "weekly": DCAInterval.WEEKLY,
    "biweekly": DCAInterval.BIWEEKLY,
    "monthly": DCAInterval.MONTHLY,
}


@dataclass
class DCAConfig(StrategyConfig):
    """Configuration for the DCA strategy.

    Attributes:
        amount_per_order: Fixed quote-currency amount per buy.
        interval: Buying interval name ('hourly', 'daily', 'weekly',
                  'biweekly', 'monthly').
        max_orders: Maximum number of buy orders to execute (0 = unlimited).
    """

    amount_per_order: float = 0.0
    interval: str = "daily"
    max_orders: int = 0


class DCAStrategy(Strategy):
    """Dollar Cost Averaging strategy implementation."""

    def __init__(
        self,
        config: DCAConfig,
        exchange: ExchangeClient,
    ) -> None:
        super().__init__(config, exchange)
        self._config: DCAConfig = config
        self._task: asyncio.Task | None = None
        self._orders_placed: int = 0
        self._total_spent: Decimal = Decimal("0")
        self._total_acquired: Decimal = Decimal("0")
        self._quote_balance: Decimal = Decimal(str(config.budget_quote))
        self._base_balance: Decimal = Decimal("0")
        self._last_buy_time: float = 0.0

    @staticmethod
    def name() -> str:
        """Return the registry key for this strategy."""
        return "dca"

    @staticmethod
    def description() -> str:
        """Return a human-readable summary of the DCA behavior."""
        return (
            "Automates recurring fixed-amount buys at regular intervals "
            "to dollar-cost average into a position."
        )

    @staticmethod
    def default_parameters() -> dict[str, Any]:
        """Return default configurable parameters for new DCA bots."""
        return {
            "amount_per_order": 0.0,
            "interval": "daily",
            "max_orders": 0,
            "budget_quote": 0.0,
        }

    async def start(self) -> None:
        """Start the DCA loop."""
        cfg = self._config
        if cfg.amount_per_order <= 0:
            raise ValueError("amount_per_order must be > 0.")
        if cfg.interval not in INTERVAL_MAP:
            raise ValueError(
                f"Invalid interval '{cfg.interval}'. "
                f"Choose from: {', '.join(INTERVAL_MAP.keys())}"
            )

        self._state = StrategyState.RUNNING
        await self._report_budget(
            balance=str(self._quote_balance),
            price="0",
        )
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "DCA strategy started: market=%s amount=%s interval=%s",
            cfg.market,
            cfg.amount_per_order,
            cfg.interval,
        )

    async def stop(self) -> None:
        """Stop the DCA loop."""
        self._state = StrategyState.STOPPED
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        logger.info("DCA strategy stopped.")

    async def _run_loop(self) -> None:
        """Periodically place market buy orders."""
        interval_secs = INTERVAL_MAP[self._config.interval]

        try:
            while self._state == StrategyState.RUNNING:
                if (
                    self._config.max_orders > 0
                    and self._orders_placed >= self._config.max_orders
                ):
                    logger.info(
                        "DCA reached max_orders=%d, stopping.",
                        self._config.max_orders,
                    )
                    self._state = StrategyState.STOPPED
                    break

                # Check remaining budget.
                budget = Decimal(str(self._config.budget_quote))
                remaining = budget - self._total_spent
                if remaining < Decimal(str(self._config.amount_per_order)):
                    logger.info("DCA budget exhausted, stopping.")
                    self._state = StrategyState.STOPPED
                    break

                await self._execute_buy()
                await asyncio.sleep(interval_secs)

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("DCA loop error.")
            self._state = StrategyState.ERROR

    async def _execute_buy(self) -> None:
        """Place a single market buy order for the configured amount."""
        cfg = self._config
        amount_quote = str(cfg.amount_per_order)

        try:
            client_order_id = self._next_client_order_id(
                f"buy:{self._orders_placed + 1}"
            )
            order = await self._exchange.create_order(
                market=cfg.market,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                operator_id=cfg.operator_id,
                amount_quote=amount_quote,
                client_order_id=client_order_id,
            )
            self._orders_placed += 1
            self._total_spent += Decimal(amount_quote)
            quote_spent = Decimal(order.filled_amount_quote or amount_quote)
            base_received = Decimal(order.filled_amount or "0")

            fee_paid = Decimal(order.fee_paid or "0")
            fee_currency = (order.fee_currency or "").upper()
            quote_symbol = cfg.market.split("-")[1].upper()
            base_symbol = cfg.market.split("-")[0].upper()

            if fee_paid > 0 and fee_currency == quote_symbol:
                quote_spent += fee_paid
            if fee_paid > 0 and fee_currency == base_symbol:
                base_received = max(Decimal("0"), base_received - fee_paid)

            self._quote_balance = max(
                Decimal("0"),
                self._quote_balance - quote_spent,
            )
            self._base_balance += base_received

            if order.filled_amount:
                self._total_acquired += Decimal(order.filled_amount)
            self._last_buy_time = time.time()

            logger.info(
                "DCA buy #%d: spent %s %s, acquired %s (total: %s)",
                self._orders_placed,
                amount_quote,
                cfg.market.split("-")[1],
                order.filled_amount,
                self._total_acquired,
            )
        except Exception:
            logger.exception("DCA buy order failed.")

    async def on_tick(self, price: str) -> None:
        """Report mark-to-market budget value for trend graphs."""
        if self._state != StrategyState.RUNNING:
            return
        current_price = Decimal(price)
        equity = self._quote_balance + (self._base_balance * current_price)
        await self._report_budget(
            balance=str(equity),
            price=str(current_price),
        )

    async def on_order_filled(self, order_id: str) -> None:
        """No-op — DCA uses market orders which fill immediately."""

    def get_status(self) -> dict[str, Any]:
        """Return runtime metrics for monitoring and UI dashboards."""
        avg_price = Decimal("0")
        if self._total_acquired > 0:
            avg_price = self._total_spent / self._total_acquired

        return {
            "strategy": self.name(),
            "state": self._state.value,
            "market": self._config.market,
            "interval": self._config.interval,
            "amount_per_order": self._config.amount_per_order,
            "orders_placed": self._orders_placed,
            "total_spent": str(self._total_spent),
            "total_acquired": str(self._total_acquired),
            "average_price": str(avg_price),
            "last_buy_time": self._last_buy_time,
        }
