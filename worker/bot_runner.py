"""Bot runner – executes a strategy on the Worker Node.

Each BotRunner manages one bot, handling its lifecycle and reporting
status and logs back to the Manager.
"""

import asyncio
import logging
import uuid
from typing import Optional

from manager.constants import (
    BOT_STATUS_FAULT,
    BOT_STATUS_INITIALIZING,
    BOT_STATUS_RUNNING,
    BOT_STATUS_STOPPED,
)
from worker.manager_client import ManagerClient

logger = logging.getLogger(__name__)


class BotRunner:
    """Runs a single bot strategy in an async task."""

    def __init__(
        self,
        bot_id: int,
        config: dict,
        client: ManagerClient,
    ) -> None:
        self.bot_id = bot_id
        self.config = config
        self._client = client
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        """Main bot execution loop."""
        correlation_id = str(uuid.uuid4())[:12]
        try:
            self._running = True
            await self._client.send_bot_status(
                self.bot_id, BOT_STATUS_INITIALIZING
            )
            await self._client.send_bot_log(
                self.bot_id,
                "Bot initializing...",
                correlation_id=correlation_id,
            )

            # Create exchange client and strategy from config.
            strategy = await self._create_strategy()
            if not strategy:
                await self._client.send_error(
                    self.bot_id, "Failed to create strategy."
                )
                return

            await self._client.send_bot_status(
                self.bot_id, BOT_STATUS_RUNNING
            )
            await self._client.send_bot_log(
                self.bot_id,
                "Bot running.",
                correlation_id=correlation_id,
            )

            # Strategy start (places initial orders etc.).
            await strategy.start()

            # Main loop – wait for ticks.
            while self._running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.exception("Bot %d error: %s", self.bot_id, exc)
            await self._client.send_error(
                self.bot_id, str(exc)
            )
            await self._client.send_bot_status(
                self.bot_id, BOT_STATUS_FAULT
            )
        finally:
            if self._running:
                self._running = False
                await self._client.send_bot_status(
                    self.bot_id, BOT_STATUS_STOPPED
                )

    async def stop(self) -> None:
        """Stop the bot gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._client.send_bot_status(
            self.bot_id, BOT_STATUS_STOPPED
        )

    async def _create_strategy(self):
        """Instantiate the strategy from config.

        Returns the strategy instance or None on failure.
        """
        from manager.strategies.registry import StrategyRegistry
        from manager.strategies.base import StrategyConfig

        strategy_name = self.config.get("strategy")
        strategy_cls = StrategyRegistry.get(strategy_name)
        if not strategy_cls:
            logger.error(
                "Unknown strategy '%s' for bot %d.",
                strategy_name,
                self.bot_id,
            )
            return None

        market = self.config.get("market", "")
        operator_id = self.config.get("operator_id", 0)
        budget_quote = self.config.get("budget_quote", 0.0)
        extra = self.config.get("strategy_params", {})

        # Build exchange client.
        from manager.exchanges.bitvavo.client import BitvavoClient

        exchange_config = self.config.get("exchange", {})
        exchange_client = BitvavoClient(
            api_key=exchange_config.get("api_key", ""),
            api_secret=exchange_config.get("api_secret", ""),
        )
        await exchange_client.connect()
        await exchange_client.authenticate()

        strategy_config = StrategyConfig(
            market=market,
            operator_id=operator_id,
            budget_quote=budget_quote,
            extra=extra,
        )

        return strategy_cls(exchange_client, strategy_config)
