"""Budget management service.

Tracks allocated budgets per bot and verifies them against the virtual
wallet (if available) or exchange balances.  Since Bitvavo (and most
exchanges) do not support balance reservation, the manager enforces
soft limits.
"""

import logging
from decimal import Decimal

from manager.database.repositories import (
    BotRepository,
    BudgetHistoryRepository,
)

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
        self._wallet_service = None

    def set_wallet_service(self, wallet_service) -> None:
        """Inject the wallet service for wallet-aware budget checks."""
        self._wallet_service = wallet_service
        self._wallet_repo = getattr(wallet_service, '_repo', None)

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
        exchange_client,
        exchange_id: int,
        quote_currency: str,
        requested_budget: float,
    ) -> tuple[bool, str]:
        """Check if enough balance is available for a new allocation.

        When a wallet exists for the exchange, budget is checked
        against the wallet's unallocated balance.  Otherwise falls
        back to the raw exchange balance.

        Returns (allowed, message).
        """
        needed = Decimal(str(requested_budget))

        # ── Wallet-based check ──────────────────────────────────
        if self._wallet_service:
            info = await self._wallet_service.get_wallet_info(exchange_id)
            if info and info["balance"] > 0:
                free = Decimal(str(info["unallocated"]))
                if needed > free:
                    msg = (
                        f"Insufficient wallet budget: {needed} "
                        f"requested, {free} unallocated "
                        f"({info['balance']} wallet - "
                        f"{info['allocated']} allocated)."
                    )
                    logger.warning(msg)
                    return False, msg
                return True, "Budget verified (wallet)."

        # ── Fallback: raw exchange balance ──────────────────────
        balances = await exchange_client.get_balance(symbol=quote_currency)
        if not balances:
            return False, f"No balance found for {quote_currency}."

        available = Decimal(balances[0].available)
        allocated = await self.get_total_allocated(exchange_id)
        free = available - allocated

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
        self,
        bot_id: int,
        limit: int = 500,
        since_minutes: int | None = None,
    ) -> list[dict]:
        """Return budget history for a bot."""
        return await self._budget_repo.get_history(
            bot_id,
            limit,
            since_minutes,
        )

    async def get_all_history(
        self,
        limit: int = 500,
        since_minutes: int | None = None,
    ) -> list[dict]:
        """Return aggregated budget history across bot snapshots only."""
        return await self._budget_repo.get_all_history(limit, since_minutes)
