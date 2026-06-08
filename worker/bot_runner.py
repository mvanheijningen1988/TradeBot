"""Bot runner – executes a strategy on the Worker Node.

Each BotRunner manages one bot, handling its lifecycle and reporting
status and logs back to the Manager.
"""

import asyncio
import contextlib
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
        """Initialize a runner for one bot.

        Args:
            bot_id: Bot identifier.
            config: Bot runtime configuration payload.
            client: Manager communication client.
        """
        self.bot_id = bot_id
        self.config = config
        self._client = client
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._cancel_strategy_on_exit = True
        self._report_stopped_on_exit = True

    async def run(self) -> None:
        """Run bot lifecycle until stopped or failed.

        The method initializes strategy/exchange dependencies, reports
        lifecycle states, and drives strategy tick updates.
        """
        correlation_id = str(uuid.uuid4())[:12]
        strategy = None
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

            # Wire strategy log callback to send logs to manager/UI.
            async def _strategy_log(
                message: str, level: str, corr_id: str | None
            ) -> None:
                await self._client.send_bot_log(
                    self.bot_id, message, level=level,
                    correlation_id=corr_id,
                )

            strategy.set_log_callback(_strategy_log, correlation_id)

            # Wire strategy order callback to persist orders via manager.
            async def _strategy_order(order_data: dict) -> None:
                await self._client.send_order_update(
                    self.bot_id, order_data
                )

            strategy.set_order_callback(_strategy_order)

            async def _strategy_budget(budget_data: dict) -> None:
                balance = budget_data.get("balance", "0")
                price = budget_data.get("price", "0")
                await self._client.send_budget_snapshot(
                    self.bot_id,
                    balance=str(balance),
                    price=str(price),
                )

            if hasattr(strategy, "set_budget_callback"):
                strategy.set_budget_callback(_strategy_budget)

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

            # Main loop – poll price and feed ticks to the strategy.
            while self._running:
                try:
                    ticker = await strategy._exchange.get_ticker_price(
                        strategy._config.market
                    )
                    await strategy.on_tick(ticker.price)
                except Exception as tick_exc:
                    logger.warning(
                        "Tick error for bot %d: %s", self.bot_id, tick_exc
                    )
                    await self._client.send_bot_log(
                        self.bot_id,
                        f"Tick error: {tick_exc}",
                        level="WARNING",
                        correlation_id=correlation_id,
                    )
                await asyncio.sleep(5)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Bot %d error: %s", self.bot_id, exc)
            await self._client.send_error(
                self.bot_id, str(exc)
            )
            await self._client.send_bot_status(
                self.bot_id, BOT_STATUS_FAULT
            )
        finally:
            # On explicit stop we cancel strategy orders; during worker
            # shutdown/restart we preserve exchange state for recovery.
            if strategy is not None:
                try:
                    if self._cancel_strategy_on_exit:
                        await strategy.stop()
                except Exception:
                    logger.exception(
                        "Bot %d strategy stop error.",
                        self.bot_id,
                    )
            self._running = False

    async def stop(
        self,
        report_stopped: bool = True,
        cancel_strategy: bool = True,
    ) -> None:
        """Stop the bot and optionally cancel strategy exchange state.

        Args:
            report_stopped: Whether to emit stopped status to manager.
            cancel_strategy: Whether to call ``strategy.stop()`` on exit.
        """
        self._report_stopped_on_exit = report_stopped
        self._cancel_strategy_on_exit = cancel_strategy
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        if self._report_stopped_on_exit:
            await self._client.send_bot_status(
                self.bot_id, BOT_STATUS_STOPPED
            )

    def attach_task(self, task: asyncio.Task) -> None:
        """Attach active runner task for coordinated cancellation.

        Args:
            task: Asyncio task executing ``run()`` wrapper logic.
        """
        self._task = task

    async def _create_strategy(self):
        """Instantiate the strategy from config.

        Returns:
            Strategy instance when config/registry resolution succeeds;
            otherwise ``None``.
        """
        from manager.strategies import StrategyRegistry
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

        # Build strategy-specific config with extra params as fields.
        config_cls = strategy_cls.__init__.__annotations__.get(
            "config", StrategyConfig
        )
        config_fields = {
            "market": market,
            "operator_id": operator_id,
            "budget_quote": budget_quote,
        }
        if extra and isinstance(extra, dict):
            config_fields.update(extra)

        try:
            strategy_config = config_cls(**config_fields)
        except TypeError:
            strategy_config = StrategyConfig(
                market=market,
                operator_id=operator_id,
                budget_quote=budget_quote,
                extra=extra,
            )

        return strategy_cls(strategy_config, exchange_client)
