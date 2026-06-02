"""Data models shared across the TradeBot system."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    """Order direction."""

    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stopLoss"
    STOP_LOSS_LIMIT = "stopLossLimit"
    TAKE_PROFIT = "takeProfit"
    TAKE_PROFIT_LIMIT = "takeProfitLimit"


class OrderStatus(str, Enum):
    """Order lifecycle states."""

    NEW = "new"
    AWAITING_TRIGGER = "awaitingTrigger"
    CANCELED = "canceled"
    EXPIRED = "expired"
    FILLED = "filled"
    PARTIALLY_FILLED = "partiallyFilled"


class TimeInForce(str, Enum):
    """Order time-in-force policies."""

    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


@dataclass
class MarketInfo:
    """Exchange market metadata."""

    market: str
    base: str
    quote: str
    status: str
    min_order_base: str
    min_order_quote: str
    max_order_base: str
    max_order_quote: str
    quantity_decimals: int
    notional_decimals: int
    tick_size: str
    max_open_orders: int
    fee_category: str
    order_types: list[str] = field(default_factory=list)


@dataclass
class OrderFill:
    """Single fill within an order."""

    fill_id: str
    timestamp: int
    amount: str
    price: str
    taker: bool
    fee: str = "0"
    fee_currency: str = ""
    settled: bool = False


@dataclass
class Order:
    """Represents an exchange order."""

    order_id: str
    market: str
    side: OrderSide
    order_type: OrderType
    status: OrderStatus
    created: int
    updated: int
    amount: Optional[str] = None
    amount_remaining: Optional[str] = None
    price: Optional[str] = None
    amount_quote: Optional[str] = None
    amount_quote_remaining: Optional[str] = None
    on_hold: Optional[str] = None
    on_hold_currency: Optional[str] = None
    trigger_price: Optional[str] = None
    trigger_amount: Optional[str] = None
    trigger_type: Optional[str] = None
    trigger_reference: Optional[str] = None
    filled_amount: str = "0"
    filled_amount_quote: str = "0"
    fee_paid: str = "0"
    fee_currency: str = ""
    fills: list[OrderFill] = field(default_factory=list)
    self_trade_prevention: str = "decrementAndCancel"
    time_in_force: str = "GTC"
    post_only: bool = False
    visible: bool = True
    client_order_id: Optional[str] = None
    operator_id: Optional[int] = None


@dataclass
class Balance:
    """Account balance for a single asset."""

    symbol: str
    available: str
    in_order: str


@dataclass
class AccountFees:
    """Trading fee schedule."""

    taker: str
    maker: str
    volume: str


@dataclass
class TickerPrice:
    """Latest trade price for a market."""

    market: str
    price: str


@dataclass
class BookEntry:
    """Single order book entry (bid or ask)."""

    price: str
    size: str


@dataclass
class OrderBook:
    """Order book snapshot."""

    market: str
    nonce: int
    bids: list[BookEntry] = field(default_factory=list)
    asks: list[BookEntry] = field(default_factory=list)


@dataclass
class Trade:
    """Public trade."""

    trade_id: str
    timestamp: int
    amount: str
    price: str
    side: str
