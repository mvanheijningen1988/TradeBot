"""Database repository classes.

Every SQL query uses parameterized statements to prevent injection.
"""

import json
import logging
import uuid as uuid_mod
from typing import Any, Optional

from manager.database.connection import Database

logger = logging.getLogger(__name__)


# ── User repository ──────────────────────────────────────────────


class UserRepository:
    """CRUD operations for the users table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        username: str,
        password_hash: str,
        role: str = "user",
        language: str = "en",
        time_display: str = "local",
    ) -> int:
        """Create a user row and return its database id."""
        cursor = await self._db.execute(
            "INSERT INTO users "
            "(username, password_hash, role, language, time_display) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, password_hash, role, language, time_display),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_by_username(self, username: str) -> Optional[dict]:
        """Return a user dict by username, or None when absent."""
        row = await self._db.fetch_one(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        return dict(row) if row else None

    async def get_by_id(self, user_id: int) -> Optional[dict]:
        """Return a user dict by primary key, or None when absent."""
        row = await self._db.fetch_one(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        )
        return dict(row) if row else None

    async def list_all(self) -> list[dict]:
        """Return all users with non-sensitive profile fields."""
        rows = await self._db.fetch_all(
            "SELECT id, username, role, language, time_display, "
            "created_at FROM users"
        )
        return [dict(r) for r in rows]

    async def update(self, user_id: int, **fields: Any) -> None:
        """Update allowed user fields for a single user id."""
        allowed = {
            "username",
            "password_hash",
            "role",
            "language",
            "time_display",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = (*updates.values(), user_id)
        await self._db.execute(
            f"UPDATE users SET {set_clause}, "
            "updated_at = datetime('now') WHERE id = ?",
            params,
        )
        await self._db.commit()

    async def delete(self, user_id: int) -> None:
        """Delete a user row by id."""
        await self._db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await self._db.commit()

    async def count(self) -> int:
        """Return the total number of users."""
        row = await self._db.fetch_one("SELECT COUNT(*) as cnt FROM users")
        return row["cnt"]


# ── Exchange repository ──────────────────────────────────────────


class ExchangeRepository:
    """CRUD operations for the exchanges table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        name: str,
        api_key: str,
        api_secret: str,
        rate_limit: int = 1000,
    ) -> int:
        """Create an exchange configuration row and return its id."""
        cursor = await self._db.execute(
            "INSERT INTO exchanges (name, api_key, api_secret, rate_limit) "
            "VALUES (?, ?, ?, ?)",
            (name, api_key, api_secret, rate_limit),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_by_id(self, exchange_id: int) -> Optional[dict]:
        """Return an exchange configuration by id."""
        row = await self._db.fetch_one(
            "SELECT * FROM exchanges WHERE id = ?", (exchange_id,)
        )
        return dict(row) if row else None

    async def list_all(self) -> list[dict]:
        """Return all exchange configurations without secret fields."""
        rows = await self._db.fetch_all(
            "SELECT id, name, rate_limit, enabled, created_at FROM exchanges"
        )
        return [dict(r) for r in rows]

    async def update(self, exchange_id: int, **fields: Any) -> None:
        """Update allowed fields for an exchange configuration."""
        allowed = {"name", "api_key", "api_secret", "rate_limit", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = (*updates.values(), exchange_id)
        await self._db.execute(
            f"UPDATE exchanges SET {set_clause}, "
            "updated_at = datetime('now') WHERE id = ?",
            params,
        )
        await self._db.commit()

    async def delete(self, exchange_id: int) -> None:
        """Delete an exchange configuration by id."""
        await self._db.execute(
            "DELETE FROM exchanges WHERE id = ?", (exchange_id,)
        )
        await self._db.commit()


# ── Worker repository ────────────────────────────────────────────


class WorkerRepository:
    """CRUD operations for the workers table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, agent_id: str, address: str, version: str = ""
    ) -> int:
        """Create a worker row and return its id."""
        cursor = await self._db.execute(
            "INSERT INTO workers (agent_id, address, version) "
            "VALUES (?, ?, ?)",
            (agent_id, address, version),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_by_agent_id(self, agent_id: str) -> Optional[dict]:
        """Return a worker by its stable agent identifier."""
        row = await self._db.fetch_one(
            "SELECT * FROM workers WHERE agent_id = ?", (agent_id,)
        )
        return dict(row) if row else None

    async def get_by_id(self, worker_id: int) -> Optional[dict]:
        """Return a worker row by primary key."""
        row = await self._db.fetch_one(
            "SELECT * FROM workers WHERE id = ?", (worker_id,)
        )
        return dict(row) if row else None

    async def list_all(self) -> list[dict]:
        """Return all worker rows."""
        rows = await self._db.fetch_all("SELECT * FROM workers")
        return [dict(r) for r in rows]

    async def update_status(
        self, worker_id: int, status: str
    ) -> None:
        """Update the lifecycle status for a worker."""
        await self._db.execute(
            "UPDATE workers SET status = ? WHERE id = ?",
            (status, worker_id),
        )
        await self._db.commit()

    async def update_heartbeat(self, worker_id: int) -> None:
        """Set worker heartbeat timestamp to the current UTC time."""
        await self._db.execute(
            "UPDATE workers SET last_heartbeat = datetime('now') "
            "WHERE id = ?",
            (worker_id,),
        )
        await self._db.commit()

    async def approve(self, worker_id: int) -> None:
        """Mark a worker as approved and ready for scheduling."""
        await self._db.execute(
            "UPDATE workers SET approved = 1, status = 'approved' "
            "WHERE id = ?",
            (worker_id,),
        )
        await self._db.commit()

    async def reject(self, worker_id: int) -> None:
        """Mark a worker as rejected to block future assignments."""
        await self._db.execute(
            "UPDATE workers SET approved = 0, status = 'rejected' "
            "WHERE id = ?",
            (worker_id,),
        )
        await self._db.commit()

    async def delete(self, worker_id: int) -> None:
        """Delete a worker row by id."""
        await self._db.execute(
            "DELETE FROM workers WHERE id = ?", (worker_id,)
        )
        await self._db.commit()

    async def get_approved_online(self) -> list[dict]:
        """Return workers currently approved and considered online."""
        rows = await self._db.fetch_all(
            "SELECT * FROM workers WHERE approved = 1 "
            "AND status IN ('approved', 'online')"
        )
        return [dict(r) for r in rows]


# ── Bot repository ───────────────────────────────────────────────


class BotRepository:
    """CRUD operations for the bots table."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        name: str,
        exchange_id: int,
        market: str,
        strategy: str,
        strategy_params: dict,
        operator_id: int,
        budget_quote: float,
        profit_mode: str = "withdraw",
        profit_skim_pct: float = 0.0,
    ) -> dict:
        """Create a bot row and return the stored bot document."""
        bot_uuid = str(uuid_mod.uuid4())
        params_json = json.dumps(strategy_params)
        cursor = await self._db.execute(
            "INSERT INTO bots "
            "(uuid, name, exchange_id, market, strategy, strategy_params, "
            " operator_id, budget_quote, profit_mode, profit_skim_pct) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bot_uuid, name, exchange_id, market, strategy,
                params_json, operator_id, budget_quote,
                profit_mode, profit_skim_pct,
            ),
        )
        await self._db.commit()
        return await self.get_by_id(cursor.lastrowid)

    async def get_by_id(self, bot_id: int) -> Optional[dict]:
        """Return a bot by id with decoded strategy parameters."""
        row = await self._db.fetch_one(
            "SELECT * FROM bots WHERE id = ?", (bot_id,)
        )
        if not row:
            return None
        d = dict(row)
        d["strategy_params"] = json.loads(d["strategy_params"])
        return d

    async def get_by_uuid(self, bot_uuid: str) -> Optional[dict]:
        """Return a bot by UUID with decoded strategy parameters."""
        row = await self._db.fetch_one(
            "SELECT * FROM bots WHERE uuid = ?", (bot_uuid,)
        )
        if not row:
            return None
        d = dict(row)
        d["strategy_params"] = json.loads(d["strategy_params"])
        return d

    async def list_all(self) -> list[dict]:
        """Return all bots ordered by id with decoded parameters."""
        rows = await self._db.fetch_all("SELECT * FROM bots ORDER BY id")
        result = []
        for r in rows:
            d = dict(r)
            d["strategy_params"] = json.loads(d["strategy_params"])
            result.append(d)
        return result

    async def list_by_worker(self, worker_id: int) -> list[dict]:
        """Return all bots currently assigned to a worker id."""
        rows = await self._db.fetch_all(
            "SELECT * FROM bots WHERE worker_id = ?", (worker_id,)
        )
        result = []
        for r in rows:
            d = dict(r)
            d["strategy_params"] = json.loads(d["strategy_params"])
            result.append(d)
        return result

    async def update_status(
        self, bot_id: int, status: str
    ) -> None:
        """Update bot status and refresh the update timestamp."""
        await self._db.execute(
            "UPDATE bots SET status = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (status, bot_id),
        )
        await self._db.commit()

    async def assign_worker(
        self, bot_id: int, worker_id: int, manual: bool = False
    ) -> None:
        """Assign a bot to a worker and set assigning state metadata."""
        await self._db.execute(
            "UPDATE bots SET worker_id = ?, manual_assign = ?, "
            "status = 'assigning', updated_at = datetime('now') "
            "WHERE id = ?",
            (worker_id, int(manual), bot_id),
        )
        await self._db.commit()

    async def update(self, bot_id: int, **fields: Any) -> None:
        """Apply partial updates to a bot row using allowed fields only."""
        allowed = {
            "name", "strategy_params", "budget_quote",
            "profit_mode", "profit_skim_pct", "retry_count",
            "status", "worker_id",
        }
        updates = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "strategy_params" and isinstance(v, dict):
                updates[k] = json.dumps(v)
            else:
                updates[k] = v
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = (*updates.values(), bot_id)
        await self._db.execute(
            f"UPDATE bots SET {set_clause}, "
            "updated_at = datetime('now') WHERE id = ?",
            params,
        )
        await self._db.commit()

    async def delete(self, bot_id: int) -> None:
        """Delete a bot and dependent history rows linked by foreign keys."""
        # Clean FK-dependent rows that reference bots.id.
        await self._db.execute(
            "DELETE FROM wallet_transactions WHERE bot_id = ?",
            (bot_id,),
        )
        await self._db.execute(
            "DELETE FROM budget_history WHERE bot_id = ?",
            (bot_id,),
        )
        await self._db.execute(
            "DELETE FROM bots WHERE id = ?", (bot_id,)
        )
        await self._db.commit()

    async def get_next_operator_id(self) -> int:
        """Return the next available operator id for bot exchange orders."""
        row = await self._db.fetch_one(
            "SELECT COALESCE(MAX(operator_id), 0) + 1 AS next_id FROM bots"
        )
        return row["next_id"]


# ── Order history repository ─────────────────────────────────────


class OrderHistoryRepository:
    """Persisted order records for UI history views."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        bot_id: int,
        exchange_order_id: str,
        market: str,
        side: str,
        order_type: str,
        status: str,
        amount: Optional[str] = None,
        price: Optional[str] = None,
        amount_quote: Optional[str] = None,
        fee_paid: str = "0",
        fee_currency: str = "",
    ) -> int:
        """Insert or refresh an order-history row and return its id."""
        # Check if order already exists (e.g. synced from exchange).
        existing = await self._db.fetch_one(
            "SELECT id FROM order_history "
            "WHERE bot_id = ? AND exchange_order_id = ?",
            (bot_id, exchange_order_id),
        )
        if existing:
            await self._db.execute(
                "UPDATE order_history SET status = ?, "
                "updated_at = datetime('now') WHERE id = ?",
                (status, existing["id"]),
            )
            await self._db.commit()
            return existing["id"]

        cursor = await self._db.execute(
            "INSERT INTO order_history "
            "(bot_id, exchange_order_id, market, side, order_type, "
            " amount, price, amount_quote, status, fee_paid, fee_currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bot_id, exchange_order_id, market, side, order_type,
                amount, price, amount_quote, status, fee_paid, fee_currency,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def list_by_bot(
        self, bot_id: int, limit: int = 100
    ) -> list[dict]:
        """Return recent order-history rows for a bot."""
        rows = await self._db.fetch_all(
            "SELECT * FROM order_history WHERE bot_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (bot_id, limit),
        )
        return [dict(r) for r in rows]

    async def update_status(
        self, order_id: int, status: str
    ) -> None:
        """Update status for a persisted order-history record."""
        await self._db.execute(
            "UPDATE order_history SET status = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (status, order_id),
        )
        await self._db.commit()

    async def delete_by_bot(self, bot_id: int) -> None:
        """Delete all order history for a bot."""
        await self._db.execute(
            "DELETE FROM order_history WHERE bot_id = ?", (bot_id,)
        )
        await self._db.commit()


# ── Trade history repository ─────────────────────────────────────


class TradeHistoryRepository:
    """Persisted trade execution records for bot performance tracking."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        bot_id: int,
        exchange_trade_id: str,
        market: str,
        side: str,
        amount: str,
        price: str,
        fee: str = "0",
        fee_currency: str = "",
        order_history_id: Optional[int] = None,
    ) -> int:
        """Insert a trade-history row and return its id."""
        cursor = await self._db.execute(
            "INSERT INTO trade_history "
            "(bot_id, order_history_id, exchange_trade_id, market, side, "
            " amount, price, fee, fee_currency) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                bot_id, order_history_id, exchange_trade_id,
                market, side, amount, price, fee, fee_currency,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def list_by_bot(
        self, bot_id: int, limit: int = 100
    ) -> list[dict]:
        """Return recent trade-history rows for a bot."""
        rows = await self._db.fetch_all(
            "SELECT * FROM trade_history WHERE bot_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (bot_id, limit),
        )
        return [dict(r) for r in rows]

    async def delete_by_bot(self, bot_id: int) -> None:
        """Delete all trade history for a bot."""
        await self._db.execute(
            "DELETE FROM trade_history WHERE bot_id = ?", (bot_id,)
        )
        await self._db.commit()


# ── Budget history repository ────────────────────────────────────


class BudgetHistoryRepository:
    """Budget snapshots for trend graphs."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, bot_id: int, balance: float) -> None:
        """Store one budget snapshot point for a bot."""
        await self._db.execute(
            "INSERT INTO budget_history (bot_id, balance) VALUES (?, ?)",
            (bot_id, balance),
        )
        await self._db.commit()

    async def get_history(
        self, bot_id: int, limit: int = 500
    ) -> list[dict]:
        """Return budget history points for a single bot."""
        rows = await self._db.fetch_all(
            "SELECT * FROM budget_history WHERE bot_id = ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (bot_id, limit),
        )
        return [dict(r) for r in rows]

    async def get_all_history(self, limit: int = 500) -> list[dict]:
        """Return aggregated budget history across all bots."""
        rows = await self._db.fetch_all(
            "SELECT timestamp, SUM(balance) as balance "
            "FROM budget_history GROUP BY timestamp "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]


# ── Log entries repository ───────────────────────────────────────


class LogEntryRepository:
    """Persisted log entries for UI history and search."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        category: str,
        message: str,
        level: str = "INFO",
        subcategory: str = "",
        correlation_id: Optional[str] = None,
        bot_id: Optional[int] = None,
        worker_id: Optional[int] = None,
    ) -> int:
        """Persist a diagnostics log entry and return its id."""
        cursor = await self._db.execute(
            "INSERT INTO log_entries "
            "(category, subcategory, level, message, "
            " correlation_id, bot_id, worker_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                category, subcategory, level, message,
                correlation_id, bot_id, worker_id,
            ),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def search(
        self,
        category: Optional[str] = None,
        correlation_id: Optional[str] = None,
        bot_id: Optional[int] = None,
        worker_id: Optional[int] = None,
        level: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        """Query persisted logs using optional filters and level threshold."""
        conditions: list[str] = []
        params: list[Any] = []

        if category:
            conditions.append("category = ?")
            params.append(category)
        if correlation_id:
            conditions.append("correlation_id = ?")
            params.append(correlation_id)
        if bot_id is not None:
            conditions.append("bot_id = ?")
            params.append(bot_id)
        if worker_id is not None:
            conditions.append("worker_id = ?")
            params.append(worker_id)
        if level:
            level_order = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
            level_upper = level.upper()
            if level_upper in level_order:
                idx = level_order.index(level_upper)
                allowed = level_order[idx:]
                placeholders = ", ".join("?" for _ in allowed)
                conditions.append(f"level IN ({placeholders})")
                params.extend(allowed)
            else:
                conditions.append("level = ?")
                params.append(level)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = await self._db.fetch_all(
            f"SELECT * FROM log_entries {where} "
            "ORDER BY id DESC LIMIT ?",
            tuple(params),
        )
        result = []
        for r in rows:
            d = dict(r)
            d["timestamp"] = d.pop("created_at", None)
            result.append(d)
        return result


# ── Wallet repository ────────────────────────────────────────────


class WalletRepository:
    """Virtual wallet and transaction persistence."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_by_exchange(self, exchange_id: int) -> Optional[dict]:
        """Get wallet for an exchange."""
        row = await self._db.fetch_one(
            "SELECT * FROM wallets WHERE exchange_id = ?",
            (exchange_id,),
        )
        return dict(row) if row else None

    async def create(
        self,
        exchange_id: int,
        quote_currency: str = "EUR",
        balance: float = 0.0,
    ) -> dict:
        """Create a wallet for an exchange."""
        cursor = await self._db.execute(
            "INSERT INTO wallets (exchange_id, quote_currency, balance) "
            "VALUES (?, ?, ?)",
            (exchange_id, quote_currency, balance),
        )
        await self._db.commit()
        row = await self._db.fetch_one(
            "SELECT * FROM wallets WHERE id = ?",
            (cursor.lastrowid,),
        )
        return dict(row)

    async def update_balance(
        self, wallet_id: int, new_balance: float
    ) -> None:
        """Set the wallet balance."""
        await self._db.execute(
            "UPDATE wallets SET balance = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (new_balance, wallet_id),
        )
        await self._db.commit()

    async def add_transaction(
        self,
        wallet_id: int,
        tx_type: str,
        amount: float,
        bot_id: Optional[int] = None,
        description: str = "",
    ) -> int:
        """Record a wallet transaction."""
        cursor = await self._db.execute(
            "INSERT INTO wallet_transactions "
            "(wallet_id, tx_type, amount, bot_id, description) "
            "VALUES (?, ?, ?, ?, ?)",
            (wallet_id, tx_type, amount, bot_id, description),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_transactions(
        self, wallet_id: int, limit: int = 100
    ) -> list[dict]:
        """Return recent wallet transactions."""
        rows = await self._db.fetch_all(
            "SELECT * FROM wallet_transactions "
            "WHERE wallet_id = ? ORDER BY id DESC LIMIT ?",
            (wallet_id, limit),
        )
        return [dict(r) for r in rows]

    async def get_allocated(self, wallet_id: int) -> float:
        """Sum allocated budget across active bots for this wallet."""
        wallet = await self._db.fetch_one(
            "SELECT exchange_id FROM wallets WHERE id = ?",
            (wallet_id,),
        )
        if not wallet:
            return 0.0
        rows = await self._db.fetch_all(
            "SELECT COALESCE(SUM(budget_quote), 0) as total "
            "FROM bots WHERE exchange_id = ? AND status != 'stopped'",
            (wallet["exchange_id"],),
        )
        return float(rows[0]["total"]) if rows else 0.0

    async def record_balance_snapshot(
        self,
        wallet_id: int,
        balance: float,
        allocated: float,
        unallocated: float,
    ) -> None:
        """Record a wallet balance snapshot for trend graphs."""
        await self._db.execute(
            "INSERT INTO wallet_balance_history "
            "(wallet_id, balance, allocated, unallocated) "
            "VALUES (?, ?, ?, ?)",
            (wallet_id, balance, allocated, unallocated),
        )
        await self._db.commit()

    async def get_balance_history(
        self, wallet_id: int, limit: int = 500
    ) -> list[dict]:
        """Return wallet balance history for trend graphs."""
        rows = await self._db.fetch_all(
            "SELECT * FROM wallet_balance_history "
            "WHERE wallet_id = ? ORDER BY timestamp DESC LIMIT ?",
            (wallet_id, limit),
        )
        return [dict(r) for r in rows]


# ── News settings repository ─────────────────────────────────────


class NewsSettingsRepository:
    """CRUD for news feeds, coin mappings, and word filters."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Feeds ────────────────────────────────────────────────────

    async def list_feeds(self) -> list[dict]:
        """Return all configured RSS news feeds."""
        rows = await self._db.fetch_all(
            "SELECT * FROM news_feeds ORDER BY id"
        )
        return [dict(r) for r in rows]

    async def count_feeds(self) -> int:
        """Return the number of configured feeds."""
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM news_feeds"
        )
        return row["cnt"]

    async def create_feed(self, name: str, url: str) -> int:
        """Add an RSS feed and return its id."""
        cursor = await self._db.execute(
            "INSERT INTO news_feeds (name, url) VALUES (?, ?)",
            (name, url),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def update_feed(
        self, feed_id: int, **fields: Any
    ) -> None:
        """Update name or enabled state for a feed."""
        allowed = {"name", "url", "enabled"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        await self._db.execute(
            f"UPDATE news_feeds SET {set_clause} WHERE id = ?",
            (*updates.values(), feed_id),
        )
        await self._db.commit()

    async def delete_feed(self, feed_id: int) -> None:
        """Remove an RSS feed by id."""
        await self._db.execute(
            "DELETE FROM news_feeds WHERE id = ?", (feed_id,)
        )
        await self._db.commit()

    # ── Coin mappings ────────────────────────────────────────────

    async def list_coin_mappings(self) -> list[dict]:
        """Return all coin name → symbol mappings."""
        rows = await self._db.fetch_all(
            "SELECT * FROM news_coin_mappings ORDER BY name"
        )
        return [dict(r) for r in rows]

    async def count_coin_mappings(self) -> int:
        """Return the number of stored coin mappings."""
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS cnt FROM news_coin_mappings"
        )
        return row["cnt"]

    async def create_coin_mapping(
        self, name: str, symbol: str, ambiguous: bool = False
    ) -> int:
        """Add a coin mapping and return its id."""
        cursor = await self._db.execute(
            "INSERT INTO news_coin_mappings (name, symbol, ambiguous) "
            "VALUES (?, ?, ?)",
            (name, symbol, int(ambiguous)),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def update_coin_mapping(
        self, mapping_id: int, **fields: Any
    ) -> None:
        """Update coin name, symbol, or ambiguous flag."""
        allowed = {"name", "symbol", "ambiguous"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        await self._db.execute(
            f"UPDATE news_coin_mappings SET {set_clause} WHERE id = ?",
            (*updates.values(), mapping_id),
        )
        await self._db.commit()

    async def delete_coin_mapping(self, mapping_id: int) -> None:
        """Delete a coin mapping by id."""
        await self._db.execute(
            "DELETE FROM news_coin_mappings WHERE id = ?",
            (mapping_id,),
        )
        await self._db.commit()

    # ── Word filters ─────────────────────────────────────────────

    async def list_word_filters(self) -> list[dict]:
        """Return all include/exclude word filters."""
        rows = await self._db.fetch_all(
            "SELECT * FROM news_word_filters ORDER BY filter_type, word"
        )
        return [dict(r) for r in rows]

    async def create_word_filter(
        self, word: str, filter_type: str
    ) -> int:
        """Add a word filter (include or exclude) and return its id."""
        if filter_type not in ("include", "exclude"):
            raise ValueError(
                f"filter_type must be 'include' or 'exclude', "
                f"got '{filter_type}'"
            )
        cursor = await self._db.execute(
            "INSERT INTO news_word_filters (word, filter_type) "
            "VALUES (?, ?)",
            (word.lower(), filter_type),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def delete_word_filter(self, filter_id: int) -> None:
        """Delete a word filter by id."""
        await self._db.execute(
            "DELETE FROM news_word_filters WHERE id = ?",
            (filter_id,),
        )
        await self._db.commit()

    # ── Engine parameters ────────────────────────────────────────

    async def get_param(
        self, key: str, default: str = ""
    ) -> str:
        """Return a news engine parameter value by key."""
        row = await self._db.fetch_one(
            "SELECT value FROM news_engine_params WHERE key = ?",
            (key,),
        )
        return row["value"] if row else default

    async def set_param(self, key: str, value: str) -> None:
        """Insert or replace a news engine parameter."""
        await self._db.execute(
            "INSERT INTO news_engine_params (key, value) "
            "VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self._db.commit()
