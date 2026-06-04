"""Tests for strategy registry and base strategy functionality."""

import pytest

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
