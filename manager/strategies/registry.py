"""Strategy registry for managing available strategy implementations."""

import logging
from typing import Type

from manager.strategies.base import Strategy

logger = logging.getLogger(__name__)


class StrategyRegistry:
    """Central registry for strategy implementations.

    Allows dynamic registration and lookup of strategies by name.
    Strategies self-register via their ``name()`` class method.
    """

    _strategies: dict[str, Type[Strategy]] = {}

    @classmethod
    def register(cls, strategy_cls: Type[Strategy]) -> None:
        """Register a strategy class using its ``name()``."""
        name = strategy_cls.name()
        if name in cls._strategies:
            logger.warning(
                "Strategy '%s' is already registered, overwriting.", name
            )
        cls._strategies[name] = strategy_cls
        logger.info("Registered strategy: %s", name)

    @classmethod
    def get(cls, name: str) -> Type[Strategy]:
        """Retrieve a strategy class by name."""
        if name not in cls._strategies:
            available = ", ".join(cls._strategies.keys()) or "(none)"
            raise KeyError(
                f"Strategy '{name}' not found. Available: {available}"
            )
        return cls._strategies[name]

    @classmethod
    def list_strategies(cls) -> list[dict]:
        """Return metadata for all registered strategies."""
        return [
            {
                "name": s.name(),
                "description": s.description(),
                "default_parameters": s.default_parameters(),
            }
            for s in cls._strategies.values()
        ]

    @classmethod
    def auto_discover(cls) -> None:
        """Import and register all built-in strategies."""
        from manager.strategies.dca import DCAStrategy
        from manager.strategies.grid_trading import GridStrategy
        from manager.strategies.martingale import MartingaleStrategy

        for strategy_cls in [GridStrategy, DCAStrategy, MartingaleStrategy]:
            cls.register(strategy_cls)
