"""Tests for strategy registry and base strategy functionality."""

import pytest

from manager.strategies.base import StrategyConfig
from manager.strategies.dca import DCAStrategy
from manager.strategies.grid_trading import GridStrategy
from manager.strategies.martingale import MartingaleStrategy
from manager.strategies.registry import StrategyRegistry


class TestStrategyRegistry:
    """Verify strategy registration and lookup."""

    @pytest.fixture(autouse=True)
    def reset_registry(self):
        """Clear the registry before each test."""
        StrategyRegistry._strategies.clear()
        yield

    def test_register_and_get(self):
        StrategyRegistry.register(GridStrategy)
        cls = StrategyRegistry.get("grid_trading")
        assert cls is GridStrategy

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="not found"):
            StrategyRegistry.get("nonexistent")

    def test_auto_discover(self):
        StrategyRegistry.auto_discover()
        names = [s["name"] for s in StrategyRegistry.list_strategies()]
        assert "grid_trading" in names
        assert "dca" in names
        assert "martingale" in names

    def test_list_strategies_metadata(self):
        StrategyRegistry.auto_discover()
        strategies = StrategyRegistry.list_strategies()
        for s in strategies:
            assert "name" in s
            assert "description" in s
            assert "default_parameters" in s
            assert isinstance(s["default_parameters"], dict)


class TestGridStrategy:
    """Grid strategy unit tests."""

    def test_name(self):
        assert GridStrategy.name() == "grid_trading"

    def test_description(self):
        assert "buy orders below" in GridStrategy.description().lower()

    def test_default_parameters(self):
        params = GridStrategy.default_parameters()
        assert "upper_price" in params
        assert "lower_price" in params
        assert "num_grids" in params


class TestDCAStrategy:
    """DCA strategy unit tests."""

    def test_name(self):
        assert DCAStrategy.name() == "dca"

    def test_description(self):
        desc = DCAStrategy.description().lower()
        assert "recurring" in desc or "interval" in desc

    def test_default_parameters(self):
        params = DCAStrategy.default_parameters()
        assert "amount_per_order" in params
        assert "interval" in params


class TestMartingaleStrategy:
    """Martingale strategy unit tests."""

    def test_name(self):
        assert MartingaleStrategy.name() == "martingale"

    def test_description(self):
        desc = MartingaleStrategy.description().lower()
        assert "dip" in desc or "rebound" in desc

    def test_default_parameters(self):
        params = MartingaleStrategy.default_parameters()
        assert "buy_in_trigger_pct" in params
        assert "take_profit_pct" in params
        assert "position_multiplier" in params
        assert "max_buy_ins" in params
        assert "stop_loss_pct" in params
