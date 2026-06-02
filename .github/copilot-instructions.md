# Copilot Instructions for TradeBot Project

## 1. System Overview
TradeBot is a modular, scalable platform for automated crypto trading using predefined strategies.
The system consists of at least one Manager Node and, for the bots to run, at least one Worker Node.
All nodes run in Docker containers for consistency across environments.

### 1.1 Components
- **Manager Node**
  - Communicates and shares states with other manager nodes for high availability and failover.
  - Keeps track of health and status of other manager nodes, Worker Nodes and bots, and manages their lifecycle.
  - Registers, accepts, and authorizes Worker Nodes
  - Manages bots: creation, assignment, start/stop/delete
  - Handles load balancing and failover of bots across workers
  - Controls budgets from the exchanges: Since budget cannot be reserved at the exchange, the manager tracks and enforces budget limits across all bots to prevent over-allocation
  - Stores users, settings, bot configs, states, and trading history in a central SQLite database
  - Provides REST API for UI and Worker communication, and WebSocket for real-time updates
  - Provides a web-based UI for monitoring and managing bots, workers, and settings and dashboards for performance, PnL and diagnostics.

- **Worker Node**
  - Can run multiple bots assigned by the manager
  - Reports status, performance, and logging via WebSocket
  - Supports live log streaming to Manager and UI

- **Bots**
  - Execute single strategies and are self-contained
  - Report status, performance, and logs in real time
  - Can run concurrently within a Worker

- **Communication**
  - Real-time via secure WebSocket (status, commands, live logs, alerts)
  - REST API for bulk data, configuration, health checks, and reports
  - All connections secured with TLS; authentication via tokens for REST and encrypted WebSocket connections

- **Database (SQLite)**
  - Stores configuration, bot assignments, historical data, cluster data, worker nodes, user acounts and settings
  - Workers and bots request runtime config via manager (for dynamic updates)

### 1.2 Design Goals
- Modularity: Clear separation of concerns between manager, workers, and bots
- Scalability: Support many bots and workers with efficient resource management
- Reliability: Robust error handling, failover, clustering and monitoring
- Security: Follow best practices for secure coding, authentication, and data handling
- User-friendly: Intuitive UI with real-time visibility and control over bots and workers

### 1.3 Availability & Scalability
- Designed for high availability with failover, load balancing, clustering and robust error handling.

#### Failure Handling Scenarios

1. **Manager Node Failure**
  1. If the manager node fails (e.g., crashes, becomes unresponsive):
    - Other manager nodes (if any) will detect the failure through health checks and take over management responsibilities.
    - The failing manager node should automatically attempt to restart the manager container up to 5 times with exponential backoff.
    - If no other manager nodes are available, the worker nodes and bots will continue running their current strategies without interruption.
  2. Worker nodes and bots continue running their current strategies until the Manager is back online.
  3. If the Manager Node fails to restart after 5 attempts:
    - The container must be manually restarted by an administrator.
    - No notification is sent to the administrator; this is handled by external monitoring tools or manual intervention.
    - Worker nodes and bots continue executing their current strategies without further updates from the Manager.

2. **Bot Fault Status**
  1. Log the error.
  2. Notify the user.
  3. Attempt to restart the bot (maximum 3 retries).
  4. If the bot continues to fail after 3 retries, mark it as Stopped.

3. **Corrupted or Invalid Bot Configuration**
  1. Log the issue.
  2. Notify the user.
  3. Prevent the bot from starting until the configuration is corrected.

4. **SQLite Database Corruption or Inaccessibility**
  1. Log the error.
  2. Notify the user.
  3. Halt all bot operations.
  4. Manual user database restore is required before resuming operations.

5. **Worker Node Authorization Failure**
  1. Log the reason for failure.
  2. Notify the administrator for manual resolution.

6. **Worker Node Status Timeout**
  1. If a Worker Node fails to report its status for more than a configurable timeout period:
    - Log the issue.
    - Notify the administrator.
    - Mark the Worker Node as Unresponsive in the UI.

7. **Malformed or Invalid Worker Status Data**
  1. Log the issue.
  2. Notify the administrator.
  3. Request the Worker Node to resend the data.

8. **TLS Connection Failure**
  1. Log the error.
  2. Notify the user.
  3. Halt the connection attempt until the issue is resolved.

9. **WebSocket Connection Interruption During Critical Operation**
  1. Log the interruption.
  2. Attempt to reconnect.
  3. Retry the operation if it is safe to do so.
  4. If reconnection fails after 3 attempts:
    - Log the failure.
    - Notify the user.
    - Halt the operation.

### 1.4 Scalability

- Scalable to support many bots and workers, with efficient resource management.

---

## 2. Coding Standards and Best Practices

- Follow **PEP8** for Python
- Use `snake_case` for functions/variables, `PascalCase` for class names
- Prefix private members with `_`
- English for code and docs
- Clear docstrings and inline comments
- Functions should be modular and concise (max 50 lines)
- No more than 3 levels of nesting
- Use constants for hardcoded values.
- Use __init__.py to define package structure and imports

### Type Hints

- Required except for:
  - Functions with duplicate signatures (log warning)
  - Ambiguous/conflicting implementations (log warning)
  - Third-party libraries (log once, skip)

### Linters & Formatters

- Run `flake8`, `black`, `isort` on every submission
- If all fail, halt process and notify with troubleshooting steps
- Use `black` formatting as source of truth
- Record config changes in `CHANGELOG.md`

### Logging
- Use `logging` module with appropriate levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- From the UI the loglevels should be changeable. also it should be possible to set the log level per category (e.g. manager, worker, bot, exchange) and subcategory (module name) without requiring restarts.
- Include context in logs (bot name, worker ID, timestamps)
- Log to both console and rotating file handlers
- rotate logs daily or when they reach 10MB, keeping 7 days of history
- logging should be made available in the UI for real-time monitoring and diagnostics, this includes the history of logs for each bot and worker, with filtering and search capabilities.
- Separate logs into catagories and subcatagories (e.g. manager, worker, bot, exchange) for easier analysis and troubleshooting
- Log errors with stack traces and relevant context for easier debugging and issue resolution
- Debug logging must be toggleable via the UI and should not require a restart of the manager or worker nodes to take effect
- Trace logging should be used for critical operations (e.g. bot execution steps, exchange interactions) to provide detailed insights into the system's behavior and facilitate troubleshooting. This should also be toggleable via the UI without requiring restarts.
- Logs/Transactions should be correlated with unique identifiers (e.g. bot ID, worker ID, transaction ID) to allow tracing the flow of operations across different components and facilitate debugging and performance analysis.
- From the UI a correlation id should be searchable across all logs to easily trace the flow of a specific operation or issue across the system. This should show the complete flow in the UI.
- All transactions to the exchange should be logged with trace level logging, including the request and response data, timestamps, and any relevant context (e.g. bot name, worker ID). This will allow for detailed analysis of exchange interactions and help identify issues or performance bottlenecks.

---

## 3. Worker Registration Flow

- On startup, Worker registers with Manager via REST
  - If successful: no further attempts
  - On network/unknown error: retry with exponential backoff
  - On explicit rejection: stop retrying immediately
  - Precedence: explicit rejection always stops retries
  - Rejected workers can be manually approved later via the UI, which will reset their retry attempts and allow them to register successfully.

---

## 4. Functional Architecture

- Modular strategy and exchange implementations
- Bots report status:
  - Stopped
  - Assigning
  - Initializing
  - Running
  - Fault
- Assignment can be automatic or manual
- manual assignment should stop load balancing for that bot. Automatic assignment should be re-enablabled via the UI.
- Real-time visibility of bot and worker status in the UI.

**Caching**
- Markets: 24 hours
- Exchange fees: 5 minutes

---

## 5. Exchange Support

- Initial implementation: Bitvavo via WebSocket API
  - Markets and fees endpoints used
  - Caching as above
- Asset icons loaded from coin_map.json

---

## 6. Security & Reliability

- Follow **OWASP** guidelines:
  - Input sanitization
  - SQL injection protection
  - XSS/CSRF prevention
  - Auth checks
  - No hard-coded secrets
  - Principle of least privilege
  - All connections via TLS
  - Use `pip-audit` for dependency checks
  - REST endpoints require authentication and authorization and the bearer token must be validated on every request
  - WebSocket connections require authentication and are encrypted

### Asynchronous Programming

- Use `asyncio`
- Proper exception handling, timeouts, cleanup (`async with`)
- Log errors with context

---

## 7. Testing & CI/CD

- Unit tests for all functions/classes with `pytest`
- Mock external dependencies
- Test edge cases and failures (network, invalid input, async issues)
- CI/CD config in `.github/workflows`:
  - Must handle async tests, timeouts

---

## 8. User Interface (UI)

- Built in Angular (latest LTS), modular via components/services
- Dark, neon-accented crypto look & feel (black/grey/neon colors, console fonts, glow/pulse effects)
- Multilingual (Dutch/English), default by browser, user choice remembered
- Automatic Admin account creation on first start, password shown in container logs

### UI Pages

- **Dashboard**
  - Table overview: bots with Name, Market, Status, Runtime, Actions
  - Exchange balances, open orders, history
  - Budget graphs with time filters
    - should be tracable and historical from the moment the bot is created, this allows for detailed performance analysis and insights into the bot's behavior over time.
  - Neon-glow alerts for bot issues

- **Workers**
  - Agent ID, Address, Status, Bots, Version, Uptime, Last heartbeat, Approval, Actions
  - Expandable detail overview: bots per worker

- **Settings**
  - Exchange management
  - API keys, secrets, rate limits
  - User management, language, authorization groups

- **Diagnostics**
  - CPU and memory stats
  - Logs per manager, worker, bot
  - Realtime log streaming

---

## 9. Bot Features & Management

- Bots based on chosen strategy (e.g. Static Grid)
- UI supports:
  - Market selection (dropdown/icons/autocomplete)
  - Strategy parameters, fee display
  - Budget slider, profit mode selection
  - Validation and preview
- Bot deletion supports:
  - Stop and cancel orders
  - Delete only
  - Convert assets

---

## 10. Design Principles

- Apply SOLID principles:
  1. Single Responsibility
  2. Open/Closed
  3. Liskov Substitution
  4. Interface Segregation
  5. Dependency Inversion

---

## 11. Documentation & References

- **Bitvavo WebSocket API:** https://docs.bitvavo.com
- **Coin icons:** https://raw.githubusercontent.com/ErikThiart/cryptocurrency-icons/refs/heads/master/coin_map.json
- **PEP8 Style Guide:** https://www.python.org/dev/peps/pep-0008/
- **Python Style Guide:** https://docs.python-guide.org/writing/style/
- **OWASP Secure Coding Practices:** https://owasp.org/www-project-secure-coding
- Maintain `README.md` (instructions/overview/setup/usage/installation)
- Maintain `CHANGELOG.md` (high-level changes/features/config updates)

---

**End of Instructions**
