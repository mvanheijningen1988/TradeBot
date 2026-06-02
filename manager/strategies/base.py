"""Abstract strategy interface.

All trading strategies must subclass Strategy and implement its
abstract methods.  Strategies are exchange-agnostic—they interact
with the market only through an ExchangeClient instance.
"""

import abc
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from manager.exchanges.base import ExchangeClient


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

    @property
    def state(self) -> StrategyState:
        return self._state

    @property
    def config(self) -> StrategyConfig:
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
