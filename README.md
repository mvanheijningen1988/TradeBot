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

- Default admin access now starts with `admin / admin123!` and forces a password change on first login.

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
    - Exchange balance cards now also show manager-allocated and
        manager in-order amounts per asset to make manager-claimed
        funds explicit.

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

- **News feed page and configurable sources**
    - The UI now includes a dedicated crypto news page with weighted sentiment scoring.
    - Settings can configure RSS feeds or scrape targets, source weights, and the news poll interval.
    - The feed shows article title, source, coins, sentiment, summary, raw text, and a global positive/negative day indicator.

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

## GitHub Workflows

This repository now includes two CI/CD workflows:

- `.github/workflows/pr-gated-ci.yml`
    - Trigger: Pull requests to `development`.
    - Runs:
        - Backend tests (`pytest tests/ -v`)
        - UI production build (`npm run build -- --configuration production`)
        - Docker build checks for `manager`, `worker`, and `ui` images.

- `.github/workflows/docker-release-development.yml`
    - Trigger: Push to `development` (and manual dispatch).
    - Detects which components changed (`manager`, `worker`, `ui`).
    - Builds and pushes only changed components to Docker Hub.
    - Computes/increments semantic prerelease tags per component:
        - `manager-vMAJOR.MINOR.PATCH-dev`
        - `worker-vMAJOR.MINOR.PATCH-dev`
        - `ui-vMAJOR.MINOR.PATCH-dev`
    - Publishes image tags per changed component:
        - `MAJOR.MINOR.PATCH-dev`
        - `MAJOR.MINOR-dev`
        - `MAJOR-dev`
        - `dev`

- `.github/workflows/docker-release-main.yml`
    - Trigger: Push to `main` (and manual dispatch).
    - Detects which components changed (`manager`, `worker`, `ui`).
    - Builds and pushes only changed components to Docker Hub.
    - Computes/increments semantic version tags per component:
        - `manager-vMAJOR.MINOR.PATCH`
        - `worker-vMAJOR.MINOR.PATCH`
        - `ui-vMAJOR.MINOR.PATCH`
    - Publishes image tags per changed component:
        - `MAJOR.MINOR.PATCH`
        - `MAJOR.MINOR`
        - `MAJOR`
        - `latest` (latest for that component image)

- `.github/workflows/manual-docker-release.yml`
    - Trigger: Manual dispatch from GitHub Actions UI.
    - Allows you to choose which branch (`development` or `main`) to release.
    - Optionally specify components to release (all, manager, worker, ui, or comma-separated).
    - Validates inputs and provides a clear summary of the release operation.
    - Use this workflow to manually trigger a release without pushing to a branch.

    ## Branching Strategy

    - Create `development` from `main`.
    - Create feature branches from `development`.
    - Merge feature branches into `development` after review.
    - Every merge to `development` can publish `-dev` Docker images for swarm testing.
    - Merge `development` into `main` using **Squash and merge**.
    - After merge to `main`, production semantic tags/images are published.

### Release Validation Runbook

Use the checks below after a merge to verify component-scoped releases.

1. Manager-only change
    - Change only files under `manager/**` (or manager shared dependencies).
    - Expect workflow to publish only `tradebot-manager` tags.
    - Expect new git tag: `manager-vX.Y.Z`.
2. Worker-only change
    - Change only files under `worker/**` (or worker shared dependencies).
    - Expect workflow to publish only `tradebot-worker` tags.
    - Expect new git tag: `worker-vX.Y.Z`.
3. UI-only change
    - Change only files under `ui/**`.
    - Expect workflow to publish only `tradebot-ui` tags.
    - Expect new git tag: `ui-vX.Y.Z`.
4. Shared backend change
    - Change `shared/**` or `pyproject.toml`.
    - Expect both manager and worker releases.
    - Expect new tags for both components.
5. No component-impacting change
    - Change docs-only files outside release filters.
    - Expect no Docker release job execution and no new component tag.

Quick verification commands:

```bash
git tag -l 'manager-v*-dev' | sort -V | tail -n 3
git tag -l 'worker-v*-dev' | sort -V | tail -n 3
git tag -l 'ui-v*-dev' | sort -V | tail -n 3
git tag -l 'manager-v*' | sort -V | tail -n 3
git tag -l 'worker-v*' | sort -V | tail -n 3
git tag -l 'ui-v*' | sort -V | tail -n 3
```

### Required setup in GitHub

1. Add Docker Hub repository secrets:
     - `DOCKERHUB_USERNAME`
     - `DOCKERHUB_TOKEN`
2. Protect `development` branch and require these status checks before merge:
     - `backend-tests`
     - `ui-build`
     - `docker-build-check`
3. Protect `main` branch with:
    - "Require a pull request before merging"
    - "Require linear history" (recommended)
    - Merge method policy: allow only **Squash merge** for `development -> main`.

Without branch protection rules, workflows run but cannot block direct merges.

## Copilot Prompt Files

Reusable prompt files are available under `.github/prompts/` to streamline the development branch workflow:

- `create-feature-branch.prompt.md`
    - Creates a new `feature/<name>` branch from `development`.
    - Includes safety checks (non-destructive git usage, existing branch handling).

- `pre-pr-quality-check.prompt.md`
    - Runs a pre-PR quality gate for commit message quality, relevant tests, and documentation readiness.
    - Verifies whether `CHANGELOG.md` and `README.md` were updated where applicable.

- `create-pr-to-development.prompt.md`
    - Guides PR creation from feature branch to `development` only.
    - Enforces checks for branch target, commit message quality, tests, and required documentation updates.

## Docker Deploy Modes

### Local development (unchanged)

Use the existing compose file with build support:

```bash
docker compose up -d --build
```

This keeps the same local workflow with direct image builds from the
repo and local named volumes.

### Docker Swarm

Swarm uses a separate file because `docker stack deploy` does not build
images from `build:` sections.

1. Build images (or push to your registry and set image vars):

```bash
docker compose build manager worker ui
```

2. Initialize swarm once (if needed):

```bash
docker swarm init
```

3. Create the shared overlay network for service-to-service communication:

```bash
docker network create -d overlay --attachable tradebot-swarm-net
```

4. Deploy the stack:

```bash
docker stack deploy -c docker-compose.swarm.yml tradebot
```

5. Verify services:

```bash
docker stack services tradebot
```

The UI is published externally on port `80` by default in swarm mode
(`UI_PORT` can override this).