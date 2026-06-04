# TradeBot

Modular, scalable platform for automated crypto trading using predefined strategies.

## Project Structure

```
manager/
├── models.py                       # Shared data models (Order, MarketInfo, etc.)
├── exchanges/
│   ├── base.py                     # Abstract ExchangeClient interface
│   ├── registry.py                 # ExchangeRegistry for pluggable exchanges
│   └── bitvavo/
│       ├── client.py               # Bitvavo WebSocket API client
│       └── rate_limiter.py         # Bitvavo-specific rate limit tracking
└── strategies/
    ├── base.py                     # Abstract Strategy interface
    ├── registry.py                 # StrategyRegistry with auto-discovery
    ├── grid_trading.py             # Grid Trading strategy
    ├── dca.py                      # Dollar Cost Averaging strategy
    └── martingale.py               # Martingale strategy
tests/
├── test_bitvavo_client.py          # Bitvavo client unit tests
├── test_rate_limiter.py            # Rate limiter tests
└── test_strategies.py              # Strategy registry & metadata tests
```

## Strategies

| Strategy | Description | Best For |
|---|---|---|
| **Grid Trading** | Places buy/sell limit orders at fixed intervals within a price range | Volatile, sideways markets |
| **DCA** | Recurring fixed-amount buys at regular intervals | Long-term accumulation |
| **Martingale** | Buys more on dips, sells on rebound | Recovering from pullbacks |

## Exchange Support

- **Bitvavo** — WebSocket API (`wss://ws.bitvavo.com/v2/`) with per-action rate limit tracking

## Recent Highlights

- **Restart-safe bot recovery**
    - Worker restart preserves bot runtime state for manager-driven recovery.
    - Stable default worker identity (`worker-<address>`) improves assignment continuity.

- **Centralized diagnostics logging**
    - Diagnostics logs receive persisted manager, worker, and bot log streams.
    - Exchange API failures (connect/auth/balance) are persisted and visible in diagnostics.

- **Delete bot API reliability**
    - Bot delete mode is handled via query parameter on DELETE requests.
    - Bot deletion now cleans FK-dependent history rows before removing
        the bot record.

- **Exchange balance reliability**
    - Fixed Bitvavo authentication recursion causing intermittent
        balance fetch timeouts.
    - Dashboard balance loading now works with authenticated exchange
        requests in the manager container runtime.

- **News Engine: RSI + Horizon insights**
    - Signals are enriched with RSI values:
        - `RSI(9)` for short-term/day-trading sensitivity
        - `RSI(14)` for smoother medium/longer trend context
    - RSI interpretation buckets:
        - `> 70`: overbought
        - `< 30`: oversold
        - otherwise: neutral
    - Each signal now includes an investment horizon hint:
        - `long_term`, `short_term`, `both`, `avoid`, or `unknown`
    - Signal tooltips in the UI display these RSI/horizon details.

- **Consistent date/time handling**
    - Timestamps are stored in UTC in SQLite.
    - UI rendering is consistent and controlled per user via a setting:
        - `Local Time` (browser locale timezone)
        - `UTC`
    - User language (`en`/`nl`) drives locale formatting.

## Date/Time Behavior

- **Storage**: backend/database timestamps use UTC.
- **Display**: frontend formats date/time based on user preference.
- **Configuration**: Settings tab → User Preferences → Date/Time Display.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Tests

```bash
pytest tests/ -v
```