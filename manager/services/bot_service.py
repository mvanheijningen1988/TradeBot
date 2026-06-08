"""Bot lifecycle management service.

Handles creation, assignment, start/stop, deletion, and state
transitions for trading bots.
"""

import logging
from typing import Any, Optional

from manager.constants import (
    BOT_STATUS_ASSIGNING,
    BOT_STATUS_FAULT,
    BOT_STATUS_INITIALIZING,
    BOT_STATUS_RUNNING,
    BOT_STATUS_STOPPED,
    PROFIT_MODES,
    WS_TYPE_ASSIGN,
    WS_TYPE_STOP_BOT,
)
from manager.database.repositories import (
    BotRepository,
    ExchangeRepository,
    OrderHistoryRepository,
    TradeHistoryRepository,
)
from manager.services.worker_service import WorkerService

logger = logging.getLogger(__name__)


class BotService:
    """Manage bot lifecycle operations and exchange-facing cleanup.

    This service coordinates repository writes and worker commands for bot
    creation, assignment, recovery, shutdown, and deletion.
    """

    RECOVERABLE_STATUSES = (
        BOT_STATUS_RUNNING,
        BOT_STATUS_ASSIGNING,
        BOT_STATUS_INITIALIZING,
    )

    def __init__(
        self,
        bot_repo: BotRepository,
        order_repo: OrderHistoryRepository,
        trade_repo: TradeHistoryRepository,
        worker_service: WorkerService,
        exchange_repo: ExchangeRepository,
    ) -> None:
        self._bot_repo = bot_repo
        self._order_repo = order_repo
        self._trade_repo = trade_repo
        self._worker_service = worker_service
        self._exchange_repo = exchange_repo

    async def create_bot(
        self,
        name: str,
        exchange_id: int,
        market: str,
        strategy: str,
        strategy_params: dict[str, Any],
        budget_quote: float,
        profit_mode: str = "withdraw",
        profit_skim_pct: float = 0.0,
    ) -> dict[str, Any]:
        """Create a new bot in stopped state.

        Args:
            name: User-defined bot name.
            exchange_id: Exchange configuration identifier.
            market: Market symbol (for example ``BTC-EUR``).
            strategy: Registered strategy name.
            strategy_params: Strategy-specific runtime configuration.
            budget_quote: Quote-currency budget assigned to the bot.
            profit_mode: Profit handling mode from ``PROFIT_MODES``.
            profit_skim_pct: Optional skim percentage when applicable.

        Returns:
            The created bot row as a dictionary.

        Raises:
            ValueError: If ``profit_mode`` is not supported.
        """
        if profit_mode not in PROFIT_MODES:
            raise ValueError(
                f"Invalid profit_mode '{profit_mode}'. "
                f"Choose from: {PROFIT_MODES}"
            )

        operator_id = await self._bot_repo.get_next_operator_id()
        bot = await self._bot_repo.create(
            name=name,
            exchange_id=exchange_id,
            market=market,
            strategy=strategy,
            strategy_params=strategy_params,
            operator_id=operator_id,
            budget_quote=budget_quote,
            profit_mode=profit_mode,
            profit_skim_pct=profit_skim_pct,
        )
        logger.info(
            "Bot created: id=%d name='%s' market=%s strategy=%s",
            bot["id"], name, market, strategy,
        )
        return bot

    async def start_bot(
        self, bot_id: int, worker_id: Optional[int] = None
    ) -> dict[str, Any]:
        """Start a bot and dispatch assign command to a worker.

        Args:
            bot_id: Bot identifier.
            worker_id: Optional explicit worker identifier. If omitted,
                the service auto-selects an available worker.

        Returns:
            The refreshed bot row after assignment.

        Raises:
            ValueError: If the bot does not exist or is already active.
            RuntimeError: If no worker is available or dispatch fails.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found.")
        if bot["status"] in self.RECOVERABLE_STATUSES:
            raise ValueError(f"Bot {bot_id} is already {bot['status']}.")

        # Reset retry counter so the bot gets a fresh set of retries.
        await self._bot_repo.update(bot_id, retry_count=0)

        manual = worker_id is not None
        if not manual:
            worker = await self._worker_service.select_worker()
            if not worker:
                raise RuntimeError("No workers available.")
            worker_id = int(worker["id"])

        await self._bot_repo.assign_worker(
            bot_id, worker_id, manual=manual
        )
        bot = await self._bot_repo.get_by_id(bot_id)
        logger.info(
            "Bot %d assigned to worker %d (manual=%s).",
            bot_id, worker_id, manual,
        )

        if not bot:
            raise RuntimeError(f"Bot {bot_id} disappeared after assignment.")
        await self._dispatch_assign(bot, worker_id)
        return bot

    async def _dispatch_assign(
        self, bot: dict[str, Any], worker_id: int
    ) -> None:
        """Send the worker assignment payload for one bot.

        Args:
            bot: Persisted bot payload containing strategy and budget fields.
            worker_id: Destination worker identifier.

        Raises:
            ValueError: If referenced exchange configuration is missing.
            RuntimeError: If worker command delivery fails.
        """
        exchange = await self._exchange_repo.get_by_id(bot["exchange_id"])
        if not exchange:
            await self._bot_repo.update_status(bot["id"], BOT_STATUS_STOPPED)
            raise ValueError(
                f"Exchange {bot['exchange_id']} not found."
            )

        payload = {
            "type": WS_TYPE_ASSIGN,
            "bot_id": bot["id"],
            "config": {
                "strategy": bot["strategy"],
                "market": bot["market"],
                "exchange_id": bot["exchange_id"],
                "operator_id": bot["operator_id"],
                "reference_id": bot["uuid"],
                "budget_quote": bot["budget_quote"],
                "profit_mode": bot["profit_mode"],
                "profit_skim_pct": bot["profit_skim_pct"],
                "strategy_params": bot["strategy_params"],
                "exchange": {
                    "api_key": exchange["api_key"],
                    "api_secret": exchange["api_secret"],
                },
            },
        }

        sent = await self._worker_service.send_command(worker_id, payload)
        if sent:
            return

        logger.error(
            "Failed to send assign command for bot %d to worker %d.",
            bot["id"], worker_id,
        )
        await self._bot_repo.update_status(bot["id"], BOT_STATUS_STOPPED)
        raise RuntimeError(
            f"Worker {worker_id} is not connected. Bot stopped."
        )

    async def restore_bots_for_worker(self, worker_id: int) -> int:
        """Re-dispatch recoverable bots currently assigned to a worker.

        Args:
            worker_id: Worker identifier to restore bots for.

        Returns:
            Number of bots successfully restored.
        """
        bots = await self._bot_repo.list_by_worker(worker_id)
        restored = 0
        for bot in bots:
            if bot["status"] not in self.RECOVERABLE_STATUSES:
                continue
            try:
                await self._bot_repo.update_status(
                    bot["id"], BOT_STATUS_ASSIGNING
                )
                bot = await self._bot_repo.get_by_id(bot["id"])
                if not bot:
                    continue
                await self._dispatch_assign(bot, worker_id)
                restored += 1
                logger.info(
                    "Recovered bot %d on worker %d after restart/failover.",
                    bot["id"],
                    worker_id,
                )
            except Exception:
                logger.exception(
                    "Failed to recover bot %d on worker %d.",
                    bot["id"],
                    worker_id,
                )
        return restored

    async def restore_unassigned_bots(self) -> int:
        """Recover active-state bots that currently have no assigned worker.

        Returns:
            Number of bots successfully reassigned and dispatched.
        """
        bots = await self._bot_repo.list_all()
        restored = 0
        for bot in bots:
            if bot["status"] not in self.RECOVERABLE_STATUSES:
                continue
            if bot.get("worker_id"):
                continue
            worker = await self._worker_service.select_worker()
            if not worker:
                logger.warning(
                    "No worker available to recover bot %d.", bot["id"]
                )
                continue
            try:
                await self._bot_repo.assign_worker(
                    bot["id"], worker["id"], manual=False
                )
                bot = await self._bot_repo.get_by_id(bot["id"])
                if not bot:
                    continue
                await self._dispatch_assign(bot, worker["id"])
                restored += 1
                logger.info(
                    "Recovered unassigned bot %d on worker %d.",
                    bot["id"],
                    worker["id"],
                )
            except Exception:
                logger.exception(
                    "Failed to recover unassigned bot %d.",
                    bot["id"],
                )
        return restored

    async def stop_bot(self, bot_id: int) -> dict:
        """Stop a bot and reset retry counters.

        Args:
            bot_id: Bot identifier.

        Returns:
            Updated bot row after state transition.

        Raises:
            ValueError: If the bot does not exist.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found.")

        # Send stop command to the worker if assigned.
        if bot.get("worker_id"):
            await self._worker_service.send_command(
                bot["worker_id"],
                {"type": WS_TYPE_STOP_BOT, "bot_id": bot_id},
            )

        await self._bot_repo.update_status(bot_id, BOT_STATUS_STOPPED)
        await self._bot_repo.update(bot_id, retry_count=0)
        bot = await self._bot_repo.get_by_id(bot_id)
        logger.info("Bot %d stopped.", bot_id)
        return bot

    async def update_bot_status(
        self, bot_id: int, status: str
    ) -> None:
        """Persist a status update from worker runtime callbacks.

        Args:
            bot_id: Bot identifier.
            status: New bot status value.
        """
        await self._bot_repo.update_status(bot_id, status)

    async def report_fault(self, bot_id: int) -> None:
        """Handle bot fault reporting and retry escalation.

        Args:
            bot_id: Bot identifier.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            return

        retries = bot["retry_count"] + 1
        if retries >= 3:
            await self._bot_repo.update_status(bot_id, BOT_STATUS_FAULT)
            await self._bot_repo.update(bot_id, retry_count=retries)
            logger.error(
                "Bot %d faulted after %d retries.", bot_id, retries
            )
        else:
            await self._bot_repo.update(bot_id, retry_count=retries)
            logger.warning(
                "Bot %d failed, retry %d/3.", bot_id, retries
            )

    async def delete_bot(
        self, bot_id: int, mode: str = "stop_cancel"
    ) -> None:
        """Delete a bot with the specified cleanup mode.

        Args:
            bot_id: Bot identifier.
            mode: Cleanup mode used before final delete.

        Modes:
            stop_cancel: Stop bot, cancel all exchange orders, delete history.
            delete_only: Delete from DB only (budget becomes orphaned).
            convert_base: Convert holdings to base currency.
            convert_quote: Convert holdings to quote currency.

        Raises:
            ValueError: If the bot does not exist.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found.")

        # Stop the bot on the worker if running.
        if bot.get("worker_id") and bot["status"] not in (
            BOT_STATUS_STOPPED, BOT_STATUS_FAULT
        ):
            await self._worker_service.send_command(
                bot["worker_id"],
                {"type": WS_TYPE_STOP_BOT, "bot_id": bot_id},
            )

        # Cancel all open orders on the exchange.
        if mode != "delete_only":
            await self._cancel_exchange_orders(bot, bot_id)

        # Delete trade history before order history to satisfy FK
        # from trade_history.order_history_id -> order_history.id.
        await self._trade_repo.delete_by_bot(bot_id)
        await self._order_repo.delete_by_bot(bot_id)

        await self._bot_repo.update_status(bot_id, BOT_STATUS_STOPPED)
        await self._bot_repo.delete(bot_id)
        logger.info("Bot %d deleted (mode=%s).", bot_id, mode)

    async def _cancel_exchange_orders(
        self, bot: dict[str, Any], bot_id: int
    ) -> None:
        """Cancel open exchange orders owned by the bot operator id.

        Args:
            bot: Bot payload containing market/exchange/operator identifiers.
            bot_id: Bot identifier used for logging context.
        """
        try:
            exchange = await self._exchange_repo.get_by_id(
                bot["exchange_id"]
            )
            if not exchange:
                return
            from manager.exchanges.bitvavo.client import BitvavoClient
            client = BitvavoClient(
                api_key=exchange["api_key"],
                api_secret=exchange["api_secret"],
            )
            await client.connect()
            await client.authenticate()
            try:
                open_orders = await client.get_open_orders(
                    market=bot["market"]
                )
                cancelled = 0
                for order in open_orders:
                    if order.operator_id != bot["operator_id"]:
                        continue
                    try:
                        await client.cancel_order(
                            market=bot["market"],
                            order_id=order.order_id,
                            operator_id=bot["operator_id"],
                        )
                        cancelled += 1
                    except Exception:
                        logger.warning(
                            "Failed to cancel order %s",
                            order.order_id,
                        )
                logger.info(
                    "Cancelled %d exchange orders for bot %d.",
                    cancelled, bot_id,
                )
            finally:
                await client.disconnect()
        except Exception:
            logger.exception(
                "Error cancelling exchange orders for bot %d.",
                bot_id,
            )

    async def update_bot(self, bot_id: int, **fields: Any) -> dict[str, Any]:
        """Update mutable bot fields and return the refreshed record.

        Args:
            bot_id: Bot identifier.
            **fields: Mutable bot fields to persist.

        Returns:
            Updated bot row.
        """
        await self._bot_repo.update(bot_id, **fields)
        return await self._bot_repo.get_by_id(bot_id)

    async def get_bot(self, bot_id: int) -> Optional[dict[str, Any]]:
        """Fetch one bot row by identifier.

        Args:
            bot_id: Bot identifier.

        Returns:
            Bot row or ``None`` when not found.
        """
        return await self._bot_repo.get_by_id(bot_id)

    async def list_bots(self) -> list[dict[str, Any]]:
        """List all persisted bots for API and UI use.

        Returns:
            List of bot rows.
        """
        return await self._bot_repo.list_all()

    async def get_orders(
        self, bot_id: int, limit: int = 100
    ) -> list[dict]:
        """Return exchange order history rows for one bot.

        Args:
            bot_id: Bot identifier.
            limit: Max number of rows to return.

        Returns:
            List of order history rows.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            return []

        exchange = await self._exchange_repo.get_by_id(bot["exchange_id"])
        if not exchange:
            return []

        from manager.exchanges.bitvavo.client import BitvavoClient

        client = BitvavoClient(
            api_key=exchange["api_key"],
            api_secret=exchange["api_secret"],
        )
        await client.connect()
        await client.authenticate()
        try:
            known_order_ids = await self._known_exchange_order_ids(bot_id)
            orders = await client.get_orders(
                market=bot["market"],
                limit=limit,
            )
            return [
                self._serialize_exchange_order(order, bot_id)
                for order in orders
                if self._is_bot_reference_order(
                    order, bot, known_order_ids
                )
            ]
        finally:
            await client.disconnect()

    async def get_open_orders(self, bot_id: int) -> list[dict]:
        """Fetch currently open exchange orders scoped to one bot.

        Args:
            bot_id: Bot identifier.

        Returns:
            Live open orders that are known to belong to this bot.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            return []

        exchange = await self._exchange_repo.get_by_id(bot["exchange_id"])
        if not exchange:
            return []

        from manager.exchanges.bitvavo.client import BitvavoClient

        client = BitvavoClient(
            api_key=exchange["api_key"],
            api_secret=exchange["api_secret"],
        )
        await client.connect()
        await client.authenticate()
        try:
            known_order_ids = await self._known_exchange_order_ids(bot_id)
            orders = await client.get_open_orders(market=bot["market"])
            result = []
            for o in orders:
                if not self._is_bot_reference_order(
                    o, bot, known_order_ids
                ):
                    continue
                result.append(self._serialize_open_order(o, bot_id))
            return result
        finally:
            await client.disconnect()

    async def get_grid_levels(self, bot_id: int) -> list[dict[str, Any]]:
        """Return grid levels with active bot-owned orders marked.

        Args:
            bot_id: Bot identifier.

        Returns:
            Grid levels containing index, level price, and active order side.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            return []

        params = bot.get("strategy_params") or {}
        upper = float(params.get("upper_price", 0))
        lower = float(params.get("lower_price", 0))
        num = int(params.get("num_grids", 0))
        if upper <= lower or num < 2:
            return []

        spread = (upper - lower) / num
        levels = [
            {
                "index": i,
                "price": lower + spread * i,
                "order_type": None,
            }
            for i in range(num + 1)
        ]

        open_orders = await self.get_open_orders(bot_id)
        if not open_orders:
            return levels

        level_tolerance = max(spread * 0.001, 1e-8)
        for order in open_orders:
            order_price = float(order.get("price") or 0)
            side = str(order.get("side") or "").lower()
            if not order_price or side not in ("buy", "sell"):
                continue

            current_price = order_price
            nearest = min(
                levels,
                key=lambda lvl, p=current_price: abs(
                    float(lvl["price"]) - p
                ),
            )
            if nearest["order_type"]:
                continue
            if abs(float(nearest["price"]) - order_price) > level_tolerance:
                continue

            nearest["order_type"] = side

        return levels

    @staticmethod
    def _reference_id(bot: dict[str, Any]) -> str:
        return str(
            bot.get("reference_id")
            or bot.get("uuid")
            or bot.get("operator_id")
            or ""
        )

    @classmethod
    def _is_bot_reference_order(
        cls,
        order,
        bot: dict[str, Any],
        known_order_ids: Optional[set[str]] = None,
    ) -> bool:
        """Validate that an exchange order belongs to this bot reference."""
        operator_id = bot.get("operator_id")
        order_operator_id = getattr(order, "operator_id", None)
        exchange_order_id = str(getattr(order, "order_id", "") or "")

        reference_id = cls._reference_id(bot)
        client_order_id = getattr(order, "client_order_id", None)
        if order_operator_id is not None:
            if operator_id is None or order_operator_id != operator_id:
                return False
            if known_order_ids and exchange_order_id in known_order_ids:
                return True
            if client_order_id and reference_id:
                return str(client_order_id).startswith(reference_id)
            return True

        if known_order_ids and exchange_order_id in known_order_ids:
            return True

        if client_order_id and reference_id:
            return str(client_order_id).startswith(reference_id)

        return False

    @staticmethod
    def _enum_value(value: Any) -> str:
        """Return enum-backed values as plain strings."""
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)

    @staticmethod
    def _string_field(order: Any, field_name: str, default: str = "") -> str:
        """Read one order field and normalize empty values to strings."""
        return getattr(order, field_name, default) or default

    @staticmethod
    def _bool_field(order: Any, field_name: str, default: bool) -> bool:
        """Read one order field and normalize to bool."""
        return bool(getattr(order, field_name, default))

    @classmethod
    def _serialize_exchange_order(
        cls,
        order,
        bot_id: int,
    ) -> dict[str, Any]:
        """Convert an exchange order model to API payload shape."""
        return {
            "id": order.order_id,
            "exchange_order_id": order.order_id,
            "bot_id": bot_id,
            "market": order.market,
            "side": cls._enum_value(order.side),
            "order_type": cls._enum_value(order.order_type),
            "status": cls._enum_value(order.status),
            "operator_id": getattr(order, "operator_id", None),
            "client_order_id": cls._string_field(order, "client_order_id"),
            "amount": cls._string_field(order, "amount"),
            "amount_remaining": cls._string_field(order, "amount_remaining"),
            "amount_quote": cls._string_field(order, "amount_quote"),
            "amount_quote_remaining": cls._string_field(
                order, "amount_quote_remaining"
            ),
            "price": cls._string_field(order, "price"),
            "on_hold": cls._string_field(order, "on_hold"),
            "on_hold_currency": cls._string_field(
                order, "on_hold_currency"
            ),
            "trigger_price": cls._string_field(order, "trigger_price"),
            "trigger_amount": cls._string_field(order, "trigger_amount"),
            "trigger_type": cls._string_field(order, "trigger_type"),
            "trigger_reference": cls._string_field(
                order, "trigger_reference"
            ),
            "filled_amount": cls._string_field(
                order, "filled_amount", "0"
            ),
            "filled_amount_quote": cls._string_field(
                order, "filled_amount_quote", "0"
            ),
            "fee_paid": cls._string_field(order, "fee_paid", "0"),
            "fee_currency": cls._string_field(order, "fee_currency"),
            "self_trade_prevention": cls._string_field(
                order, "self_trade_prevention"
            ),
            "time_in_force": cls._string_field(order, "time_in_force"),
            "post_only": cls._bool_field(order, "post_only", False),
            "visible": cls._bool_field(order, "visible", True),
            "created_at": order.created,
            "updated_at": getattr(order, "updated", 0),
            "fill_count": len(getattr(order, "fills", []) or []),
        }

    @staticmethod
    def _serialize_open_order(order, bot_id: int) -> dict[str, Any]:
        """Convert an exchange order model to API payload shape."""
        return BotService._serialize_exchange_order(order, bot_id)

    @classmethod
    def _serialize_trade_fill(
        cls,
        order,
        fill,
        bot_id: int,
    ) -> dict[str, Any]:
        """Convert one exchange fill to API payload shape."""
        return {
            "id": f"{order.order_id}:{fill.fill_id}",
            "bot_id": bot_id,
            "exchange_trade_id": fill.fill_id,
            "exchange_order_id": order.order_id,
            "operator_id": getattr(order, "operator_id", None),
            "client_order_id": cls._string_field(order, "client_order_id"),
            "market": order.market,
            "side": cls._enum_value(order.side),
            "order_type": cls._enum_value(order.order_type),
            "order_status": cls._enum_value(order.status),
            "amount": fill.amount,
            "price": fill.price,
            "fee": fill.fee,
            "fee_currency": fill.fee_currency,
            "taker": fill.taker,
            "settled": fill.settled,
            "order_amount": cls._string_field(order, "amount"),
            "order_amount_remaining": cls._string_field(
                order, "amount_remaining"
            ),
            "order_amount_quote": cls._string_field(order, "amount_quote"),
            "order_amount_quote_remaining": cls._string_field(
                order, "amount_quote_remaining"
            ),
            "order_price": cls._string_field(order, "price"),
            "filled_amount": cls._string_field(order, "filled_amount", "0"),
            "filled_amount_quote": cls._string_field(
                order, "filled_amount_quote", "0"
            ),
            "fee_paid": cls._string_field(order, "fee_paid", "0"),
            "time_in_force": cls._string_field(order, "time_in_force"),
            "post_only": cls._bool_field(order, "post_only", False),
            "visible": cls._bool_field(order, "visible", True),
            "created_at": fill.timestamp,
            "order_created_at": order.created,
            "order_updated_at": order.updated,
        }

    async def get_trades(
        self, bot_id: int, limit: int = 100
    ) -> list[dict]:
        """Return exchange trade rows for one bot.

        Args:
            bot_id: Bot identifier.
            limit: Max number of rows to return.

        Returns:
            List of trade history rows.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            return []

        exchange = await self._exchange_repo.get_by_id(bot["exchange_id"])
        if not exchange:
            return []

        from manager.exchanges.bitvavo.client import BitvavoClient

        client = BitvavoClient(
            api_key=exchange["api_key"],
            api_secret=exchange["api_secret"],
        )
        await client.connect()
        await client.authenticate()
        try:
            known_order_ids = await self._known_exchange_order_ids(bot_id)
            orders = await client.get_orders(
                market=bot["market"],
                limit=limit,
            )
            result: list[dict[str, Any]] = []
            for order in orders:
                if not self._is_bot_reference_order(
                    order, bot, known_order_ids
                ):
                    continue
                for fill in getattr(order, "fills", []) or []:
                    result.append(
                        self._serialize_trade_fill(order, fill, bot_id)
                    )
            return result
        finally:
            await client.disconnect()

    async def _known_exchange_order_ids(self, bot_id: int) -> set[str]:
        """Return persisted exchange order ids already linked to a bot."""
        return await self._order_repo.list_exchange_order_ids_by_bots(
            [bot_id]
        )
