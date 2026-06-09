# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- Default admin login now starts with `admin / admin123!` and the first login forces a password change before the app is accessible.
- New swarm deployment file `docker-compose.swarm.yml` with overlay-network based service communication and externally published UI port.
- New PR-gated CI workflow (`.github/workflows/pr-gated-ci.yml`) that runs backend tests, UI production build, and Docker image build checks for pull requests to `main`.
- New main-branch Docker release workflow (`.github/workflows/docker-release-main.yml`) that creates semantic version tags and publishes `manager`, `worker`, and `ui` images to Docker Hub with semantic tags plus `latest`.

### Changed
- README now documents both deployment scenarios explicitly: local `docker compose up -d --build` and swarm `docker stack deploy` flow including overlay network creation.

### Fixed
- Grid strategy now applies `profit_mode` during runtime sizing: `compound` reinvests realized PnL, `skim` reinvests only the non-skimmed profit portion (while losses still reduce sizing), and `withdraw` keeps fixed base sizing.
- Existing open grid BUY orders are now updated to the current target amount when dynamic sizing changes, so both new and already-open orders follow compound/skim sizing.
- Fixed Bitvavo order placement rejections (`error 205`) by sending
  UUID-shaped `clientOrderId` values instead of bot-prefixed custom
  identifiers, while preserving bot scoping via persisted exchange
  order ids when operator metadata is missing.
- Open orders, historical orders, and historical trades now come from the exchange but are filtered by the bot reference id/client order id prefix, so manual exchange activity no longer leaks into bot views while live bot orders remain visible.
- Open orders, order history, and trade history now also require an exact bot `operator_id` match, so exchange rows with missing or foreign operator ids are excluded even if their client order id looks bot-like.
- Dashboard order/trade details now open in a regular modal instead of the previous tooltip-style overlay, so row clicks reliably show the full payload.
- Exchange balance `manager_in_order` for BUY orders now prefers Bitvavo `onHold` quote values before fallback estimation, preventing precision drift such as `amount_remaining * price` mismatches.
- `manager_in_order` ownership filtering is now stricter by intersecting exchange open orders with known bot order-history ids, preventing manual/non-bot orders from being counted when operator tagging is ambiguous.
- Fixed exchange balance endpoint failure caused by bot order-id ownership lookup on SQLite row objects, which could surface in UI as "Failed to load exchange balances" despite valid API credentials.
- Fixed occasional 2x budget trend spikes by de-duplicating same-second snapshots per bot before aggregated history totals are computed.
- Fixed budget trend time filter behavior by applying server-side `since_minutes` filtering for both overall and per-bot history endpoints, instead of relying only on client-side trimming of a fixed-size dataset.
- Fixed timestamp parsing edge cases in dashboard chart filtering/tooltip handling for SQLite timestamp format without `T` separator.
- Added visible budget trend X-axis time labels so selected windows are readable on the chart.
- Fixed budget trend aggregation to use true per-filter time buckets (average per bucket) instead of latest-point downsampling, so datapoints consistently match selected aggregation windows.
- Fixed budget trend X-axis cadence to use per-filter tick intervals and rounded boundaries, so labels remain stable and readable across `30m`, `1h`, `2h`, `6h`, `12h`, `24h`, `7d`, and `all`.
- News Settings now include a `finbert_enabled` toggle so FinBERT sentiment can be enabled/disabled from the UI and applied via runtime settings reload.
- Grid/open-order overview now excludes manual/non-bot orders even when operator tags overlap, by requiring both bot `operator_id` match and bot-owned `order_history` id membership.
- Bot open-order retrieval now requires persisted bot-owned exchange order ids before showing active orders, preventing legacy/manual orders from leaking into the grid modal for bots without reliable operator tagging.
- Grid modal level matching now requires near-exact level proximity, preventing off-grid prices from being displayed as active grid levels.
- Grid modal now uses server-side resolved grid levels (`GET /api/bots/{bot_id}/grid-levels`) so only bot-owned orders that match configured grid levels can be shown as active.
- Grid modal now shows a visible "server validated" badge to indicate active levels are backend-validated instead of client-side matched.
- Manager images now install FinBERT dependencies by default so the news settings toggle can enable it at runtime without `transformers` import failures.

## [0.2.6] - 2026-06-08

### Fixed
- Added server-side grid-level resolution for dashboard modal to prevent manual/non-grid orders from appearing as bot-active levels.

## [UI 0.1.2] - 2026-06-08

### Fixed
- Dashboard grid modal now consumes server-side validated grid-level activity, removing client-side order-to-level mapping drift.

## [0.2.5] - 2026-06-08

### Changed
- `GET /api/exchanges/{id}/balances` now includes per-asset manager visibility fields: `manager_allocated` and `manager_in_order`.
- Dashboard exchange balance cards now show manager-claimed (`manager_allocated`) and manager in-order (`manager_in_order`) amounts next to exchange `available` and `in_order`.

### Added
- New regression tests for exchange balance enrichment helper logic (`tests/test_exchange_balances.py`) covering quote-budget aggregation and bot-owned in-order calculations.

## [0.2.4] - 2026-06-08

### Fixed
- RSS feeds added from Settings are now accepted by the runtime allowlist; custom feeds are no longer incorrectly skipped as "not in allowlist".

### Added
- Regression tests for dynamic news feed allowlist synchronization and budget trend mark-to-market behavior (buy price down/up and sell realized value impact).

### Changed
- Exchange balance payload/UI now includes `manager_allocated` and `manager_in_order` per asset so manager-claimed funds are visible alongside exchange `available` and `in_order`.

## [0.2.3] - 2026-06-08

### Added
- New worker-to-manager `budget_snapshot` websocket event to persist bot mark-to-market equity points in real time.

### Changed
- Budget trend snapshots are now produced by active strategies using bot-only quote/base position tracking and current market price.
- Dashboard now ingests live `budget_snapshot` events to refresh the trend chart without waiting for manual reload.

### Fixed
- Budget trend now reflects unrealized value changes after bot BUY trades (price down -> trend down, price up -> trend up).
- SELL executions now update bot quote/base balances so trend moves up on profitable exits and down on loss exits.
- Overall budget-history endpoint now aggregates bot snapshots only, excluding wallet-only movements that are unrelated to bot trades.

## [0.2.2] - 2026-06-08

### Changed
- Expanded inline API documentation for `BotService` lifecycle methods with explicit parameter, return, and error semantics.
- Expanded Bitvavo client method docstrings for precision helpers and trading/cancel endpoints to improve maintainability and safe local modifications.
- Expanded Worker and News collector/client docstrings with parameter-focused API documentation to simplify safe local modifications.

### Fixed
- Bot deletion now cancels only orders whose `operator_id` exactly matches the bot, preventing manual or unrelated bot orders from being cancelled.
- Bitvavo order `amount` and `amountRemaining` values are now floored using market quantity precision (capped at 8 decimals) to prevent decimal precision rejections.
- Removed blocking file-I/O from manager startup seed path by loading coin mapping JSON via thread offloading inside async lifecycle code.

## [0.2.1] - 2026-06-08

### Added
- Dedicated crypto news page with article-level sentiment table and a weighted global market indicator.
- Configurable news sources for RSS feeds and scraped pages, including per-source type and weight.
- Configurable news polling interval in Settings.

### Changed
- News engine now stores article-level snapshots so the news page can render sentiment, summaries, raw text, and coin mentions.
- News source loading now preserves source type and weight from the database.
- Settings page now edits source type, source weight, and poll interval alongside existing news controls.

### Fixed
- Scraped news URLs are now fetched safely over HTTP(S) and can be processed alongside RSS feeds.
- Bitvavo order `amount` and `amountRemaining` values are now floored using market quantity precision (capped at 8 decimals) to prevent decimal precision rejections.
- Bot deletion now cancels only orders whose `operator_id` exactly matches the bot, preventing manual or unrelated bot orders from being cancelled.

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
- **Backend API and strategy documentation coverage**:
  - Added or expanded docstrings for public classes and methods across
    repositories, strategies, exchange client methods, API schema
    models, core service helpers, and test modules.

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
