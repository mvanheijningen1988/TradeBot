"""Martingale trading strategy.

Buys a fixed amount of crypto and, when the price drops by a predefined
percentage, buys a larger amount (multiplied by a position multiplier)
to lower the average entry price.  When the price rebounds by the
take-profit percentage, sells the entire position for a profit.

Best for: recovering from dips and pullbacks.  Carries high risk in
one-sided bearish trends unless strict stop-loss limits are set.

Reference parameters (KuCoin guide):
    - Buy-in trigger: 1-5 % drop per step
    - Take-profit: ~1 %
    - Position multiplier: 1.1x - 1.3x for beginners
    - Max buy-ins: limits total exposure

Reference:
    https://www.kucoin.com/support/31130050642329
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional

from manager.exchanges.base import ExchangeClient
from manager.models import OrderSide, OrderType
from manager.strategies.base import Strategy, StrategyConfig, StrategyState

logger = logging.getLogger(__name__)


@dataclass
class MartingaleConfig(StrategyConfig):
    """Configuration for the Martingale strategy.

    Attributes:
        initial_amount_quote: Quote-currency amount for the first buy.
        buy_in_trigger_pct: Price drop percentage that triggers the next
                            buy-in (e.g. 2.0 for 2 %).
        take_profit_pct: Price rebound percentage from average entry at
                         which to sell (e.g. 1.0 for 1 %).
        position_multiplier: Factor by which each subsequent buy-in
                             increases (e.g. 1.2 for 20 % more).
        max_buy_ins: Maximum number of additional buy-ins (safety limit).
        stop_loss_pct: Optional stop-loss percentage from the average
                       entry price (e.g. 10.0 for -10 %).  0 = disabled.
    """

    initial_amount_quote: float = 0.0
    buy_in_trigger_pct: float = 2.0
    take_profit_pct: float = 1.0
    position_multiplier: float = 1.2
    max_buy_ins: int = 5
    stop_loss_pct: float = 0.0


class MartingaleStrategy(Strategy):
    """Martingale strategy implementation."""

    def __init__(
        self,
        config: MartingaleConfig,
        exchange: ExchangeClient,
    ) -> None:
        super().__init__(config, exchange)
        self._config: MartingaleConfig = config

        # Position tracking.
        self._total_base: Decimal = Decimal("0")
        self._total_quote_spent: Decimal = Decimal("0")
        self._avg_entry_price: Decimal = Decimal("0")
        self._buy_in_count: int = 0
        self._last_buy_price: Decimal = Decimal("0")

        # Cycle tracking.
        self._cycles_completed: int = 0
        self._total_profit: Decimal = Decimal("0")

        # Current sell order.
        self._sell_order_id: Optional[str] = None

    @staticmethod
    def name() -> str:
        return "martingale"

    @staticmethod
    def description() -> str:
        return (
            "Buys more on dips with increasing size to lower average "
            "entry, sells the full position on a small rebound."
        )

    @staticmethod
    def default_parameters() -> dict[str, Any]:
        return {
            "initial_amount_quote": 0.0,
            "buy_in_trigger_pct": 2.0,
            "take_profit_pct": 1.0,
            "position_multiplier": 1.2,
            "max_buy_ins": 5,
            "stop_loss_pct": 0.0,
            "budget_quote": 0.0,
        }

    async def start(self) -> None:
        """Execute the initial buy and enter the monitoring phase."""
        cfg = self._config
        if cfg.initial_amount_quote <= 0:
            raise ValueError("initial_amount_quote must be > 0.")
        if cfg.buy_in_trigger_pct <= 0:
            raise ValueError("buy_in_trigger_pct must be > 0.")
        if cfg.take_profit_pct <= 0:
            raise ValueError("take_profit_pct must be > 0.")

        self._state = StrategyState.RUNNING

        # Place initial market buy.
        await self._execute_buy(Decimal(str(cfg.initial_amount_quote)))
        logger.info(
            "Martingale started: market=%s initial=%s trigger=%s%% "
            "tp=%s%% multiplier=%s max_buy_ins=%d",
            cfg.market,
            cfg.initial_amount_quote,
            cfg.buy_in_trigger_pct,
            cfg.take_profit_pct,
            cfg.position_multiplier,
            cfg.max_buy_ins,
        )

    async def stop(self) -> None:
        """Cancel any pending sell order and stop."""
        self._state = StrategyState.STOPPED
        if self._sell_order_id:
            try:
                await self._exchange.cancel_order(
                    market=self._config.market,
                    order_id=self._sell_order_id,
                    operator_id=self._config.operator_id,
                )
            except Exception:
                logger.exception("Failed to cancel sell order on stop.")
            self._sell_order_id = None
        logger.info("Martingale strategy stopped.")

    async def on_tick(self, price: str) -> None:
        """Check if price triggers a new buy-in or stop-loss."""
        if self._state != StrategyState.RUNNING:
            return
        if self._total_base <= 0:
            return

        current_price = Decimal(price)
        cfg = self._config

        # Check stop-loss.
        if cfg.stop_loss_pct > 0 and self._avg_entry_price > 0:
            stop_price = self._avg_entry_price * (
                1 - Decimal(str(cfg.stop_loss_pct)) / 100
            )
            if current_price <= stop_price:
                logger.warning(
                    "Martingale stop-loss triggered at %s (avg_entry=%s, "
                    "stop=%s)",
                    current_price,
                    self._avg_entry_price,
                    stop_price,
                )
                await self._execute_sell_all(current_price)
                return

        # Check buy-in trigger.
        if self._last_buy_price > 0:
            trigger_price = self._last_buy_price * (
                1 - Decimal(str(cfg.buy_in_trigger_pct)) / 100
            )
            if (
                current_price <= trigger_price
                and self._buy_in_count < cfg.max_buy_ins
            ):
                # Budget check.
                next_amount = Decimal(str(cfg.initial_amount_quote)) * (
                    Decimal(str(cfg.position_multiplier))
                    ** self._buy_in_count
                )
                remaining = (
                    Decimal(str(cfg.budget_quote)) - self._total_quote_spent
                )
                if next_amount <= remaining:
                    logger.info(
                        "Martingale buy-in #%d triggered at %s (trigger=%s)",
                        self._buy_in_count + 1,
                        current_price,
                        trigger_price,
                    )
                    await self._execute_buy(next_amount)
                else:
                    logger.warning(
                        "Martingale budget insufficient for buy-in #%d "
                        "(need %s, have %s).",
                        self._buy_in_count + 1,
                        next_amount,
                        remaining,
                    )

        # Check take-profit: place/update sell order.
        if self._avg_entry_price > 0 and self._total_base > 0:
            tp_price = self._avg_entry_price * (
                1 + Decimal(str(cfg.take_profit_pct)) / 100
            )
            if current_price >= tp_price and self._sell_order_id is None:
                await self._place_take_profit(tp_price)

    async def on_order_filled(self, order_id: str) -> None:
        """Handle fill events (mainly the take-profit sell)."""
        if order_id == self._sell_order_id:
            # Take profit hit — cycle complete.
            profit = (
                self._total_base * self._avg_entry_price
                * Decimal(str(self._config.take_profit_pct)) / 100
            )
            self._total_profit += profit
            self._cycles_completed += 1
            logger.info(
                "Martingale cycle #%d complete. Profit: ~%s. "
                "Total profit: %s",
                self._cycles_completed,
                profit,
                self._total_profit,
            )

            # Reset position for next cycle.
            self._total_base = Decimal("0")
            self._total_quote_spent = Decimal("0")
            self._avg_entry_price = Decimal("0")
            self._buy_in_count = 0
            self._last_buy_price = Decimal("0")
            self._sell_order_id = None

            # Start next cycle if budget allows.
            remaining = (
                Decimal(str(self._config.budget_quote))
                - self._total_quote_spent
            )
            initial = Decimal(str(self._config.initial_amount_quote))
            if remaining >= initial:
                await self._execute_buy(initial)
            else:
                logger.info("Martingale budget exhausted after cycle.")
                self._state = StrategyState.STOPPED

    async def _execute_buy(self, amount_quote: Decimal) -> None:
        """Place a market buy and update position tracking."""
        cfg = self._config
        try:
            order = await self._exchange.create_order(
                market=cfg.market,
                side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                operator_id=cfg.operator_id,
                amount_quote=str(amount_quote),
            )

            filled = Decimal(order.filled_amount or "0")
            filled_quote = Decimal(order.filled_amount_quote or str(amount_quote))

            self._total_base += filled
            self._total_quote_spent += filled_quote
            self._buy_in_count += 1

            if self._total_base > 0:
                self._avg_entry_price = (
                    self._total_quote_spent / self._total_base
                )

            # Use the fill price as last buy price.
            if filled > 0:
                self._last_buy_price = filled_quote / filled

            logger.info(
                "Martingale buy #%d: spent %s, got %s base, "
                "avg_entry=%s",
                self._buy_in_count,
                filled_quote,
                filled,
                self._avg_entry_price,
            )

            # Cancel existing sell order if we need to recalculate TP.
            if self._sell_order_id:
                try:
                    await self._exchange.cancel_order(
                        market=cfg.market,
                        order_id=self._sell_order_id,
                        operator_id=cfg.operator_id,
                    )
                except Exception:
                    logger.debug("Could not cancel stale sell order.")
                self._sell_order_id = None

        except Exception:
            logger.exception("Martingale buy failed.")

    async def _execute_sell_all(self, current_price: Decimal) -> None:
        """Market-sell the entire position (stop-loss)."""
        cfg = self._config
        if self._total_base <= 0:
            return

        try:
            if self._sell_order_id:
                try:
                    await self._exchange.cancel_order(
                        market=cfg.market,
                        order_id=self._sell_order_id,
                        operator_id=cfg.operator_id,
                    )
                except Exception:
                    pass
                self._sell_order_id = None

            order = await self._exchange.create_order(
                market=cfg.market,
                side=OrderSide.SELL,
                order_type=OrderType.MARKET,
                operator_id=cfg.operator_id,
                amount=str(self._total_base),
            )

            received = Decimal(order.filled_amount_quote or "0")
            loss = self._total_quote_spent - received
            self._total_profit -= loss
            logger.warning(
                "Martingale stop-loss executed. Lost %s. "
                "Total profit: %s",
                loss,
                self._total_profit,
            )

            # Reset position.
            self._total_base = Decimal("0")
            self._total_quote_spent = Decimal("0")
            self._avg_entry_price = Decimal("0")
            self._buy_in_count = 0
            self._last_buy_price = Decimal("0")
            self._state = StrategyState.STOPPED

        except Exception:
            logger.exception("Martingale stop-loss sell failed.")
            self._state = StrategyState.ERROR

    async def _place_take_profit(self, tp_price: Decimal) -> None:
        """Place a limit sell order at the take-profit price."""
        cfg = self._config
        try:
            order = await self._exchange.create_order(
                market=cfg.market,
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                operator_id=cfg.operator_id,
                amount=str(self._total_base),
                price=str(tp_price),
            )
            self._sell_order_id = order.order_id
            logger.info(
                "Martingale take-profit order placed at %s for %s base.",
                tp_price,
                self._total_base,
            )
        except Exception:
            logger.exception("Failed to place take-profit order.")

    def get_status(self) -> dict[str, Any]:
        return {
            "strategy": self.name(),
            "state": self._state.value,
            "market": self._config.market,
            "buy_in_count": self._buy_in_count,
            "max_buy_ins": self._config.max_buy_ins,
            "total_base": str(self._total_base),
            "total_quote_spent": str(self._total_quote_spent),
            "avg_entry_price": str(self._avg_entry_price),
            "last_buy_price": str(self._last_buy_price),
            "cycles_completed": self._cycles_completed,
            "total_profit": str(self._total_profit),
            "sell_order_id": self._sell_order_id,
            "take_profit_pct": self._config.take_profit_pct,
            "buy_in_trigger_pct": self._config.buy_in_trigger_pct,
            "position_multiplier": self._config.position_multiplier,
            "stop_loss_pct": self._config.stop_loss_pct,
        }
