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