"""Tests for strategy registry and base strategy functionality."""

from decimal import Decimal

import pytest

from manager.exchanges.base import ExchangeClient
from manager.models import Order, OrderSide, OrderStatus, OrderType
from manager.strategies.base import Strategy, StrategyConfig
from manager.strategies.dca import DCAStrategy
from manager.strategies.grid_trading import GridStrategy
from manager.strategies.martingale import MartingaleStrategy
from manager.strategies.registry import StrategyRegistry


class DummyExchange(ExchangeClient):
    """Minimal exchange stub for base-strategy unit tests."""

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def authenticate(self) -> None:
        return None

    async def get_markets(self, market=None):
        return []

    async def get_order_book(self, market: str, depth=None):
        raise NotImplementedError()

    async def get_trades(
        self, market: str, limit: int = 500, start=None, end=None
    ):
        return []

    async def get_ticker_price(self, market: str):
        raise NotImplementedError()

    async def create_order(self, *args, **kwargs):
        raise NotImplementedError()

    async def update_order(self, *args, **kwargs):
        raise NotImplementedError()

    async def get_order(self, *args, **kwargs):
        raise NotImplementedError()

    async def get_open_orders(self, market=None):
        return []

    async def get_orders(
        self, market: str, limit: int = 500, start=None, end=None
    ):
        return []

    async def cancel_order(self, *args, **kwargs):
        raise NotImplementedError()

    async def cancel_orders(self, market: str, operator_id: int):
        return []

    async def get_account_fees(self):
        raise NotImplementedError()

    async def get_balance(self, symbol=None):
        return []

    async def subscribe_ticker(self, markets: list[str], callback) -> None:
        return None

    async def unsubscribe_ticker(self, markets: list[str]) -> None:
        return None


class DummyStrategy(Strategy):
    """Concrete strategy for validating base helper behavior."""

    @staticmethod
    def name() -> str:
        return "dummy"

    @staticmethod
    def description() -> str:
        return "dummy"

    @staticmethod
    def default_parameters() -> dict[str, str]:
        return {}

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def on_tick(self, price: str) -> None:
        return None

    async def on_order_filled(self, order_id: str) -> None:
        return None

    def get_status(self) -> dict[str, str]:
        return {}


class TestStrategyRegistry:
    """Verify strategy registration and lookup."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Clear the registry before each test."""
        StrategyRegistry._strategies.clear()
        yield

    def test_register_and_get(self):
        """Register strategy class and verify lookup by name."""
        StrategyRegistry.register(GridStrategy)
        cls = StrategyRegistry.get("grid_trading")
        assert cls is GridStrategy

    def test_get_unknown_raises(self):
        """Raise KeyError when requesting an unknown strategy name."""
        with pytest.raises(KeyError, match="not found"):
            StrategyRegistry.get("nonexistent")

    def test_auto_discover(self):
        """Auto-discover bundled strategies and verify expected names."""
        StrategyRegistry.auto_discover()
        names = [s["name"] for s in StrategyRegistry.list_strategies()]
        assert "grid_trading" in names
        assert "dca" in names
        assert "martingale" in names

    def test_list_strategies_metadata(self):
        """Ensure metadata payload contains required strategy fields."""
        StrategyRegistry.auto_discover()
        strategies = StrategyRegistry.list_strategies()
        for s in strategies:
            assert "name" in s
            assert "description" in s
            assert "default_parameters" in s
            assert isinstance(s["default_parameters"], dict)


class TestGridStrategy:
    """Grid strategy unit tests."""

    def _make_grid_strategy(
        self,
        *,
        profit_mode: str,
        profit_skim_pct: float = 0.0,
    ) -> GridStrategy:
        config = StrategyConfig(
            market="BTC-EUR",
            operator_id=1,
            budget_quote=100.0,
            profit_mode=profit_mode,
            profit_skim_pct=profit_skim_pct,
        )
        return GridStrategy(config=config, exchange=DummyExchange())

    def test_client_order_id_is_uuid(self):
        """Generate Bitvavo-safe client order ids as canonical UUIDs."""
        strategy = DummyStrategy(
            StrategyConfig(
                market="BTC-EUR",
                operator_id=1,
                budget_quote=100.0,
                reference_id="bot-1",
            ),
            DummyExchange(),
        )

        client_order_id = strategy._next_client_order_id(
            "grid-buy-p0.96"
        )

        assert len(client_order_id) == 36
        assert client_order_id.count("-") == 4

    def test_name(self):
        """Return canonical registry name for grid strategy."""
        assert GridStrategy.name() == "grid_trading"

    def test_description(self):
        """Expose a description mentioning buy-side grid placement."""
        assert "buy orders below" in GridStrategy.description().lower()

    def test_default_parameters(self):
        """Expose default parameter keys required by grid strategy."""
        params = GridStrategy.default_parameters()
        assert "upper_price" in params
        assert "lower_price" in params
        assert "num_grids" in params

    def test_effective_budget_withdraw_keeps_initial_budget(self):
        """Keep sizing budget fixed in withdraw mode."""
        strategy = self._make_grid_strategy(profit_mode="withdraw")
        strategy._total_profit = Decimal("25")

        assert strategy._effective_grid_budget() == Decimal("100.0")

    def test_effective_budget_compound_reinvests_profit(self):
        """Increase sizing budget by full realized profit in compound mode."""
        strategy = self._make_grid_strategy(profit_mode="compound")
        strategy._total_profit = Decimal("25")

        assert strategy._effective_grid_budget() == Decimal("125.0")

    def test_effective_budget_skim_reinvests_partial_profit(self):
        """Reinvest only non-skimmed profit in skim mode."""
        strategy = self._make_grid_strategy(
            profit_mode="skim",
            profit_skim_pct=40.0,
        )
        strategy._total_profit = Decimal("20")

        assert strategy._effective_grid_budget() == Decimal("112.0")

    def test_effective_budget_skim_applies_losses(self):
        """Apply losses fully to sizing budget regardless of skim setting."""
        strategy = self._make_grid_strategy(
            profit_mode="skim",
            profit_skim_pct=90.0,
        )
        strategy._total_profit = Decimal("-10")

        assert strategy._effective_grid_budget() == Decimal("90.0")

    @pytest.mark.asyncio
    async def test_update_open_buy_orders_resizes_existing_order(self):
        """Update tracked open buy order amount when target size changes."""

        class TrackingExchange(DummyExchange):
            def __init__(self):
                self.calls: list[dict] = []

            async def update_order(self, **kwargs):
                self.calls.append(kwargs)

        exchange = TrackingExchange()
        strategy = GridStrategy(
            config=StrategyConfig(
                market="BTC-EUR",
                operator_id=7,
                budget_quote=100.0,
            ),
            exchange=exchange,
        )
        strategy._buy_orders = {"90": "oid-1"}

        open_order = Order(
            order_id="oid-1",
            market="BTC-EUR",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            status=OrderStatus.NEW,
            created=0,
            updated=0,
            amount="1",
            amount_remaining="1",
            price="90",
            operator_id=7,
        )

        await strategy._update_open_buy_orders(
            open_orders=[open_order],
            investment_per_grid=Decimal("180"),
            current_price=Decimal("100"),
        )

        assert len(exchange.calls) == 1
        assert exchange.calls[0]["order_id"] == "oid-1"
        assert exchange.calls[0]["amount"] == "2.00000000"


class TestDCAStrategy:
    """DCA strategy unit tests."""

    def test_name(self):
        """Return canonical registry name for DCA strategy."""
        assert DCAStrategy.name() == "dca"

    def test_description(self):
        """Expose a description mentioning recurring interval buys."""
        desc = DCAStrategy.description().lower()
        assert "recurring" in desc or "interval" in desc

    def test_default_parameters(self):
        """Expose default parameter keys required by DCA strategy."""
        params = DCAStrategy.default_parameters()
        assert "amount_per_order" in params
        assert "interval" in params


class TestMartingaleStrategy:
    """Martingale strategy unit tests."""

    def test_name(self):
        """Return canonical registry name for Martingale strategy."""
        assert MartingaleStrategy.name() == "martingale"

    def test_description(self):
        """Expose a description mentioning dip buying and rebounds."""
        desc = MartingaleStrategy.description().lower()
        assert "dip" in desc or "rebound" in desc

    def test_default_parameters(self):
        """Expose default parameter keys required by Martingale strategy."""
        params = MartingaleStrategy.default_parameters()
        assert "buy_in_trigger_pct" in params
        assert "take_profit_pct" in params
        assert "position_multiplier" in params
        assert "max_buy_ins" in params
        assert "stop_loss_pct" in params
