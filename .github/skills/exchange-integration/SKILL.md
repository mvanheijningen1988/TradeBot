---
name: exchange-integration
description: Implements exchange APIs for trading.
---
# Exchange Integration Skill

This skill focuses on integrating with (crypto)currency exchange APIs. It includes capabilities for market data streaming, order placement, cancellation, and account balance retrieval. The skill must ensure that all exchange interactions are abstracted away from trading strategies to maintain modularity and exchange-agnostic design.

## When to Use This Skill
Use this skill when the request involves:
- Implementing or modifying exchange API integrations
- Adding support for a new exchange
- Normalizing exchange responses for use in trading strategies
- Implementing retries and error handling for exchange interactions
- Ensuring exchange API interactions are isolated from trading logic


## capabilities:

- websocket market streams
- order placement
- order cancellation
- account balance retrieval
- retry logic with exponential backoff
- log at trace level: request ID, endpoint, method, latency, request body, response code, and parsed error fields; redact API keys and secrets.
- normalization of exchange responses to a common format for use in trading strategies
- keep track of API rate limits and implement backoff when approaching limits

Rules:

- all exchange APIs must be isolated
- retries with exponential backoff
- detailed trace logging
- normalize exchange responses
- implement backoff when approaching API rate limits
