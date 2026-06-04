"""Bitvavo WebSocket client implementation.

Connects to wss://ws.bitvavo.com/v2/ and provides the full exchange
interface via the Bitvavo WebSocket API.  Includes Bitvavo-specific
rate-limit tracking per call.
"""

import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable, Optional

import websockets
from websockets.asyncio.client import ClientConnection

from manager.exchanges.base import ExchangeClient
from manager.exchanges.bitvavo.rate_limiter import BitvavoRateLimiter
from manager.models import (
    AccountFees,
    Balance,
    BookEntry,
    MarketInfo,
    Order,
    OrderBook,
    OrderFill,
    OrderSide,
    OrderStatus,
    OrderType,
    TickerPrice,
    TimeInForce,
    Trade,
)

logger = logging.getLogger(__name__)

WS_ENDPOINT = "wss://ws.bitvavo.com/v2/"
DEFAULT_ACCESS_WINDOW = 10_000  # ms


class BitvavoClient(ExchangeClient):
    """Bitvavo exchange client using the WebSocket API.

    Authentication follows the Bitvavo HMAC-SHA256 flow documented at
    https://docs.bitvavo.com/docs/websocket-api/introduction/.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_window: int = DEFAULT_ACCESS_WINDOW,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_window = access_window

        self._ws: Optional[ClientConnection] = None
        self._request_id: int = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._authenticated = False
        self._rate_limiter = BitvavoRateLimiter()

        # Subscription callbacks: channel -> {market -> callback}
        self._subscriptions: dict[str, dict[str, Callable]] = {}
        self._background_tasks: set[asyncio.Task] = set()

        self._recv_task: Optional[asyncio.Task] = None
        self._reconnect_lock = asyncio.Lock()

    # ── Connection lifecycle ─────────────────────────────────────

    async def connect(self) -> None:
        """Open the WebSocket connection and start the receive loop."""
        logger.info("Connecting to Bitvavo WebSocket at %s", WS_ENDPOINT)
        self._ws = await websockets.connect(WS_ENDPOINT)
        self._recv_task = asyncio.create_task(self._receive_loop())
        logger.info("Connected to Bitvavo WebSocket.")

    async def disconnect(self) -> None:
        """Close the WebSocket connection gracefully."""
        if self._recv_task:
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
            self._recv_task = None

        if self._ws:
            await self._ws.close()
            self._ws = None

        self._authenticated = False
        logger.info("Disconnected from Bitvavo WebSocket.")

    def _fail_pending_requests(self, exc: Exception) -> None:
        """Fail and clear all pending request futures."""
        for future in self._pending.values():
            if not future.done():
                future.set_exception(exc)
        self._pending.clear()

    async def reconnect(self) -> None:
        """Reconnect and re-authenticate the websocket session."""
        async with self._reconnect_lock:
            # Another coroutine may already have reconnected while this one
            # waited for the lock.
            if self._ws is not None and self._authenticated:
                return

            await self.disconnect()
            await self.connect()
            await self.authenticate()

    async def authenticate(self) -> None:
        """Authenticate the WebSocket connection with HMAC-SHA256."""
        timestamp = int(time.time() * 1000)
        signature = self._create_signature(timestamp)

        response = await self._send_action("authenticate", {
            "key": self._api_key,
            "signature": signature,
            "timestamp": timestamp,
            "window": self._access_window,
        })

        if response.get("authenticated"):
            self._authenticated = True
            logger.info("Bitvavo WebSocket authenticated successfully.")
        else:
            error = response.get("errorCode", "unknown")
            raise ConnectionError(
                f"Bitvavo authentication failed: {error}"
            )

    def _create_signature(self, timestamp: int) -> str:
        """Create HMAC-SHA256 signature for WebSocket authentication."""
        string = f"{timestamp}GET/v2/websocket"
        return hmac.new(
            self._api_secret.encode("utf-8"),
            string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    # ── Internal messaging ───────────────────────────────────────

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_action(
        self,
        action: str,
        body: dict[str, Any],
        rate_limit: bool = True,
        has_market: bool = True,
    ) -> dict:
        """Send an action message and wait for the response.

        Args:
            action: The Bitvavo action name (e.g. 'privateCreateOrder').
            body: Request body parameters.
            rate_limit: Whether to apply rate limiting.
            has_market: Whether a market parameter is present (affects
                        rate limit weight for some endpoints).

        Returns:
            The parsed JSON response dict.
        """
        for attempt in range(2):
            if self._ws is None:
                await self.connect()

            # Authenticate lazily for private actions, but avoid recursion
            # while sending the authenticate action itself.
            if action != "authenticate" and not self._authenticated:
                await self.authenticate()

            if rate_limit:
                await self._rate_limiter.acquire(action, has_market)

            request_id = self._next_request_id()
            payload = dict(body)
            payload["action"] = action
            payload["requestId"] = request_id

            future: asyncio.Future = asyncio.get_event_loop().create_future()
            self._pending[request_id] = future

            message = json.dumps(payload)
            logger.debug("WS SEND [%d]: %s", request_id, action)

            try:
                await self._ws.send(message)
                response = await asyncio.wait_for(future, timeout=30.0)
            except websockets.ConnectionClosed as exc:
                self._pending.pop(request_id, None)
                if attempt == 0:
                    logger.warning(
                        "Bitvavo WS disconnected during %s; reconnecting.",
                        action,
                    )
                    self._ws = None
                    self._authenticated = False
                    await self.reconnect()
                    continue
                raise ConnectionError(
                    f"Bitvavo websocket disconnected during {action}: {exc}"
                ) from exc
            except asyncio.TimeoutError:
                self._pending.pop(request_id, None)
                raise TimeoutError(
                    f"Bitvavo request {action} (id={request_id}) timed out."
                )

            if "errorCode" in response:
                raise RuntimeError(
                    f"Bitvavo error {response['errorCode']}: "
                    f"{response.get('error', 'unknown')}"
                )

            return response

        raise ConnectionError(f"Failed to execute Bitvavo action {action}.")

    async def _receive_loop(self) -> None:
        """Background task that dispatches incoming WebSocket messages."""
        try:
            async for raw in self._ws:
                data = json.loads(raw)
                self._dispatch(data)
        except websockets.ConnectionClosed as exc:
            logger.warning("Bitvavo WebSocket connection closed: %s", exc)
            self._ws = None
            self._authenticated = False
            self._fail_pending_requests(exc)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in Bitvavo receive loop.")

    def _dispatch(self, data: dict) -> None:
        """Route an incoming message to the correct handler."""
        # Response to a request-id based call.
        request_id = data.get("requestId")
        if request_id is not None and request_id in self._pending:
            future = self._pending.pop(request_id)
            if not future.done():
                future.set_result(data)
            return

        # Authentication response (no requestId).
        action = data.get("action")
        if action == "authenticate":
            # Resolve the pending authenticate future if any.
            rid_to_pop: Optional[int] = None
            for rid, fut in self._pending.items():
                if not fut.done():
                    fut.set_result(data)
                    rid_to_pop = rid
                    break
            if rid_to_pop is not None:
                self._pending.pop(rid_to_pop, None)
            return

        # Subscription event.
        event = data.get("event")
        if event == "ticker":
            market = data.get("market", "")
            cbs = self._subscriptions.get("ticker", {})
            cb = cbs.get(market)
            if cb:
                task = asyncio.create_task(self._safe_callback(cb, data))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            return

        logger.debug("Unhandled message: %s", data)

    async def _safe_callback(
        self,
        callback: Callable,
        data: dict,
    ) -> None:
        """Invoke a callback, catching and logging exceptions."""
        try:
            result = callback(data)
            if asyncio.iscoroutine(result):
                await result
        except Exception:
            logger.exception("Error in subscription callback.")

    # ── Market data ──────────────────────────────────────────────

    async def get_markets(
        self, market: Optional[str] = None
    ) -> list[MarketInfo]:
        body: dict[str, Any] = {}
        if market:
            body["market"] = market
        response = await self._send_action(
            "getMarkets", body, has_market=market is not None
        )
        raw = response.get("response", [])
        if isinstance(raw, dict):
            raw = [raw]
        return [self._parse_market(m) for m in raw]

    async def get_order_book(
        self, market: str, depth: Optional[int] = None
    ) -> OrderBook:
        body: dict[str, Any] = {"market": market}
        if depth is not None:
            body["depth"] = depth
        response = await self._send_action("getBook", body)
        r = response["response"]
        return OrderBook(
            market=r["market"],
            nonce=r["nonce"],
            bids=[BookEntry(price=b[0], size=b[1]) for b in r.get("bids", [])],
            asks=[BookEntry(price=a[0], size=a[1]) for a in r.get("asks", [])],
        )

    async def get_trades(
        self,
        market: str,
        limit: int = 500,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> list[Trade]:
        body: dict[str, Any] = {"market": market, "limit": limit}
        if start is not None:
            body["start"] = start
        if end is not None:
            body["end"] = end
        response = await self._send_action("getTrades", body)
        raw = response.get("response", [])
        if isinstance(raw, dict):
            raw = [raw]
        return [
            Trade(
                trade_id=t["id"],
                timestamp=t["timestamp"],
                amount=t["amount"],
                price=t["price"],
                side=t["side"],
            )
            for t in raw
        ]

    async def get_ticker_price(self, market: str) -> TickerPrice:
        response = await self._send_action(
            "getTickerPrice", {"market": market}
        )
        r = response["response"]
        if isinstance(r, list):
            r = r[0]
        return TickerPrice(market=r["market"], price=r["price"])

    # ── Trading ──────────────────────────────────────────────────

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
        body: dict[str, Any] = {
            "market": market,
            "side": side.value,
            "orderType": order_type.value,
            "operatorId": operator_id,
        }
        if amount is not None:
            body["amount"] = amount
        if amount_quote is not None:
            body["amountQuote"] = amount_quote
        if price is not None:
            body["price"] = price
        if time_in_force != TimeInForce.GTC:
            body["timeInForce"] = time_in_force.value
        if post_only:
            body["postOnly"] = True
        if client_order_id:
            body["clientOrderId"] = client_order_id
        if trigger_amount is not None:
            body["triggerAmount"] = trigger_amount
        if trigger_type is not None:
            body["triggerType"] = trigger_type
        if trigger_reference is not None:
            body["triggerReference"] = trigger_reference

        response = await self._send_action("privateCreateOrder", body)
        return self._parse_order(response["response"])

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
        body: dict[str, Any] = {
            "market": market,
            "orderId": order_id,
            "operatorId": operator_id,
        }
        if amount is not None:
            body["amount"] = amount
        if amount_remaining is not None:
            body["amountRemaining"] = amount_remaining
        if price is not None:
            body["price"] = price
        if trigger_amount is not None:
            body["triggerAmount"] = trigger_amount
        if time_in_force is not None:
            body["timeInForce"] = time_in_force.value
        if post_only is not None:
            body["postOnly"] = post_only
        if client_order_id is not None:
            body["clientOrderId"] = client_order_id

        response = await self._send_action("privateUpdateOrder", body)
        return self._parse_order(response["response"])

    async def get_order(
        self,
        market: str,
        order_id: str,
        client_order_id: Optional[str] = None,
    ) -> Order:
        body: dict[str, Any] = {"market": market, "orderId": order_id}
        if client_order_id:
            body["clientOrderId"] = client_order_id
        response = await self._send_action("privateGetOrder", body)
        return self._parse_order(response["response"])

    async def get_open_orders(
        self, market: Optional[str] = None
    ) -> list[Order]:
        body: dict[str, Any] = {}
        if market:
            body["market"] = market
        response = await self._send_action(
            "privateGetOrdersOpen", body, has_market=market is not None
        )
        raw = response.get("response", [])
        if isinstance(raw, dict):
            raw = [raw]
        return [self._parse_order(o) for o in raw]

    async def get_orders(
        self,
        market: str,
        limit: int = 500,
        start: Optional[int] = None,
        end: Optional[int] = None,
    ) -> list[Order]:
        body: dict[str, Any] = {"market": market, "limit": limit}
        if start is not None:
            body["start"] = start
        if end is not None:
            body["end"] = end
        response = await self._send_action("privateGetOrders", body)
        raw = response.get("response", [])
        if isinstance(raw, dict):
            raw = [raw]
        return [self._parse_order(o) for o in raw]

    async def cancel_order(
        self,
        market: str,
        order_id: str,
        operator_id: int,
        client_order_id: Optional[str] = None,
    ) -> dict:
        body: dict[str, Any] = {
            "market": market,
            "orderId": order_id,
            "operatorId": operator_id,
        }
        if client_order_id:
            body["clientOrderId"] = client_order_id
        response = await self._send_action("privateCancelOrder", body)
        return response.get("response", {})

    async def cancel_orders(
        self, market: str, operator_id: int
    ) -> list[dict]:
        body: dict[str, Any] = {
            "market": market,
            "operatorId": operator_id,
        }
        response = await self._send_action(
            "privateCancelOrders", body, has_market=True
        )
        raw = response.get("response", [])
        if isinstance(raw, dict):
            raw = [raw]
        return raw

    # ── Account ──────────────────────────────────────────────────

    async def get_account_fees(self) -> AccountFees:
        response = await self._send_action("privateGetAccount", {})
        fees = response["response"]["fees"]
        return AccountFees(
            taker=fees["taker"],
            maker=fees["maker"],
            volume=fees["volume"],
        )

    async def get_balance(
        self, symbol: Optional[str] = None
    ) -> list[Balance]:
        body: dict[str, Any] = {}
        if symbol:
            body["symbol"] = symbol
        response = await self._send_action("privateGetBalance", body)
        raw = response.get("response", [])
        if isinstance(raw, dict):
            raw = [raw]
        return [
            Balance(
                symbol=b["symbol"],
                available=b["available"],
                in_order=b["inOrder"],
            )
            for b in raw
        ]

    # ── Subscriptions ────────────────────────────────────────────

    async def subscribe_ticker(
        self, markets: list[str], callback: Callable
    ) -> None:
        if "ticker" not in self._subscriptions:
            self._subscriptions["ticker"] = {}
        for m in markets:
            self._subscriptions["ticker"][m] = callback

        msg = {
            "action": "subscribe",
            "channels": [{"name": "ticker", "markets": markets}],
        }
        await self._ws.send(json.dumps(msg))
        logger.info("Subscribed to ticker for %s", markets)

    async def unsubscribe_ticker(self, markets: list[str]) -> None:
        msg = {
            "action": "unsubscribe",
            "channels": [{"name": "ticker", "markets": markets}],
        }
        await self._ws.send(json.dumps(msg))
        for m in markets:
            self._subscriptions.get("ticker", {}).pop(m, None)
        logger.info("Unsubscribed from ticker for %s", markets)

    # ── Rate limiter access ──────────────────────────────────────

    @property
    def rate_limiter(self) -> BitvavoRateLimiter:
        """Expose the Bitvavo-specific rate limiter for inspection."""
        return self._rate_limiter

    # ── Parsers ──────────────────────────────────────────────────

    @staticmethod
    def _parse_market(data: dict) -> MarketInfo:
        return MarketInfo(
            market=data["market"],
            base=data["base"],
            quote=data["quote"],
            status=data.get("status", "trading"),
            min_order_base=data.get("minOrderInBaseAsset", "0"),
            min_order_quote=data.get("minOrderInQuoteAsset", "0"),
            max_order_base=data.get("maxOrderInBaseAsset", "0"),
            max_order_quote=data.get("maxOrderInQuoteAsset", "0"),
            quantity_decimals=data.get("quantityDecimals", 8),
            notional_decimals=data.get("notionalDecimals", 2),
            tick_size=data.get("tickSize", "0.01"),
            max_open_orders=data.get("maxOpenOrders", 100),
            fee_category=data.get("feeCategory", "A"),
            order_types=data.get("orderTypes", []),
        )

    @staticmethod
    def _parse_order(data: dict) -> Order:
        fills = []
        for f in data.get("fills", []):
            fills.append(OrderFill(
                fill_id=f.get("id", ""),
                timestamp=f.get("timestamp", 0),
                amount=f.get("amount", "0"),
                price=f.get("price", "0"),
                taker=f.get("taker", False),
                fee=f.get("fee", "0"),
                fee_currency=f.get("feeCurrency", ""),
                settled=f.get("settled", False),
            ))

        return Order(
            order_id=data["orderId"],
            market=data["market"],
            side=OrderSide(data["side"]),
            order_type=OrderType(data["orderType"]),
            status=OrderStatus(data["status"]),
            created=data.get("created", 0),
            updated=data.get("updated", 0),
            amount=data.get("amount"),
            amount_remaining=data.get("amountRemaining"),
            price=data.get("price"),
            amount_quote=data.get("amountQuote"),
            amount_quote_remaining=data.get("amountQuoteRemaining"),
            on_hold=data.get("onHold"),
            on_hold_currency=data.get("onHoldCurrency"),
            trigger_price=data.get("triggerPrice"),
            trigger_amount=data.get("triggerAmount"),
            trigger_type=data.get("triggerType"),
            trigger_reference=data.get("triggerReference"),
            filled_amount=data.get("filledAmount", "0"),
            filled_amount_quote=data.get("filledAmountQuote", "0"),
            fee_paid=data.get("feePaid", "0"),
            fee_currency=data.get("feeCurrency", ""),
            fills=fills,
            self_trade_prevention=data.get(
                "selfTradePrevention", "decrementAndCancel"
            ),
            time_in_force=data.get("timeInForce", "GTC"),
            post_only=data.get("postOnly", False),
            visible=data.get("visible", True),
            client_order_id=data.get("clientOrderId"),
            operator_id=data.get("operatorId"),
        )
