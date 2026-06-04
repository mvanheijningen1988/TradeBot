"""Virtual wallet management service.

Provides a virtual budget envelope per exchange.  The wallet acts as
a soft cap on how much total capital bots may allocate.  Deposits and
withdrawals are purely bookkeeping — no actual exchange transactions
are made.

The wallet balance is periodically verified against the real exchange
balance to detect if unallocated funds have been moved externally.
"""

import asyncio
import contextlib
import logging
from typing import Optional

from manager.database.repositories import WalletRepository

logger = logging.getLogger(__name__)

_VERIFY_INTERVAL = 300  # 5 minutes


class WalletService:
    """Manages virtual wallets for exchange budget control."""

    def __init__(self, wallet_repo: WalletRepository) -> None:
        self._repo = wallet_repo
        self._verify_task: Optional[asyncio.Task] = None
        self._exchange_client_factory = None
        self._running = False

    def set_exchange_client_factory(self, factory) -> None:
        """Set callable(exchange_id) -> ExchangeClient for verification."""
        self._exchange_client_factory = factory

    # ------------------------------------------------------------------
    # Wallet CRUD
    # ------------------------------------------------------------------

    async def get_or_create(
        self,
        exchange_id: int,
        quote_currency: str = "EUR",
    ) -> dict:
        """Return the wallet for an exchange, creating if needed."""
        wallet = await self._repo.get_by_exchange(exchange_id)
        if not wallet:
            wallet = await self._repo.create(
                exchange_id, quote_currency, 0.0
            )
            logger.info(
                "Created wallet for exchange %d (%s).",
                exchange_id,
                quote_currency,
            )
        return wallet

    async def get_wallet_info(self, exchange_id: int) -> Optional[dict]:
        """Return wallet info with allocated/unallocated breakdown."""
        wallet = await self._repo.get_by_exchange(exchange_id)
        if not wallet:
            return None

        allocated = await self._repo.get_allocated(wallet["id"])
        unallocated = max(0.0, wallet["balance"] - allocated)

        return {
            "id": wallet["id"],
            "exchange_id": wallet["exchange_id"],
            "quote_currency": wallet["quote_currency"],
            "balance": round(wallet["balance"], 2),
            "allocated": round(allocated, 2),
            "unallocated": round(unallocated, 2),
            "created_at": wallet["created_at"],
            "updated_at": wallet["updated_at"],
        }

    # ------------------------------------------------------------------
    # Snapshot helper
    # ------------------------------------------------------------------

    async def _record_snapshot(self, wallet_id: int) -> None:
        """Record a balance snapshot for the budget trend graph."""
        wallet = await self._repo._db.fetch_one(
            "SELECT * FROM wallets WHERE id = ?", (wallet_id,)
        )
        if not wallet:
            return
        allocated = await self._repo.get_allocated(wallet_id)
        balance = wallet["balance"]
        unallocated = max(0.0, balance - allocated)
        await self._repo.record_balance_snapshot(
            wallet_id,
            round(balance, 2),
            round(allocated, 2),
            round(unallocated, 2),
        )

    # ------------------------------------------------------------------
    # Deposit / Withdraw
    # ------------------------------------------------------------------

    async def deposit(
        self,
        exchange_id: int,
        amount: float,
        quote_currency: str = "EUR",
    ) -> dict:
        """Virtually deposit funds into the wallet."""
        if amount <= 0:
            raise ValueError("Deposit amount must be positive.")

        wallet = await self.get_or_create(exchange_id, quote_currency)
        new_balance = wallet["balance"] + amount
        await self._repo.update_balance(wallet["id"], new_balance)
        currency = wallet["quote_currency"]
        await self._repo.add_transaction(
            wallet["id"],
            tx_type="deposit",
            amount=amount,
            description=f"Virtual deposit of {amount} {currency}",
        )
        logger.info(
            "Wallet %d: deposited %.2f %s (new balance: %.2f).",
            wallet["id"],
            amount,
            wallet["quote_currency"],
            new_balance,
        )
        await self._record_snapshot(wallet["id"])
        return await self.get_wallet_info(exchange_id)

    async def withdraw(
        self,
        exchange_id: int,
        amount: float,
    ) -> dict:
        """Virtually withdraw funds from the wallet."""
        if amount <= 0:
            raise ValueError("Withdraw amount must be positive.")

        wallet = await self._repo.get_by_exchange(exchange_id)
        if not wallet:
            raise ValueError("No wallet for this exchange.")

        allocated = await self._repo.get_allocated(wallet["id"])
        unallocated = wallet["balance"] - allocated
        if amount > unallocated:
            raise ValueError(
                f"Cannot withdraw {amount}: only {unallocated:.2f} "
                f"unallocated ({wallet['balance']:.2f} total - "
                f"{allocated:.2f} allocated)."
            )

        new_balance = wallet["balance"] - amount
        await self._repo.update_balance(wallet["id"], new_balance)
        currency = wallet["quote_currency"]
        await self._repo.add_transaction(
            wallet["id"],
            tx_type="withdraw",
            amount=-amount,
            description=f"Virtual withdrawal of {amount} {currency}",
        )
        logger.info(
            "Wallet %d: withdrew %.2f %s (new balance: %.2f).",
            wallet["id"],
            amount,
            wallet["quote_currency"],
            new_balance,
        )
        await self._record_snapshot(wallet["id"])
        return await self.get_wallet_info(exchange_id)

    # ------------------------------------------------------------------
    # Bot allocation
    # ------------------------------------------------------------------

    async def allocate_for_bot(
        self,
        exchange_id: int,
        bot_id: int,
        amount: float,
    ) -> bool:
        """Allocate budget from wallet for a bot.

        Returns True if allocation succeeded.
        """
        wallet = await self._repo.get_by_exchange(exchange_id)
        if not wallet:
            logger.warning(
                "No wallet for exchange %d — allocation skipped.",
                exchange_id,
            )
            return False

        allocated = await self._repo.get_allocated(wallet["id"])
        unallocated = wallet["balance"] - allocated
        if amount > unallocated:
            logger.warning(
                "Wallet %d: cannot allocate %.2f for bot %d "
                "(unallocated: %.2f).",
                wallet["id"],
                amount,
                bot_id,
                unallocated,
            )
            return False

        await self._repo.add_transaction(
            wallet["id"],
            tx_type="bot_allocate",
            amount=-amount,
            bot_id=bot_id,
            description=f"Allocated {amount} to bot {bot_id}",
        )
        logger.info(
            "Wallet %d: allocated %.2f to bot %d.",
            wallet["id"],
            amount,
            bot_id,
        )
        await self._record_snapshot(wallet["id"])
        return True

    async def return_from_bot(
        self,
        exchange_id: int,
        bot_id: int,
        amount: float,
        reason: str = "bot_stop",
    ) -> None:
        """Return funds from a bot back to the wallet."""
        wallet = await self._repo.get_by_exchange(exchange_id)
        if not wallet:
            return

        await self._repo.add_transaction(
            wallet["id"],
            tx_type="bot_return",
            amount=amount,
            bot_id=bot_id,
            description=f"Returned {amount} from bot {bot_id} ({reason})",
        )
        logger.info(
            "Wallet %d: bot %d returned %.2f (%s).",
            wallet["id"],
            bot_id,
            amount,
            reason,
        )
        await self._record_snapshot(wallet["id"])

    async def record_profit(
        self,
        exchange_id: int,
        bot_id: int,
        profit: float,
    ) -> None:
        """Record profit withdrawal to the wallet (withdraw mode)."""
        wallet = await self._repo.get_by_exchange(exchange_id)
        if not wallet:
            return

        new_balance = wallet["balance"] + profit
        await self._repo.update_balance(wallet["id"], new_balance)
        await self._repo.add_transaction(
            wallet["id"],
            tx_type="profit",
            amount=profit,
            bot_id=bot_id,
            description=f"Profit of {profit} from bot {bot_id}",
        )
        logger.info(
            "Wallet %d: profit %.2f from bot %d (new balance: %.2f).",
            wallet["id"],
            profit,
            bot_id,
            new_balance,
        )
        await self._record_snapshot(wallet["id"])

    # ------------------------------------------------------------------
    # Exchange verification
    # ------------------------------------------------------------------

    async def verify_against_exchange(
        self, exchange_id: int
    ) -> Optional[dict]:
        """Check wallet unallocated vs actual exchange balance.

        Returns verification result or None if check cannot be performed.
        """
        if not self._exchange_client_factory:
            return None

        wallet = await self._repo.get_by_exchange(exchange_id)
        if not wallet:
            return None

        try:
            client = await self._exchange_client_factory(exchange_id)
            balances = await client.get_balance(
                symbol=wallet["quote_currency"]
            )
            await client.disconnect()
        except Exception as exc:
            logger.warning(
                "Exchange verification failed for wallet %d: %s",
                wallet["id"],
                exc,
            )
            return None

        exchange_available = (
            float(balances[0].available) if balances else 0.0
        )
        allocated = await self._repo.get_allocated(wallet["id"])
        unallocated = wallet["balance"] - allocated

        ok = exchange_available >= unallocated
        result = {
            "wallet_balance": round(wallet["balance"], 2),
            "allocated": round(allocated, 2),
            "unallocated": round(unallocated, 2),
            "exchange_available": round(exchange_available, 2),
            "sufficient": ok,
        }
        if not ok:
            logger.warning(
                "Wallet %d: exchange has %.2f %s but wallet expects "
                "%.2f unallocated — funds may have been moved.",
                wallet["id"],
                exchange_available,
                wallet["quote_currency"],
                unallocated,
            )
        return result

    # ------------------------------------------------------------------
    # Background verification loop
    # ------------------------------------------------------------------

    async def start_verification_loop(
        self, exchange_repo
    ) -> None:
        """Start periodic exchange balance verification."""
        self._exchange_repo = exchange_repo
        self._running = True

        # Record initial snapshots for existing wallets so the
        # budget trend chart has data from the moment balance exists.
        await self._snapshot_all_wallets()

        self._verify_task = asyncio.create_task(self._verify_loop())
        logger.info("Wallet verification loop started.")

    async def stop_verification_loop(self) -> None:
        """Stop the background wallet verification task gracefully."""
        self._running = False
        if self._verify_task:
            self._verify_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._verify_task

    async def _verify_loop(self) -> None:
        """Periodically verify all wallets against exchange balances."""
        while self._running:
            await asyncio.sleep(_VERIFY_INTERVAL)
            try:
                await self._snapshot_all_wallets()
                exchanges = await self._exchange_repo.list_all()
                for ex in exchanges:
                    wallet = await self._repo.get_by_exchange(ex["id"])
                    if wallet:
                        await self.verify_against_exchange(ex["id"])
            except Exception as exc:
                logger.exception(
                    "Wallet verification cycle failed: %s", exc
                )

    async def _snapshot_all_wallets(self) -> None:
        """Record a balance snapshot for every wallet that has funds."""
        try:
            all_wallets = await self._repo._db.fetch_all(
                "SELECT * FROM wallets WHERE balance > 0"
            )
            for w in all_wallets:
                await self._record_snapshot(w["id"])
        except Exception as exc:
            logger.exception("Wallet snapshot cycle failed: %s", exc)
