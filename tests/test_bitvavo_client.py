"""Tests for the Bitvavo WebSocket client (unit tests with mocks)."""

import hashlib
import hmac
from unittest.mock import AsyncMock

import pytest

from manager.exchanges.bitvavo.client import BitvavoClient
from manager.models import OrderSide, OrderStatus, OrderType


class TestBitvavoSignature:
    """Verify HMAC-SHA256 signature generation."""

    def test_create_signature(self):
        """Build a deterministic signature and compare with local HMAC."""
        client = BitvavoClient(
            api_key="testkey", api_secret="bitvavo"
        )
        timestamp = 1548175200641
        sig = client._create_signature(timestamp)

        # Reproduce expected signature.
        string = f"{timestamp}GET/v2/websocket"
        expected = hmac.new(
            b"bitvavo", string.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        assert sig == expected

    def test_signature_matches_docs_example(self):
        """Validate against the example in the Bitvavo docs."""
        client = BitvavoClient(
            api_key="testkey", api_secret="bitvavo"
        )
        sig = client._create_signature(1548175200641)
        expected_sig = (
            "653fc0505431c63a043273da4bd2f0927eae83948d796084"
            "f313e5d1131b0d6f"
        )
        assert sig == expected_sig


class TestBitvavoParser:
    """Verify parsing helpers for order and market payloads."""

    def test_parse_order(self):
        """Parse a limit order payload into a typed Order object."""
        data = {
            "orderId": "abc-123",
            "market": "BTC-EUR",
            "side": "buy",
            "orderType": "limit",
            "status": "new",
            "created": 1706100650751,
            "updated": 1706100650751,
            "amount": "0.1",
            "price": "50000",
            "filledAmount": "0",
            "filledAmountQuote": "0",
            "feePaid": "0",
            "feeCurrency": "EUR",
            "fills": [],
            "timeInForce": "GTC",
            "postOnly": False,
            "visible": True,
        }
        order = BitvavoClient._parse_order(data)
        assert order.order_id == "abc-123"
        assert order.market == "BTC-EUR"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.LIMIT
        assert order.status == OrderStatus.NEW
        assert order.amount == "0.1"
        assert order.price == "50000"

    def test_parse_order_with_fills(self):
        """Parse an order payload containing fill information."""
        data = {
            "orderId": "abc-456",
            "market": "ETH-EUR",
            "side": "sell",
            "orderType": "market",
            "status": "filled",
            "created": 1706100650751,
            "updated": 1706100650752,
            "filledAmount": "1.5",
            "filledAmountQuote": "4500",
            "feePaid": "2.25",
            "feeCurrency": "EUR",
            "fills": [
                {
                    "id": "fill-1",
                    "timestamp": 1706100650751,
                    "amount": "1.5",
                    "price": "3000",
                    "taker": True,
                    "fee": "2.25",
                    "feeCurrency": "EUR",
                    "settled": True,
                }
            ],
            "timeInForce": "GTC",
        }
        order = BitvavoClient._parse_order(data)
        assert order.status == OrderStatus.FILLED
        assert len(order.fills) == 1
        assert order.fills[0].amount == "1.5"
        assert order.fills[0].taker is True

    def test_parse_market(self):
        """Parse market metadata payload into a MarketInfo object."""
        data = {
            "market": "BTC-EUR",
            "base": "BTC",
            "quote": "EUR",
            "status": "trading",
            "minOrderInBaseAsset": "0.00006100",
            "minOrderInQuoteAsset": "5.00",
            "maxOrderInBaseAsset": "1000000000.00000000",
            "maxOrderInQuoteAsset": "1000000000.00",
            "quantityDecimals": 8,
            "notionalDecimals": 2,
            "tickSize": "0.00001",
            "maxOpenOrders": 100,
            "feeCategory": "A",
            "orderTypes": ["market", "limit"],
        }
        market = BitvavoClient._parse_market(data)
        assert market.market == "BTC-EUR"
        assert market.base == "BTC"
        assert market.quote == "EUR"
        assert market.quantity_decimals == 8
        assert market.tick_size == "0.00001"


class TestBitvavoFormatting:
    """Verify outbound numeric formatting for order payloads."""

    def test_format_decimal_floor_max_8_digits(self):
        """Trim decimals beyond 8 digits by rounding down."""
        value = BitvavoClient._format_decimal_floor("1.123456789")
        assert value == "1.12345678"

    def test_format_decimal_floor_removes_trailing_zeros(self):
        """Keep a plain non-scientific numeric string."""
        value = BitvavoClient._format_decimal_floor("2.340000000")
        assert value == "2.34"

    def test_format_decimal_floor_small_value(self):
        """Handle very small inputs with 8-digit floor precision."""
        value = BitvavoClient._format_decimal_floor("0.000000019")
        assert value == "0.00000001"

    def test_format_decimal_floor_zero_decimals(self):
        """Support whole-number floor mode when decimals are 0."""
        value = BitvavoClient._format_decimal_floor("12.99", decimals=0)
        assert value == "12"

    def test_format_decimal_floor_two_decimals(self):
        """Support market-level decimal clamps below 8 digits."""
        value = BitvavoClient._format_decimal_floor("12.999", decimals=2)
        assert value == "12.99"


class TestBitvavoOrderPayloadFormatting:
    """Verify create/update order payloads apply amount precision rules."""

    @pytest.mark.asyncio
    async def test_create_order_amount_uses_market_quantity_decimals(self):
        """Clamp amount to min(8, quantityDecimals) before submit."""
        client = BitvavoClient(api_key="k", api_secret="s")
        client._get_amount_decimals = AsyncMock(return_value=2)

        client._send_action = AsyncMock(return_value={
            "response": {
                "orderId": "o-1",
                "market": "BTC-EUR",
                "side": "buy",
                "orderType": "limit",
                "status": "new",
                "created": 1,
                "updated": 1,
            }
        })

        await client.create_order(
            market="BTC-EUR",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            operator_id=1,
            amount="1.2399",
            price="100",
        )

        args = client._send_action.await_args.args
        assert args[0] == "privateCreateOrder"
        body = args[1]
        assert body["amount"] == "1.23"

    @pytest.mark.asyncio
    async def test_update_order_amount_remaining_uses_market_decimals(self):
        """Clamp amountRemaining using same market precision policy."""
        client = BitvavoClient(api_key="k", api_secret="s")
        client._get_amount_decimals = AsyncMock(return_value=3)

        client._send_action = AsyncMock(return_value={
            "response": {
                "orderId": "o-2",
                "market": "BTC-EUR",
                "side": "buy",
                "orderType": "limit",
                "status": "new",
                "created": 1,
                "updated": 1,
            }
        })

        await client.update_order(
            market="BTC-EUR",
            order_id="o-2",
            operator_id=1,
            amount="2.98765",
            amount_remaining="1.12399",
        )

        args = client._send_action.await_args.args
        assert args[0] == "privateUpdateOrder"
        body = args[1]
        assert body["amount"] == "2.987"
        assert body["amountRemaining"] == "1.123"


class TestExchangeRegistry:
    """Verify exchange registry wiring for Bitvavo client discovery."""

    def test_register_bitvavo(self):
        """Register Bitvavo and confirm lookup/list operations."""
        from manager.exchanges.registry import ExchangeRegistry

        ExchangeRegistry.register("bitvavo", BitvavoClient)
        assert ExchangeRegistry.get("bitvavo") is BitvavoClient
        assert "bitvavo" in ExchangeRegistry.list_exchanges()
