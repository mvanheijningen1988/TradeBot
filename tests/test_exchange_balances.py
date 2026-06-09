"""Tests for exchange balance enrichment helpers."""

from unittest.mock import AsyncMock

import pytest

from manager.api.exchanges import (
    _build_manager_allocation,
    _build_manager_in_order,
)
from manager.models import Order, OrderSide, OrderStatus, OrderType


def _make_order(
    order_id: str,
    market: str,
    side: OrderSide,
    operator_id: int,
    amount_remaining: str = "0",
    price: str = "0",
    amount_quote_remaining: str | None = None,
) -> Order:
    """Build a minimal order model instance for helper tests."""
    return Order(
        order_id=order_id,
        market=market,
        side=side,
        order_type=OrderType.LIMIT,
        status=OrderStatus.NEW,
        created=0,
        updated=0,
        operator_id=operator_id,
        amount_remaining=amount_remaining,
        price=price,
        amount_quote_remaining=amount_quote_remaining,
    )


def test_build_manager_allocation_groups_by_quote_symbol():
    """Aggregate quote budget and operator ids from exchange bot records."""
    exchange_bots = [
        {
            "market": "BTC-EUR",
            "budget_quote": "100",
            "operator_id": 10,
        },
        {
            "market": "ETH-EUR",
            "budget_quote": "25.5",
            "operator_id": 11,
        },
        {
            "market": "SOL-USD",
            "budget_quote": "9",
            "operator_id": 12,
        },
        {
            "market": "INVALID",
            "budget_quote": "999",
            "operator_id": 99,
        },
    ]

    allocated, operator_ids = _build_manager_allocation(exchange_bots)

    assert str(allocated["EUR"]) == "125.5"
    assert str(allocated["USD"]) == "9"
    assert operator_ids == {10, 11, 12}


@pytest.mark.asyncio
async def test_build_manager_in_order_aggregates_bot_owned_open_orders():
    """Count only bot-owned open orders and map locks to affected symbols."""
    orders = [
        _make_order(
            order_id="1",
            market="BTC-EUR",
            side=OrderSide.BUY,
            operator_id=11,
            amount_remaining="0.1",
            price="50000",
        ),
        _make_order(
            order_id="2",
            market="ETH-EUR",
            side=OrderSide.SELL,
            operator_id=11,
            amount_remaining="2",
        ),
        _make_order(
            order_id="3",
            market="BTC-EUR",
            side=OrderSide.BUY,
            operator_id=11,
            amount_remaining="0.2",
            price="60000",
            amount_quote_remaining="30",
        ),
        _make_order(
            order_id="4",
            market="ADA-EUR",
            side=OrderSide.BUY,
            operator_id=99,
            amount_remaining="100",
            price="1",
        ),
    ]

    client = type("ClientStub", (), {})()
    client.get_open_orders = AsyncMock(return_value=orders)
    in_order = await _build_manager_in_order(
        client,
        {11},
        {"1", "2", "3"},
    )

    assert str(in_order["EUR"]) == "5030.0"
    assert str(in_order["ETH"]) == "2"
    assert "ADA" not in in_order


@pytest.mark.asyncio
async def test_build_manager_in_order_prefers_on_hold_for_buy_quote():
    """Use exchange on-hold quote value when available for BUY orders."""
    order = _make_order(
        order_id="buy-1",
        market="XRP-EUR",
        side=OrderSide.BUY,
        operator_id=42,
        amount_remaining="30.76923",
        price="0.97500",
    )
    order.on_hold = "30.08"
    order.on_hold_currency = "EUR"

    client = type("ClientStub", (), {})()
    client.get_open_orders = AsyncMock(return_value=[order])

    in_order = await _build_manager_in_order(client, {42}, {"buy-1"})

    assert str(in_order["EUR"]) == "30.08"


@pytest.mark.asyncio
async def test_build_manager_in_order_excludes_manual_same_operator_order():
    """Exclude orders that are not known in bot order history."""
    bot_order = _make_order(
        order_id="bot-order-1",
        market="XRP-EUR",
        side=OrderSide.SELL,
        operator_id=77,
        amount_remaining="10",
    )
    manual_order = _make_order(
        order_id="manual-order-1",
        market="XRP-EUR",
        side=OrderSide.SELL,
        operator_id=77,
        amount_remaining="56.737588",
    )

    client = type("ClientStub", (), {})()
    client.get_open_orders = AsyncMock(
        return_value=[bot_order, manual_order]
    )

    in_order = await _build_manager_in_order(
        client,
        {77},
        {"bot-order-1"},
    )

    assert str(in_order["XRP"]) == "10"
