# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0] - 2026-06-02

### Added
- **Exchange abstraction layer**: `ExchangeClient` abstract base class and `ExchangeRegistry` for pluggable exchange support.
- **Bitvavo WebSocket client**: Full implementation of the Bitvavo WebSocket API (`wss://ws.bitvavo.com/v2/`) including:
  - HMAC-SHA256 authentication
  - Market data: `getMarkets`, `getBook`, `getTrades`, `getTickerPrice`
  - Trading: `privateCreateOrder`, `privateUpdateOrder`, `privateGetOrder`, `privateCancelOrder`, `privateGetOrdersOpen`, `privateGetOrders`, `privateCancelOrders`
  - Account: `privateGetAccount`, `privateGetBalance`
  - Subscriptions: `ticker` channel with subscribe/unsubscribe
- **Bitvavo rate limiter**: Sliding-window rate limiter tracking weight points per action (1000 pts/sec budget, Bitvavo-specific). All documented action weights included.
- **Strategy abstraction layer**: `Strategy` abstract base class and `StrategyRegistry` with auto-discovery.
- **Grid Trading strategy**: Places buy/sell limit orders at fixed grid intervals within a price range. Automatically re-places counter orders on fills.
- **DCA strategy**: Automated recurring fixed-amount market buys at configurable intervals (hourly/daily/weekly/biweekly/monthly).
- **Martingale strategy**: Buys more on dips with increasing position multiplier, sells on take-profit rebound. Includes configurable stop-loss.
- **Shared data models**: `Order`, `MarketInfo`, `Balance`, `AccountFees`, `TickerPrice`, `OrderBook`, `Trade`, and supporting enums.
- **Test suite**: 38 unit tests covering rate limiter weights, signature generation, response parsing, strategy metadata, and registry operations.
- **Project configuration**: `pyproject.toml` with pytest, black, isort, flake8 dev dependencies.
