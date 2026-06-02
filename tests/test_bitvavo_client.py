"""Tests for the Bitvavo WebSocket client (unit tests with mocks)."""

import asyncio
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from manager.exchanges.bitvavo.client import BitvavoClient
from manager.models import OrderSide, OrderStatus, OrderType


class TestBitvavoSignature:
    """Verify HMAC-SHA256 signature generation."""

    def test_create_signature(self):
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
        assert sig == "653fc0505431c63a043273da4bd2f0927eae83948d796084f313e5d1131b0d6f"


class TestBitvavoParser:
    """Verify response parsing."""

    def test_parse_order(self):
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


class TestExchangeRegistry:
    """Verify exchange registration."""

    def test_register_bitvavo(self):
        from manager.exchanges.registry import ExchangeRegistry

        ExchangeRegistry.register("bitvavo", BitvavoClient)
        assert ExchangeRegistry.get("bitvavo") is BitvavoClient
        assert "bitvavo" in ExchangeRegistry.list_exchanges()
