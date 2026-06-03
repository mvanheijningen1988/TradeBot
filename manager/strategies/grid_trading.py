"""Spot & Futures Grid Trading strategy.

Places buy orders below the current price and sell orders above it at
fixed intervals to capture profit from price oscillations within a
defined range.

Best for: volatile, sideways-moving markets.

Reference:
    https://www.kucoin.com/support/31130050642329
"""

import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Optional

from manager.exchanges.base import ExchangeClient
from manager.models import OrderSide, OrderStatus, OrderType
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

    Builds N+1 price levels from *lower* to *upper*.
    - **Buy levels**: levels 0 … N-1 (lower → upper − spread)
    - **Sell levels**: levels 1 … N   (lower + spread → upper)

    When a buy at level *i* fills  → counter sell at level *i + 1*.
    When a sell at level *i* fills → counter buy  at level *i − 1*.

    Grid Spread = (Upper Price − Lower Price) / Number of Grids
    """

    def __init__(
        self,
        config: GridConfig,
        exchange: ExchangeClient,
    ) -> None:
        super().__init__(config, exchange)
        self._config: GridConfig = config
        self._grid_prices: list[Decimal] = []
        self._buy_orders: dict[str, str] = {}   # price_str → order_id
        self._sell_orders: dict[str, str] = {}  # price_str → order_id
        self._filled_buys: int = 0
        self._filled_sells: int = 0
        self._total_profit: Decimal = Decimal("0")
        self._tick_count: int = 0

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

    # ── helpers ──────────────────────────────────────────────────

    def _all_orders(self) -> list[tuple[str, str]]:
        """Return (price_str, order_id) for every tracked order."""
        items: list[tuple[str, str]] = []
        items.extend(self._buy_orders.items())
        items.extend(self._sell_orders.items())
        return items

    async def _place_order(
        self,
        cfg: GridConfig,
        side: OrderSide,
        price: Decimal,
        amount: Decimal,
    ) -> bool:
        """Place a single limit order and track it.

        Returns:
            True if placement succeeded.
        """
        try:
            order = await self._exchange.create_order(
                market=cfg.market,
                side=side,
                order_type=OrderType.LIMIT,
                operator_id=cfg.operator_id,
                amount=str(amount),
                price=str(price),
                post_only=True,
            )
            price_str = str(price)
            if side == OrderSide.BUY:
                self._buy_orders[price_str] = order.order_id
            else:
                self._sell_orders[price_str] = order.order_id
            await self._report_order(
                exchange_order_id=order.order_id,
                market=cfg.market,
                side=side.value,
                order_type="limit",
                status="new",
                amount=str(amount),
                price=price_str,
            )
            logger.debug(
                "Placed %s %s @ %s (id=%s)",
                side.value, amount, price, order.order_id,
            )
            return True
        except Exception as exc:
            err = f"Failed to place {side.value.upper()} @ {price}: {exc}"
            logger.exception(err)
            await self._log(err, "ERROR")
            return False

    # ── lifecycle ────────────────────────────────────────────────

    async def start(self) -> None:
        """Calculate grid levels and place initial orders.

        Grid layout for lower=1, upper=2, num_grids=10:
            levels: 1.0, 1.1, 1.2, …, 1.9, 2.0   (11 price points)
            buy  levels: 1.0 … 1.9  (indices 0-9)
            sell levels: 1.1 … 2.0  (indices 1-10)

        On restart the strategy syncs open orders from the exchange
        (matched by operator_id) and only places orders at levels
        that don't already have one.
        """
        cfg = self._config
        if cfg.upper_price <= cfg.lower_price:
            raise ValueError("upper_price must be greater than lower_price.")
        if cfg.num_grids < 2:
            raise ValueError("num_grids must be at least 2.")

        upper = Decimal(str(cfg.upper_price))
        lower = Decimal(str(cfg.lower_price))
        num = cfg.num_grids

        # Build N+1 price points (inclusive of boundaries).
        grid_spread = (upper - lower) / num
        self._grid_prices = [
            lower + grid_spread * i for i in range(num + 1)
        ]

        # ── Sync existing open orders from the exchange ─────────
        await self._sync_exchange_orders(cfg, upper, lower)

        # Current price decides initial buy / sell placement.
        ticker = await self._exchange.get_ticker_price(cfg.market)
        current_price = Decimal(ticker.price)

        budget = Decimal(str(cfg.budget_quote))
        investment_per_grid = budget / num

        self._state = StrategyState.RUNNING

        existing = len(self._buy_orders) + len(self._sell_orders)
        if existing:
            msg = (
                f"Grid resuming: {existing} existing orders synced "
                f"({len(self._buy_orders)} buys, "
                f"{len(self._sell_orders)} sells)"
            )
        else:
            msg = (
                f"Grid starting: {cfg.market} range=[{lower}-{upper}] "
                f"grids={num} spread={grid_spread} "
                f"budget/grid={investment_per_grid} current={current_price}"
            )
        logger.info(msg)
        await self._log(msg)

        buy_count = 0

        # ── Place buy orders at buy-levels below current price ──
        for price in self._grid_prices[:-1]:          # levels 0 … N-1
            price_str = str(price)
            if price >= current_price:
                continue
            if price_str in self._buy_orders:
                continue
            if self._buy_blocked_by_sell_above(price):
                continue
            amount = (investment_per_grid / price).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN,
            )
            if amount <= 0:
                continue
            if await self._place_order(cfg, OrderSide.BUY, price, amount):
                buy_count += 1

        # ── Sell orders are only placed as counter-orders ───────
        # On a fresh start the bot holds no base asset, so placing
        # sell orders would fail (error 216).  Sells are created
        # automatically when a buy fill triggers on_order_filled().
        #
        # On restart, existing sell orders are already synced from
        # the exchange and tracked in _sell_orders — nothing extra
        # to place.

        msg = (
            f"Grid placed {buy_count} buy orders"
        )
        logger.info(msg)
        await self._log(msg)

    async def stop(self) -> None:
        """Cancel all open grid orders."""
        self._state = StrategyState.STOPPED
        cfg = self._config
        cancelled = 0
        for price_str, order_id in self._all_orders():
            try:
                await self._exchange.cancel_order(
                    market=cfg.market,
                    order_id=order_id,
                    operator_id=cfg.operator_id,
                )
                await self._report_order(
                    exchange_order_id=order_id,
                    market=cfg.market,
                    side="",
                    order_type="limit",
                    status="cancelled",
                )
                cancelled += 1
            except Exception:
                logger.exception(
                    "Failed to cancel order %s at price %s",
                    order_id,
                    price_str,
                )
        self._buy_orders.clear()
        self._sell_orders.clear()
        msg = f"Grid stopped, cancelled {cancelled} orders."
        logger.info(msg)
        await self._log(msg)

    async def on_tick(self, price: str) -> None:
        """Reconcile order state with the exchange and fill empty grid levels.

        Every 6th tick (~30 s) fetches open orders to detect fills and
        cancellations.  Then checks all buy-levels below the current
        price and places orders at any uncovered level.
        """
        if self._state != StrategyState.RUNNING:
            return

        # Reconcile tracked orders with the exchange every tick so
        # filled/cancelled levels are replenished quickly.
        self._tick_count += 1
        await self._reconcile_orders()

        cfg = self._config
        current_price = Decimal(price)
        budget = Decimal(str(cfg.budget_quote))
        investment_per_grid = budget / cfg.num_grids

        for grid_price in self._grid_prices[:-1]:     # buy levels 0 … N-1
            if grid_price >= current_price:
                continue
            price_str = str(grid_price)
            if price_str in self._buy_orders or price_str in self._sell_orders:
                continue
            if self._buy_blocked_by_sell_above(grid_price):
                continue
            amount = (investment_per_grid / grid_price).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN,
            )
            if amount <= 0:
                continue
            if await self._place_order(cfg, OrderSide.BUY, grid_price, amount):
                await self._log(
                    f"Price rose above {grid_price} — placed BUY"
                )

    async def _reconcile_orders(self) -> None:
        """Detect fills/cancellations by comparing tracked and open orders.

        For each tracked order no longer in the exchange's open list,
        queries the order status.  Filled orders trigger
        ``on_order_filled`` (which places counter-orders).  Cancelled
        or expired orders are simply removed so ``on_tick`` can
        re-place them.
        """
        cfg = self._config
        try:
            open_orders = await self._exchange.get_open_orders(
                market=cfg.market,
            )
        except Exception as exc:
            logger.warning("Reconcile: failed to fetch open orders: %s", exc)
            return

        # Build set of currently open order IDs.
        #
        # Some exchange responses may omit operator_id on open-orders
        # payloads; filtering here can incorrectly mark active orders as
        # missing and trigger false cancel/recreate loops.
        open_ids: set[str] = set()
        for order in open_orders:
            open_ids.add(order.order_id)

        missing = self._collect_missing_orders(open_ids)

        if not missing:
            return

        for side, price_str, order_id in missing:
            status = await self._fetch_order_status(order_id)
            if status is None:
                continue
            await self._apply_reconciled_status(
                side=side,
                price_str=price_str,
                order_id=order_id,
                status=status,
            )

    def _collect_missing_orders(
        self, open_ids: set[str]
    ) -> list[tuple[str, str, str]]:
        """Return tracked orders that are not currently open on exchange."""
        missing: list[tuple[str, str, str]] = []
        for price_str, order_id in self._buy_orders.items():
            if order_id not in open_ids:
                missing.append(("buy", price_str, order_id))
        for price_str, order_id in self._sell_orders.items():
            if order_id not in open_ids:
                missing.append(("sell", price_str, order_id))
        return missing

    async def _fetch_order_status(
        self, order_id: str
    ) -> Optional[OrderStatus]:
        """Fetch definitive order status from the exchange.

        Returns None when status cannot be fetched, so tracking remains
        unchanged and the strategy can retry on the next reconciliation.
        """
        cfg = self._config
        try:
            order = await self._exchange.get_order(
                market=cfg.market,
                order_id=order_id,
            )
            return order.status
        except Exception as exc:
            logger.warning(
                "Reconcile: cannot fetch order %s (%s), keeping tracked.",
                order_id,
                exc,
            )
            return None

    async def _apply_reconciled_status(
        self,
        side: str,
        price_str: str,
        order_id: str,
        status: OrderStatus,
    ) -> None:
        """Apply reconciled status for a tracked order."""
        if status == OrderStatus.FILLED:
            await self._log(
                f"Detected {side.upper()} fill @ {price_str} "
                f"(order {order_id})"
            )
            await self.on_order_filled(order_id)
            return

        status_text = status.value if hasattr(status, "value") else str(status)
        await self._log(
            f"Order {order_id} @ {price_str} no longer open "
            f"(status={status_text}), removing from grid"
        )
        if side == "buy":
            self._buy_orders.pop(price_str, None)
        else:
            self._sell_orders.pop(price_str, None)
        await self._report_order(
            exchange_order_id=order_id,
            market=self._config.market,
            side=side,
            order_type="limit",
            status="cancelled",
            price=price_str,
        )

    async def on_order_filled(self, order_id: str) -> None:
        """When a buy fills, place a sell one grid level up and vice versa."""
        if self._state != StrategyState.RUNNING:
            return

        filled = self._find_tracked_order(order_id)
        if filled is None:
            return
        filled_side, filled_price_str = filled

        cfg = self._config

        # Remove from tracking.
        if filled_side == "buy":
            self._buy_orders.pop(filled_price_str, None)
        else:
            self._sell_orders.pop(filled_price_str, None)

        filled_price = Decimal(filled_price_str)

        # Report the fill.
        await self._report_order(
            exchange_order_id=order_id,
            market=cfg.market,
            side=filled_side,
            order_type="limit",
            status="filled",
            price=filled_price_str,
        )

        # Determine the index in the grid.
        try:
            idx = self._grid_prices.index(filled_price)
        except ValueError:
            return

        budget = Decimal(str(cfg.budget_quote))
        investment_per_grid = budget / cfg.num_grids

        if filled_side == "buy":
            await self._handle_buy_fill(
                order_id=order_id,
                idx=idx,
                filled_price=filled_price,
                investment_per_grid=investment_per_grid,
            )
        else:
            await self._handle_sell_fill(
                order_id=order_id,
                idx=idx,
                filled_price=filled_price,
                investment_per_grid=investment_per_grid,
            )

    def _find_tracked_order(
        self, order_id: str
    ) -> Optional[tuple[str, str]]:
        """Find tracked order by id and return (side, price_str)."""
        for p_str, oid in self._buy_orders.items():
            if oid == order_id:
                return "buy", p_str
        for p_str, oid in self._sell_orders.items():
            if oid == order_id:
                return "sell", p_str
        return None

    def _buy_blocked_by_sell_above(self, buy_price: Decimal) -> bool:
        """Return True when buy level has an active sell one level above.

        Rule: if sell exists at level i, level i-1 must stay empty (no buy).
        This prevents repeated buy/sell churn when price oscillates between
        two adjacent grid levels.
        """
        try:
            idx = self._grid_prices.index(buy_price)
        except ValueError:
            return False

        if idx + 1 >= len(self._grid_prices):
            return False

        sell_above_price = str(self._grid_prices[idx + 1])
        return sell_above_price in self._sell_orders

    async def _handle_buy_fill(
        self,
        order_id: str,
        idx: int,
        filled_price: Decimal,
        investment_per_grid: Decimal,
    ) -> None:
        """Handle post-fill logic for a buy order."""
        cfg = self._config
        self._filled_buys += 1
        await self._log(
            f"BUY filled @ {filled_price} (order {order_id}). "
            f"Total buys: {self._filled_buys}"
        )
        if idx + 1 >= len(self._grid_prices):
            return

        sell_price = self._grid_prices[idx + 1]
        amount = (investment_per_grid / sell_price).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN,
        )
        grid_profit = (sell_price - filled_price) * amount
        self._total_profit += grid_profit
        if amount <= 0:
            return

        await self._place_order(cfg, OrderSide.SELL, sell_price, amount)
        await self._log(
            f"Counter SELL placed @ {sell_price} "
            f"(amount={amount}, expected_profit={grid_profit})"
        )

    async def _handle_sell_fill(
        self,
        order_id: str,
        idx: int,
        filled_price: Decimal,
        investment_per_grid: Decimal,
    ) -> None:
        """Handle post-fill logic for a sell order."""
        cfg = self._config
        self._filled_sells += 1
        await self._log(
            f"SELL filled @ {filled_price} (order {order_id}). "
            f"Total sells: {self._filled_sells}"
        )
        if idx - 1 < 0:
            return

        buy_price = self._grid_prices[idx - 1]
        amount = (investment_per_grid / buy_price).quantize(
            Decimal("0.00000001"), rounding=ROUND_DOWN,
        )
        if amount <= 0:
            return

        await self._place_order(cfg, OrderSide.BUY, buy_price, amount)
        await self._log(
            f"Counter BUY placed @ {buy_price} (amount={amount})"
        )

    # ── exchange reconciliation ─────────────────────────────────

    async def _sync_exchange_orders(
        self,
        cfg: GridConfig,
        upper: Decimal,
        lower: Decimal,
    ) -> None:
        """Sync open orders from the exchange that belong to this bot.

        Uses ``operator_id`` to identify orders placed by this bot.
        Matches orders by price to grid levels and stores them in the
        appropriate buy/sell tracking dict.
        """
        try:
            open_orders = await self._exchange.get_open_orders(
                market=cfg.market
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch open orders for sync: %s", exc
            )
            await self._log(
                f"Could not sync orders from exchange: {exc}",
                "WARNING",
            )
            return

        if not open_orders:
            return

        grid_spread = (upper - lower) / cfg.num_grids
        tolerance = grid_spread / 2

        synced = 0
        skipped = 0
        for order in open_orders:
            sync_result = await self._sync_single_open_order(
                cfg=cfg,
                order=order,
                lower=lower,
                upper=upper,
                tolerance=tolerance,
            )
            if sync_result == "skipped_other_bot":
                skipped += 1
            elif sync_result == "synced":
                synced += 1

        msg = (
            f"Order sync: {synced} matched this bot "
            f"(operator={cfg.operator_id}), "
            f"{skipped} belong to other bots, "
            f"{len(open_orders)} total on exchange"
        )
        logger.info(msg)
        await self._log(msg)

    async def _sync_single_open_order(
        self,
        cfg: GridConfig,
        order: Any,
        lower: Decimal,
        upper: Decimal,
        tolerance: Decimal,
    ) -> str:
        """Sync one open order to local tracking.

        Returns one of: "synced", "skipped_other_bot", "ignored".
        """
        if order.price is None:
            return "ignored"

        if order.operator_id is None or order.operator_id != cfg.operator_id:
            return "skipped_other_bot"

        order_price = Decimal(order.price)
        if order_price < lower - tolerance or order_price > upper + tolerance:
            return "ignored"

        best_grid = self._nearest_grid_price(order_price)
        if best_grid is None or abs(best_grid - order_price) > tolerance:
            return "ignored"

        price_str = str(best_grid)
        side_val = (
            order.side.value
            if hasattr(order.side, "value")
            else str(order.side)
        )
        if not self._track_synced_order(price_str, side_val, order.order_id):
            return "ignored"

        await self._report_order(
            exchange_order_id=order.order_id,
            market=cfg.market,
            side=side_val,
            order_type=(
                order.order_type.value
                if hasattr(order.order_type, "value")
                else str(order.order_type)
            ),
            status="new",
            amount=order.amount or "",
            price=order.price or "",
        )
        return "synced"

    def _nearest_grid_price(self, order_price: Decimal) -> Optional[Decimal]:
        """Return nearest configured grid level for an order price."""
        if not self._grid_prices:
            return None
        return min(
            self._grid_prices,
            key=lambda g, op=order_price: abs(g - op),
        )

    def _track_synced_order(
        self,
        price_str: str,
        side_val: str,
        order_id: str,
    ) -> bool:
        """Track a synced open order if not already tracked.

        Returns True when the order was newly added.
        """
        if side_val == "buy":
            if price_str in self._buy_orders:
                return False
            self._buy_orders[price_str] = order_id
            return True

        if price_str in self._sell_orders:
            return False
        self._sell_orders[price_str] = order_id
        return True

    def get_status(self) -> dict[str, Any]:
        return {
            "strategy": self.name(),
            "state": self._state.value,
            "market": self._config.market,
            "upper_price": self._config.upper_price,
            "lower_price": self._config.lower_price,
            "num_grids": self._config.num_grids,
            "grid_prices": [str(p) for p in self._grid_prices],
            "active_orders": len(self._buy_orders) + len(self._sell_orders),
            "active_buys": len(self._buy_orders),
            "active_sells": len(self._sell_orders),
            "filled_buys": self._filled_buys,
            "filled_sells": self._filled_sells,
            "total_profit": str(self._total_profit),
        }
