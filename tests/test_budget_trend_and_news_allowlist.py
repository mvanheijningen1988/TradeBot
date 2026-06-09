"""Regression tests for budget trend valuation and RSS allowlist behavior."""

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import asyncio

from manager.models import Order, OrderSide, OrderStatus, OrderType
from manager.strategies.dca import DCAConfig, DCAStrategy
from manager.strategies.grid_trading import GridConfig, GridStrategy
from manager.strategies.martingale import MartingaleConfig, MartingaleStrategy
from manager.strategies.base import StrategyState
from services.news_engine.collector.news_collector import NewsCollector
from services.news_engine.collector.rss_client import RssClient
from services.news_engine.config.news_sources import NewsSource


@dataclass
class _FakeFeedResponse:
    status: int = 200
    body: str = "<rss><channel><title>x</title></channel></rss>"

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        await asyncio.sleep(0)
        return self.body


class _FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.called_urls: list[str] = []

    def get(self, url: str):
        self.called_urls.append(url)
        return _FakeFeedResponse()


@pytest.mark.asyncio
async def test_rss_client_accepts_runtime_configured_feed_url() -> None:
    """Custom feeds from settings should be fetchable after allowlist sync."""
    client = RssClient()
    fake_session = _FakeSession()
    client._session = fake_session  # type: ignore[attr-defined]

    custom_url = "https://www.crypto-insiders.nl/feed"
    client.set_allowed_urls([custom_url])
    await client.fetch_feed(custom_url)

    assert fake_session.called_urls == [custom_url]


def test_news_collector_syncs_allowlist_from_sources() -> None:
    """Collector should push RSS source URLs to client allowlist."""
    client = RssClient()
    sources = [
        NewsSource(
            name="Custom",
            url="https://www.crypto-insiders.nl/bitcoin/feed/",
            source_type="rss",
            weight=1.0,
        )
    ]

    collector = NewsCollector(sources=sources, rss_client=client)

    assert client._allowed_urls == {sources[0].url}  # noqa: SLF001

    updated = [
        NewsSource(
            name="Other",
            url="https://www.crypto-insiders.nl/nieuws/ripple/feed",
            source_type="rss",
            weight=1.0,
        )
    ]
    collector.update_sources(updated)
    assert client._allowed_urls == {updated[0].url}  # noqa: SLF001


@pytest.mark.asyncio
async def test_dca_budget_snapshot_moves_with_price() -> None:
    """After buy, mark-to-market equity must follow price down and up."""
    exchange = SimpleNamespace()
    cfg = DCAConfig(
        market="XRP-EUR",
        operator_id=1,
        budget_quote=100.0,
        amount_per_order=100.0,
        interval="daily",
    )
    strategy = DCAStrategy(cfg, exchange)
    strategy._state = StrategyState.RUNNING  # type: ignore[attr-defined]
    strategy._quote_balance = Decimal("0")  # type: ignore[attr-defined]
    strategy._base_balance = Decimal("50")  # type: ignore[attr-defined]

    points: list[Decimal] = []

    async def _budget_cb(data):
        await asyncio.sleep(0)
        points.append(Decimal(str(data["balance"])))

    strategy.set_budget_callback(_budget_cb)

    await strategy.on_tick("1.8")
    await strategy.on_tick("2.2")

    assert points[0] == Decimal("90.0")
    assert points[1] == Decimal("110.0")


@pytest.mark.asyncio
async def test_grid_sell_fill_updates_quote_balance_profit_or_loss() -> None:
    """Sell fills should increase quote balance by realized proceeds."""
    cfg = GridConfig(
        market="XRP-EUR",
        operator_id=1,
        budget_quote=100.0,
        upper_price=3.0,
        lower_price=1.0,
        num_grids=2,
    )
    strategy = GridStrategy(cfg, SimpleNamespace())
    strategy._state = StrategyState.RUNNING  # type: ignore[attr-defined]
    strategy._grid_prices = [  # type: ignore[attr-defined]
        Decimal("1"),
        Decimal("2"),
        Decimal("3"),
    ]
    strategy._quote_balance = Decimal("0")  # type: ignore[attr-defined]
    strategy._base_balance = Decimal("50")  # type: ignore[attr-defined]

    strategy._place_order = AsyncMock(  # type: ignore[assignment]
        return_value=True
    )
    strategy._log = AsyncMock(return_value=None)  # type: ignore[assignment]

    profit_fill = Order(
        order_id="sell-profit",
        market="XRP-EUR",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        status=OrderStatus.FILLED,
        created=1,
        updated=1,
        filled_amount="50",
        filled_amount_quote="120",
        fee_paid="0",
        fee_currency="EUR",
    )
    await strategy._handle_sell_fill(  # type: ignore[attr-defined]
        order_id="sell-profit",
        idx=1,
        filled_price=Decimal("2"),
        investment_per_grid=Decimal("100"),
        filled_order=profit_fill,
    )
    assert strategy._quote_balance == Decimal("120")  # type: ignore[attr-defined]  # noqa: E501
    assert strategy._base_balance == Decimal("0")  # type: ignore[attr-defined]

    strategy._quote_balance = Decimal("0")  # type: ignore[attr-defined]
    strategy._base_balance = Decimal("50")  # type: ignore[attr-defined]
    loss_fill = Order(
        order_id="sell-loss",
        market="XRP-EUR",
        side=OrderSide.SELL,
        order_type=OrderType.LIMIT,
        status=OrderStatus.FILLED,
        created=1,
        updated=1,
        filled_amount="50",
        filled_amount_quote="80",
        fee_paid="0",
        fee_currency="EUR",
    )
    await strategy._handle_sell_fill(  # type: ignore[attr-defined]
        order_id="sell-loss",
        idx=1,
        filled_price=Decimal("2"),
        investment_per_grid=Decimal("100"),
        filled_order=loss_fill,
    )
    assert strategy._quote_balance == Decimal(
        "80"
    )  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_martingale_sell_updates_quote_balance() -> None:
    """Stop-loss sell should update quote balance from realized proceeds."""
    cfg = MartingaleConfig(
        market="XRP-EUR",
        operator_id=2,
        budget_quote=100.0,
        initial_amount_quote=100.0,
    )
    fill_order = Order(
        order_id="m-sell",
        market="XRP-EUR",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        status=OrderStatus.FILLED,
        created=1,
        updated=1,
        filled_amount="50",
        filled_amount_quote="110",
        fee_paid="0",
        fee_currency="EUR",
    )
    exchange = SimpleNamespace(
        create_order=AsyncMock(return_value=fill_order),
        cancel_order=AsyncMock(return_value={}),
    )

    strategy = MartingaleStrategy(cfg, exchange)
    strategy._total_base = Decimal("50")  # type: ignore[attr-defined]
    strategy._total_quote_spent = Decimal("100")  # type: ignore[attr-defined]
    strategy._base_balance = Decimal("50")  # type: ignore[attr-defined]
    strategy._quote_balance = Decimal("0")  # type: ignore[attr-defined]

    await strategy._execute_sell_all()  # type: ignore[attr-defined]

    assert strategy._quote_balance == Decimal(
        "110"
    )  # type: ignore[attr-defined]
    assert strategy._base_balance == Decimal("0")  # type: ignore[attr-defined]
