"""Abstract exchange client interface.

All exchange implementations must subclass ExchangeClient and implement
its abstract methods. This ensures strategies remain exchange-agnostic.
"""

import abc
from typing import Optional

from manager.models import (
    AccountFees,
    Balance,
    MarketInfo,
    Order,
    OrderBook,
    OrderSide,
    OrderType,
    TickerPrice,
    TimeInForce,
    Trade,
)


class ExchangeClient(abc.ABC):
    """Base class for all exchange client implementations."""

    @abc.abstractmethod
    async def connect(self) -> None:
        """Establish connection to the exchange."""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the exchange."""

    @abc.abstractmethod
    async def authenticate(self) -> None:
        """Authenticate with the exchange."""

    # ── Market data ──────────────────────────────────────────────

    @abc.abstractmethod
    async def get_markets(
        self, market: Optional[str] = None
    ) -> list[MarketInfo]:
        """Return market information for one or all markets."""

    @abc.abstractmethod
    async def get_order_book(
        self, market: str, depth: Optional[int] = None
    ) -> OrderBook:
        """Return the order book for a market."""

    @abc.abstractmethod
    async def get_trades(
        self,
        market: str,
        limit: int = 500,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> list[Trade]:
        """Return recent public trades for a market."""

    @abc.abstractmethod
    async def get_ticker_price(
        self, market: str
    ) -> TickerPrice:
        """Return the latest trade price for a market."""

    # ── Trading ──────────────────────────────────────────────────

    @abc.abstractmethod
    async def create_order(
        self,
        market: str,
        side: OrderSide,
        order_type: OrderType,
        operator_id: int,
        amount: Optional[str] = None,
        amount_quote: Optional[str] = None,
        price: Optional[str] = None,
        time_in_force: TimeInForce = TimeInForce.GTC,
        post_only: bool = False,
        client_order_id: Optional[str] = None,
        trigger_amount: Optional[str] = None,
        trigger_type: Optional[str] = None,
        trigger_reference: Optional[str] = None,
    ) -> Order:
        """Place a new order."""

    @abc.abstractmethod
    async def update_order(
        self,
        market: str,
        order_id: str,
        operator_id: int,
        amount: Optional[str] = None,
        amount_remaining: Optional[str] = None,
        price: Optional[str] = None,
        trigger_amount: Optional[str] = None,
        time_in_force: Optional[TimeInForce] = None,
        post_only: Optional[bool] = None,
        client_order_id: Optional[str] = None,
    ) -> Order:
        """Update an existing order."""

    @abc.abstractmethod
    async def get_order(
        self,
        market: str,
        order_id: str,
        client_order_id: Optional[str] = None,
    ) -> Order:
        """Retrieve a single order."""

    @abc.abstractmethod
    async def get_open_orders(
        self, market: Optional[str] = None
    ) -> list[Order]:
        """Return all open orders, optionally filtered by market."""

    @abc.abstractmethod
    async def get_orders(
        self,
        market: str,
        limit: int = 500,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> list[Order]:
        """Return historical orders for a market."""

    @abc.abstractmethod
    async def cancel_order(
        self,
        market: str,
        order_id: str,
        operator_id: int,
        client_order_id: Optional[str] = None,
    ) -> dict:
        """Cancel a single order."""

    @abc.abstractmethod
    async def cancel_orders(
        self, market: str, operator_id: int
    ) -> list[dict]:
        """Cancel all orders for a market."""

    # ── Account ──────────────────────────────────────────────────

    @abc.abstractmethod
    async def get_account_fees(self) -> AccountFees:
        """Return the current account fee schedule."""

    @abc.abstractmethod
    async def get_balance(
        self, symbol: Optional[str] = None
    ) -> list[Balance]:
        """Return account balances."""

    # ── Subscriptions ────────────────────────────────────────────

    @abc.abstractmethod
    async def subscribe_ticker(
        self, markets: list[str], callback
    ) -> None:
        """Subscribe to real-time ticker updates."""

    @abc.abstractmethod
    async def unsubscribe_ticker(
        self, markets: list[str]
    ) -> None:
        """Unsubscribe from ticker updates."""
