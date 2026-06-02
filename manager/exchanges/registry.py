"""Exchange registry for managing available exchange implementations."""

import logging
from typing import Type

from manager.exchanges.base import ExchangeClient

logger = logging.getLogger(__name__)


class ExchangeRegistry:
    """Central registry for exchange client implementations.

    Allows dynamic registration and lookup of exchange clients by name.
    """

    _exchanges: dict[str, Type[ExchangeClient]] = {}

    @classmethod
    def register(cls, name: str, exchange_cls: Type[ExchangeClient]) -> None:
        """Register an exchange client class under the given name."""
        if name in cls._exchanges:
            logger.warning(
                "Exchange '%s' is already registered, overwriting.", name
            )
        cls._exchanges[name] = exchange_cls
        logger.info("Registered exchange: %s", name)

    @classmethod
    def get(cls, name: str) -> Type[ExchangeClient]:
        """Retrieve an exchange client class by name."""
        if name not in cls._exchanges:
            available = ", ".join(cls._exchanges.keys()) or "(none)"
            raise KeyError(
                f"Exchange '{name}' not found. Available: {available}"
            )
        return cls._exchanges[name]

    @classmethod
    def list_exchanges(cls) -> list[str]:
        """Return names of all registered exchanges."""
        return list(cls._exchanges.keys())
