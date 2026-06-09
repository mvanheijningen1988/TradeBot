"""Abstract strategy interface.

All trading strategies must subclass Strategy and implement its
abstract methods.  Strategies are exchange-agnostic—they interact
with the market only through an ExchangeClient instance.
"""

import abc
import re
from uuid import uuid4
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

from manager.exchanges.base import ExchangeClient

# Async callback: (message, level, correlation_id) -> None
LogCallback = Callable[[str, str, Optional[str]], Coroutine[Any, Any, None]]

# Async callback: (order_data_dict) -> None
OrderCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]

# Async callback: (budget_data_dict) -> None
BudgetCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class StrategyState(str, Enum):
    """Lifecycle states for a strategy instance."""

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class StrategyConfig:
    """Base configuration shared by all strategies.

    Each strategy subclass should define its own config dataclass that
    inherits from this one.
    """

    market: str
    operator_id: int
    budget_quote: float
    reference_id: str = ""
    profit_mode: str = "withdraw"
    profit_skim_pct: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class Strategy(abc.ABC):
    """Base class for all trading strategy implementations."""

    def __init__(
        self,
        config: StrategyConfig,
        exchange: ExchangeClient,
    ) -> None:
        self._config = config
        self._exchange = exchange
        self._state = StrategyState.IDLE
        self._log_callback: Optional[LogCallback] = None
        self._order_callback: Optional[OrderCallback] = None
        self._budget_callback: Optional[BudgetCallback] = None
        self._correlation_id: Optional[str] = None

    def set_log_callback(
        self, callback: LogCallback, correlation_id: Optional[str] = None
    ) -> None:
        """Set a callback for sending log messages to the manager."""
        self._log_callback = callback
        self._correlation_id = correlation_id

    def set_order_callback(self, callback: OrderCallback) -> None:
        """Set a callback for reporting order events to the manager."""
        self._order_callback = callback

    def set_budget_callback(self, callback: BudgetCallback) -> None:
        """Set a callback for reporting budget trend snapshots."""
        self._budget_callback = callback

    def _next_client_order_id(self, prefix: str) -> str:
        """Return a Bitvavo-safe UUID client order id.

        Bitvavo validates ``clientOrderId`` as a UUID-shaped string. Keep the
        semantic ``prefix`` parameter for stable call sites, but send a plain
        UUID to the exchange.
        """
        return str(uuid4())

    @staticmethod
    def _normalize_client_order_id(value: str) -> str:
        """Keep client order ids within a safe exchange character set."""
        normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip())
        normalized = re.sub(r"-+", "-", normalized).strip("-")
        return normalized or "bot"

    @staticmethod
    def _truncate_client_order_id(value: str, limit: int = 50) -> str:
        """Cap client order ids so they stay within exchange limits."""
        if len(value) <= limit:
            return value
        return value[:limit].rstrip("-")

    async def _log(
        self, message: str, level: str = "INFO"
    ) -> None:
        """Log via callback (to manager/UI) and local logger."""
        if self._log_callback:
            await self._log_callback(message, level, self._correlation_id)

    async def _report_order(
        self,
        exchange_order_id: str,
        market: str,
        side: str,
        order_type: str,
        status: str,
        amount: str = "",
        price: str = "",
    ) -> None:
        """Report an order event via callback."""
        if self._order_callback:
            await self._order_callback({
                "exchange_order_id": exchange_order_id,
                "market": market,
                "side": side,
                "order_type": order_type,
                "status": status,
                "amount": amount,
                "price": price,
                "operator_id": self._config.operator_id,
            })

    async def _report_budget(
        self,
        balance: str,
        price: str,
    ) -> None:
        """Report a budget snapshot via callback.

        Args:
            balance: Mark-to-market bot equity in quote currency.
            price: Last observed market price used for valuation.
        """
        if self._budget_callback:
            await self._budget_callback({
                "balance": balance,
                "price": price,
            })

    @property
    def state(self) -> StrategyState:
        """Return the current lifecycle state for this strategy instance."""
        return self._state

    @property
    def config(self) -> StrategyConfig:
        """Return the runtime configuration used by this strategy."""
        return self._config

    @staticmethod
    @abc.abstractmethod
    def name() -> str:
        """Return the unique strategy name used for registration."""

    @staticmethod
    @abc.abstractmethod
    def description() -> str:
        """Return a short human-readable description."""

    @staticmethod
    @abc.abstractmethod
    def default_parameters() -> dict[str, Any]:
        """Return the default configurable parameters and their values."""

    @abc.abstractmethod
    async def start(self) -> None:
        """Start executing the strategy."""

    @abc.abstractmethod
    async def stop(self) -> None:
        """Gracefully stop the strategy and cancel pending orders."""

    @abc.abstractmethod
    async def on_tick(self, price: str) -> None:
        """React to a new market price tick."""

    @abc.abstractmethod
    async def on_order_filled(self, order_id: str) -> None:
        """React to one of the strategy's orders being filled."""

    @abc.abstractmethod
    def get_status(self) -> dict[str, Any]:
        """Return a snapshot of the strategy's current state and metrics."""
