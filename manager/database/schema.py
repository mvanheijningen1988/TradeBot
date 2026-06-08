"""Database schema DDL statements.

All tables use parameterized queries throughout the application to
prevent SQL injection (OWASP A03:2021).
"""

TABLES: list[str] = [
    # ── Users ────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS users (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        username    TEXT    NOT NULL UNIQUE,
        password_hash TEXT  NOT NULL,
        role        TEXT    NOT NULL DEFAULT 'user',
        language    TEXT    NOT NULL DEFAULT 'en',
        time_display TEXT   NOT NULL DEFAULT 'local',
        must_change_password INTEGER NOT NULL DEFAULT 0,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Exchange configurations ──────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS exchanges (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        api_key     TEXT    NOT NULL,
        api_secret  TEXT    NOT NULL,
        rate_limit  INTEGER NOT NULL DEFAULT 1000,
        enabled     INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Worker nodes ─────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS workers (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id        TEXT    NOT NULL UNIQUE,
        address         TEXT    NOT NULL,
        status          TEXT    NOT NULL DEFAULT 'pending',
        version         TEXT    NOT NULL DEFAULT '',
        approved        INTEGER NOT NULL DEFAULT 0,
        last_heartbeat  TEXT,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Bots ─────────────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS bots (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        uuid            TEXT    NOT NULL UNIQUE,
        name            TEXT    NOT NULL,
        exchange_id     INTEGER NOT NULL REFERENCES exchanges(id),
        market          TEXT    NOT NULL,
        strategy        TEXT    NOT NULL,
        strategy_params TEXT    NOT NULL DEFAULT '{}',
        status          TEXT    NOT NULL DEFAULT 'stopped',
        worker_id       INTEGER REFERENCES workers(id),
        operator_id     INTEGER NOT NULL,
        budget_quote    REAL    NOT NULL DEFAULT 0,
        profit_mode     TEXT    NOT NULL DEFAULT 'withdraw',
        profit_skim_pct REAL    NOT NULL DEFAULT 0,
        manual_assign   INTEGER NOT NULL DEFAULT 0,
        retry_count     INTEGER NOT NULL DEFAULT 0,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Order history ────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS order_history (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_id              INTEGER NOT NULL REFERENCES bots(id),
        exchange_order_id   TEXT    NOT NULL,
        market              TEXT    NOT NULL,
        side                TEXT    NOT NULL,
        order_type          TEXT    NOT NULL,
        amount              TEXT,
        price               TEXT,
        amount_quote        TEXT,
        status              TEXT    NOT NULL,
        fee_paid            TEXT    NOT NULL DEFAULT '0',
        fee_currency        TEXT    NOT NULL DEFAULT '',
        created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Trade history ────────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS trade_history (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_id              INTEGER NOT NULL REFERENCES bots(id),
        order_history_id    INTEGER REFERENCES order_history(id),
        exchange_trade_id   TEXT    NOT NULL,
        market              TEXT    NOT NULL,
        side                TEXT    NOT NULL,
        amount              TEXT    NOT NULL,
        price               TEXT    NOT NULL,
        fee                 TEXT    NOT NULL DEFAULT '0',
        fee_currency        TEXT    NOT NULL DEFAULT '',
        timestamp           TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Budget history (for graphs) ──────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS budget_history (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_id      INTEGER NOT NULL REFERENCES bots(id),
        balance     REAL    NOT NULL,
        timestamp   TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Log entries (persisted for UI history) ───────────────────
    """
    CREATE TABLE IF NOT EXISTS log_entries (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        category        TEXT    NOT NULL,
        subcategory     TEXT    NOT NULL DEFAULT '',
        level           TEXT    NOT NULL DEFAULT 'INFO',
        message         TEXT    NOT NULL,
        correlation_id  TEXT,
        bot_id          INTEGER,
        worker_id       INTEGER,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Virtual wallets (per exchange) ───────────────────────────
    """
    CREATE TABLE IF NOT EXISTS wallets (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        exchange_id     INTEGER NOT NULL REFERENCES exchanges(id) UNIQUE,
        quote_currency  TEXT    NOT NULL DEFAULT 'EUR',
        balance         REAL    NOT NULL DEFAULT 0,
        created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
        updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Wallet transaction log ───────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS wallet_transactions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        wallet_id       INTEGER NOT NULL REFERENCES wallets(id),
        tx_type         TEXT    NOT NULL,
        amount          REAL    NOT NULL,
        bot_id          INTEGER REFERENCES bots(id),
        description     TEXT    NOT NULL DEFAULT '',
        created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── Wallet balance history (for budget trend) ────────────────
    """
    CREATE TABLE IF NOT EXISTS wallet_balance_history (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        wallet_id       INTEGER NOT NULL REFERENCES wallets(id),
        balance         REAL    NOT NULL,
        allocated       REAL    NOT NULL DEFAULT 0,
        unallocated     REAL    NOT NULL DEFAULT 0,
        timestamp       TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── News feed sources ─────────────────────────────────────────
    """
    CREATE TABLE IF NOT EXISTS news_feeds (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL,
        url         TEXT    NOT NULL UNIQUE,
        source_type TEXT    NOT NULL DEFAULT 'rss',
        weight      REAL    NOT NULL DEFAULT 1.0,
        enabled     INTEGER NOT NULL DEFAULT 1,
        created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
    )
    """,

    # ── News coin mappings (name → ticker symbol) ─────────────────
    """
    CREATE TABLE IF NOT EXISTS news_coin_mappings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT    NOT NULL UNIQUE,
        symbol      TEXT    NOT NULL,
        ambiguous   INTEGER NOT NULL DEFAULT 0
    )
    """,

    # ── News word filters (include / exclude) ─────────────────────
    """
    CREATE TABLE IF NOT EXISTS news_word_filters (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        word        TEXT    NOT NULL UNIQUE,
        filter_type TEXT    NOT NULL DEFAULT 'exclude'
    )
    """,

    # ── News engine parameters (key-value) ───────────────────────
    """
    CREATE TABLE IF NOT EXISTS news_engine_params (
        key         TEXT    NOT NULL PRIMARY KEY,
        value       TEXT    NOT NULL
    )
    """,
]
