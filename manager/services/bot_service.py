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
    """Manages the full bot lifecycle."""

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
        strategy_params: dict,
        budget_quote: float,
        profit_mode: str = "withdraw",
        profit_skim_pct: float = 0.0,
    ) -> dict:
        """Create a new bot in stopped state."""
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
    ) -> dict:
        """Start a bot by assigning it to a worker."""
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
            worker_id = worker["id"]

        await self._bot_repo.assign_worker(
            bot_id, worker_id, manual=manual
        )
        bot = await self._bot_repo.get_by_id(bot_id)
        logger.info(
            "Bot %d assigned to worker %d (manual=%s).",
            bot_id, worker_id, manual,
        )

        await self._dispatch_assign(bot, worker_id)
        return bot

    async def _dispatch_assign(self, bot: dict, worker_id: int) -> None:
        """Send assign command for a bot to a worker."""
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
        """Re-dispatch recoverable bots assigned to a specific worker."""
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
        """Assign recoverable bots without worker to any available worker."""
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
        """Stop a running bot."""
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
        """Update bot status (called by worker via WebSocket)."""
        await self._bot_repo.update_status(bot_id, status)

    async def report_fault(self, bot_id: int) -> None:
        """Handle a bot fault—increment retry counter."""
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

        Modes:
            stop_cancel: Stop bot, cancel all exchange orders, delete history.
            delete_only: Delete from DB only (budget becomes orphaned).
            convert_base: Convert holdings to base currency.
            convert_quote: Convert holdings to quote currency.
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
            try:
                exchange = await self._exchange_repo.get_by_id(
                    bot["exchange_id"]
                )
                if exchange:
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
                            # Only cancel orders belonging to this bot.
                            if (
                                order.operator_id is not None
                                and order.operator_id != bot["operator_id"]
                            ):
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

        # Delete trade history before order history to satisfy FK
        # from trade_history.order_history_id -> order_history.id.
        await self._trade_repo.delete_by_bot(bot_id)
        await self._order_repo.delete_by_bot(bot_id)

        await self._bot_repo.update_status(bot_id, BOT_STATUS_STOPPED)
        await self._bot_repo.delete(bot_id)
        logger.info("Bot %d deleted (mode=%s).", bot_id, mode)

    async def update_bot(self, bot_id: int, **fields: Any) -> dict:
        """Update bot fields."""
        await self._bot_repo.update(bot_id, **fields)
        return await self._bot_repo.get_by_id(bot_id)

    async def get_bot(self, bot_id: int) -> Optional[dict]:
        """Get a single bot by ID."""
        return await self._bot_repo.get_by_id(bot_id)

    async def list_bots(self) -> list[dict]:
        """List all bots."""
        return await self._bot_repo.list_all()

    async def get_orders(
        self, bot_id: int, limit: int = 100
    ) -> list[dict]:
        """Return order history for a bot."""
        return await self._order_repo.list_by_bot(bot_id, limit)

    async def get_open_orders(self, bot_id: int) -> list[dict]:
        """Fetch live open orders from the exchange for a bot."""
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
            orders = await client.get_open_orders(market=bot["market"])
            result = []
            for o in orders:
                # Strict filter: only orders explicitly tagged with this
                # bot's operator_id are treated as bot-owned orders.
                if o.operator_id != bot["operator_id"]:
                    continue
                result.append({
                    "exchange_order_id": o.order_id,
                    "market": o.market,
                    "side": o.side.value if hasattr(o.side, "value") else str(o.side),
                    "order_type": o.order_type.value if hasattr(o.order_type, "value") else str(o.order_type),
                    "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                    "amount": o.amount or "",
                    "amount_remaining": o.amount_remaining or "",
                    "price": o.price or "",
                    "created_at": o.created,
                    "bot_id": bot_id,
                })
            return result
        finally:
            await client.disconnect()

    async def get_trades(
        self, bot_id: int, limit: int = 100
    ) -> list[dict]:
        """Return trade history for a bot."""
        return await self._trade_repo.list_by_bot(bot_id, limit)
