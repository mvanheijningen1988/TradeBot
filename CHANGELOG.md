# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0] - 2026-06-04

### Added
- **Worker restart bot recovery hardening**:
  - Stable default worker identity (`worker-<address>`) to avoid orphaned bot assignments after worker restarts.
  - New worker restart regression tests in `tests/test_worker_restart_resume.py`.
- **Central diagnostics log streaming**:
  - Manager logger output is now mirrored into persisted diagnostics logs.
  - Worker logger output is forwarded to manager and persisted as worker/bot diagnostics events.
- **Per-user date/time display preference**:
  - New user setting `time_display` with values `local` or `utc`.
  - New endpoint `PUT /api/settings/time-display`.
  - Angular Settings UI now allows users to choose Local Time or UTC.
  - Shared UI date-time formatter ensures consistent locale/timezone rendering across pages.
- **News Engine RSI enrichment**:
  - Added RSI calculation support using the standard formula based on
    exchange trade prices.
  - Signals now include RSI(9), RSI(14), RSI state
    (`overbought`/`oversold`/`neutral`), and investment horizon hints
    (`long_term`, `short_term`, `both`, `avoid`, `unknown`).
  - Signal tooltip now includes per-field info hints and a short
    article-context summary that explains why the article reads as
    positive, negative, or mixed.

### Changed
- **Bot shutdown behavior during worker stop/restart**:
  - Worker shutdown now preserves running bot exchange state for manager-side recovery.
  - BotRunner stop flow supports restart-safe shutdown without reporting bot as stopped.
- **Bot delete API semantics**:
  - Delete mode is now sent/handled via query parameter for `DELETE /api/bots/{bot_id}`.
  - Frontend delete call updated accordingly.
- **Exchange balance error handling**:
  - Exchange connect/auth/balance failures now return explicit 502 responses.
  - Failures are persisted into diagnostics logs under manager/api.exchanges.
  - Dashboard shows per-exchange balance load error messages.
- **News signal tooltip content**:
  - Dashboard signal tooltips now display RSI metrics and suggested
    investment horizon context.

### Fixed
- Bots no longer lose recoverable runtime state on worker restart.
- Bot deletion endpoint works reliably with FastAPI DELETE semantics.
- Bot deletion now clears all FK-dependent rows (`trade_history`,
  `order_history`, `budget_history`, `wallet_transactions`) before
  removing the bot record.
- Exchange balance failures are visible in both dashboard and diagnostics logs.
- Fixed Bitvavo client authentication recursion in `_send_action()` that
  could cause timeouts and unavailable exchange balances.
- Cleared final static-analysis blockers from the recent strategy/exchange
  update:
  - Reduced `MartingaleStrategy.on_tick()` complexity by splitting stop-loss,
    buy-in, and take-profit logic into focused helper methods.
  - Tightened exchange cancel order return types to
    `dict[str, Any]`/`list[dict[str, Any]]` to satisfy strict typing.
  - Added UI TypeScript `rootDir` in `ui/tsconfig.json` for TS 6 compatibility.
- Timestamp rendering consistency in major UI diagnostics/dashboard/worker views.
- Docker Compose manager JWT secret now defaults to a stable value for
  local development to reduce token invalidation after restarts.
- **Signals panel empty after restart**:
  - Recommendations now fall back to persisted `news_signals` records
    when in-memory signal cache is empty after manager restart.
  - Signals panel now refreshes recommendations periodically so bullish/
    bearish entries appear without requiring a full browser reload.

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
