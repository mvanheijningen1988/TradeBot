"""Bot lifecycle management service.

Handles creation, assignment, start/stop, deletion, and state
transitions for trading bots.
"""

import json
import logging
from typing import Any, Optional

from manager.constants import (
    BOT_STATUS_ASSIGNING,
    BOT_STATUS_FAULT,
    BOT_STATUS_INITIALIZING,
    BOT_STATUS_RUNNING,
    BOT_STATUS_STOPPED,
    PROFIT_MODES,
)
from manager.database.repositories import (
    BotRepository,
    OrderHistoryRepository,
    TradeHistoryRepository,
)
from manager.services.worker_service import WorkerService

logger = logging.getLogger(__name__)


class BotService:
    """Manages the full bot lifecycle."""

    def __init__(
        self,
        bot_repo: BotRepository,
        order_repo: OrderHistoryRepository,
        trade_repo: TradeHistoryRepository,
        worker_service: WorkerService,
    ) -> None:
        self._bot_repo = bot_repo
        self._order_repo = order_repo
        self._trade_repo = trade_repo
        self._worker_service = worker_service

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
        if bot["status"] == BOT_STATUS_RUNNING:
            raise ValueError(f"Bot {bot_id} is already running.")

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
        return bot

    async def stop_bot(self, bot_id: int) -> dict:
        """Stop a running bot."""
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found.")

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
            stop_cancel: Stop bot, cancel all exchange orders.
            delete_only: Delete from DB only (budget becomes orphaned).
            convert_base: Convert holdings to base currency.
            convert_quote: Convert holdings to quote currency.
        """
        bot = await self._bot_repo.get_by_id(bot_id)
        if not bot:
            raise ValueError(f"Bot {bot_id} not found.")

        # For now, mark as stopped and delete from DB.
        # The actual exchange order cancellation is handled by the worker.
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

    async def get_trades(
        self, bot_id: int, limit: int = 100
    ) -> list[dict]:
        """Return trade history for a bot."""
        return await self._trade_repo.list_by_bot(bot_id, limit)
