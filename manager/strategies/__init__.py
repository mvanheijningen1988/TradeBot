from manager.strategies.base import Strategy
from manager.strategies.registry import StrategyRegistry
from manager.strategies.grid_trading import GridStrategy
from manager.strategies.dca import DCAStrategy
from manager.strategies.martingale import MartingaleStrategy

StrategyRegistry.register(GridStrategy)
StrategyRegistry.register(DCAStrategy)
StrategyRegistry.register(MartingaleStrategy)

__all__ = ["Strategy", "StrategyRegistry"]
