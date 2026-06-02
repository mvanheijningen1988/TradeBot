"""Budget management service.

Tracks allocated budgets per bot and verifies them against exchange
balances.  Since Bitvavo (and most exchanges) do not support balance
reservation, the manager enforces soft limits checked against actual
exchange balances.
"""

import logging
from decimal import Decimal
from typing import Optional

from manager.database.repositories import BotRepository, BudgetHistoryRepository
from manager.exchanges.base import ExchangeClient

logger = logging.getLogger(__name__)


class BudgetService:
    """Manages budget allocation and verification."""

    def __init__(
        self,
        bot_repo: BotRepository,
        budget_repo: BudgetHistoryRepository,
    ) -> None:
        self._bot_repo = bot_repo
        self._budget_repo = budget_repo

    async def get_total_allocated(self, exchange_id: int) -> Decimal:
        """Sum all budget_quote for active bots on a given exchange."""
        bots = await self._bot_repo.list_all()
        total = Decimal("0")
        for bot in bots:
            if bot["exchange_id"] != exchange_id:
                continue
            if bot["status"] == "stopped":
                continue
            total += Decimal(str(bot["budget_quote"]))
        return total

    async def verify_budget(
        self,
        exchange_client: ExchangeClient,
        exchange_id: int,
        quote_currency: str,
        requested_budget: float,
    ) -> tuple[bool, str]:
        """Check if enough balance is available for a new allocation.

        Returns (allowed, message).
        """
        balances = await exchange_client.get_balance(symbol=quote_currency)
        if not balances:
            return False, f"No balance found for {quote_currency}."

        available = Decimal(balances[0].available)
        allocated = await self.get_total_allocated(exchange_id)
        free = available - allocated
        needed = Decimal(str(requested_budget))

        if needed > free:
            msg = (
                f"Insufficient budget: {needed} requested, "
                f"{free} available ({available} total - "
                f"{allocated} allocated)."
            )
            logger.warning(msg)
            return False, msg

        return True, "Budget verified."

    async def record_snapshot(
        self, bot_id: int, balance: float
    ) -> None:
        """Record a budget snapshot for trend graphs."""
        await self._budget_repo.record(bot_id, balance)

    async def get_history(
        self, bot_id: int, limit: int = 500
    ) -> list[dict]:
        """Return budget history for a bot."""
        return await self._budget_repo.get_history(bot_id, limit)

    async def get_all_history(self, limit: int = 500) -> list[dict]:
        """Return budget history aggregated across all bots."""
        return await self._budget_repo.get_all_history(limit)
