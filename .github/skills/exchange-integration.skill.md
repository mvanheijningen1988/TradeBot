---
name: exchange-integration
description: Implements exchange APIs for crypto trading.
---

capabilities:

- websocket market streams
- order placement
- order cancellation
- account balance retrieval

Rules:

- all exchange APIs must be isolated
- retries with exponential backoff
- detailed trace logging
- normalize exchange responses

Primary exchange:

Bitvavo WebSocket API
