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
    ) -> int:
        cursor = await self._db.execute(
            "INSERT INTO users (username, password_hash, role, language) "
            "VALUES (?, ?, ?, ?)",
            (username, password_hash, role, language),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_by_username(self, username: str) -> Optional[dict]:
        row = await self._db.fetch_one(
            "SELECT * FROM users WHERE username = ?", (username,)
        )
        return dict(row) if row else None

    async def get_by_id(self, user_id: int) -> Optional[dict]:
        row = await self._db.fetch_one(
            "SELECT * FROM users WHERE id = ?", (user_id,)
        )
        return dict(row) if row else None

    async def list_all(self) -> list[dict]:
        rows = await self._db.fetch_all(
            "SELECT id, username, role, language, created_at FROM users"
        )
        return [dict(r) for r in rows]

    async def update(self, user_id: int, **fields: Any) -> None:
        allowed = {"username", "password_hash", "role", "language"}
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
        await self._db.execute("DELETE FROM users WHERE id = ?", (user_id,))
        await self._db.commit()

    async def count(self) -> int:
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
        cursor = await self._db.execute(
            "INSERT INTO exchanges (name, api_key, api_secret, rate_limit) "
            "VALUES (?, ?, ?, ?)",
            (name, api_key, api_secret, rate_limit),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_by_id(self, exchange_id: int) -> Optional[dict]:
        row = await self._db.fetch_one(
            "SELECT * FROM exchanges WHERE id = ?", (exchange_id,)
        )
        return dict(row) if row else None

    async def list_all(self) -> list[dict]:
        rows = await self._db.fetch_all(
            "SELECT id, name, rate_limit, enabled, created_at FROM exchanges"
        )
        return [dict(r) for r in rows]

    async def update(self, exchange_id: int, **fields: Any) -> None:
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
        cursor = await self._db.execute(
            "INSERT INTO workers (agent_id, address, version) "
            "VALUES (?, ?, ?)",
            (agent_id, address, version),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def get_by_agent_id(self, agent_id: str) -> Optional[dict]:
        row = await self._db.fetch_one(
            "SELECT * FROM workers WHERE agent_id = ?", (agent_id,)
        )
        return dict(row) if row else None

    async def get_by_id(self, worker_id: int) -> Optional[dict]:
        row = await self._db.fetch_one(
            "SELECT * FROM workers WHERE id = ?", (worker_id,)
        )
        return dict(row) if row else None

    async def list_all(self) -> list[dict]:
        rows = await self._db.fetch_all("SELECT * FROM workers")
        return [dict(r) for r in rows]

    async def update_status(
        self, worker_id: int, status: str
    ) -> None:
        await self._db.execute(
            "UPDATE workers SET status = ? WHERE id = ?",
            (status, worker_id),
        )
        await self._db.commit()

    async def update_heartbeat(self, worker_id: int) -> None:
        await self._db.execute(
            "UPDATE workers SET last_heartbeat = datetime('now') "
            "WHERE id = ?",
            (worker_id,),
        )
        await self._db.commit()

    async def approve(self, worker_id: int) -> None:
        await self._db.execute(
            "UPDATE workers SET approved = 1, status = 'approved' "
            "WHERE id = ?",
            (worker_id,),
        )
        await self._db.commit()

    async def reject(self, worker_id: int) -> None:
        await self._db.execute(
            "UPDATE workers SET approved = 0, status = 'rejected' "
            "WHERE id = ?",
            (worker_id,),
        )
        await self._db.commit()

    async def delete(self, worker_id: int) -> None:
        await self._db.execute(
            "DELETE FROM workers WHERE id = ?", (worker_id,)
        )
        await self._db.commit()

    async def get_approved_online(self) -> list[dict]:
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
        row = await self._db.fetch_one(
            "SELECT * FROM bots WHERE id = ?", (bot_id,)
        )
        if not row:
            return None
        d = dict(row)
        d["strategy_params"] = json.loads(d["strategy_params"])
        return d

    async def get_by_uuid(self, bot_uuid: str) -> Optional[dict]:
        row = await self._db.fetch_one(
            "SELECT * FROM bots WHERE uuid = ?", (bot_uuid,)
        )
        if not row:
            return None
        d = dict(row)
        d["strategy_params"] = json.loads(d["strategy_params"])
        return d

    async def list_all(self) -> list[dict]:
        rows = await self._db.fetch_all("SELECT * FROM bots ORDER BY id")
        result = []
        for r in rows:
            d = dict(r)
            d["strategy_params"] = json.loads(d["strategy_params"])
            result.append(d)
        return result

    async def list_by_worker(self, worker_id: int) -> list[dict]:
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
        await self._db.execute(
            "UPDATE bots SET status = ?, updated_at = datetime('now') "
            "WHERE id = ?",
            (status, bot_id),
        )
        await self._db.commit()

    async def assign_worker(
        self, bot_id: int, worker_id: int, manual: bool = False
    ) -> None:
        await self._db.execute(
            "UPDATE bots SET worker_id = ?, manual_assign = ?, "
            "status = 'assigning', updated_at = datetime('now') "
            "WHERE id = ?",
            (worker_id, int(manual), bot_id),
        )
        await self._db.commit()

    async def update(self, bot_id: int, **fields: Any) -> None:
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
        await self._db.execute(
            "DELETE FROM bots WHERE id = ?", (bot_id,)
        )
        await self._db.commit()

    async def get_next_operator_id(self) -> int:
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
        rows = await self._db.fetch_all(
            "SELECT * FROM order_history WHERE bot_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (bot_id, limit),
        )
        return [dict(r) for r in rows]

    async def update_status(
        self, order_id: int, status: str
    ) -> None:
        await self._db.execute(
            "UPDATE order_history SET status = ?, "
            "updated_at = datetime('now') WHERE id = ?",
            (status, order_id),
        )
        await self._db.commit()


# ── Trade history repository ─────────────────────────────────────


class TradeHistoryRepository:
    """Persisted trade records."""

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
        rows = await self._db.fetch_all(
            "SELECT * FROM trade_history WHERE bot_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (bot_id, limit),
        )
        return [dict(r) for r in rows]


# ── Budget history repository ────────────────────────────────────


class BudgetHistoryRepository:
    """Budget snapshots for trend graphs."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, bot_id: int, balance: float) -> None:
        await self._db.execute(
            "INSERT INTO budget_history (bot_id, balance) VALUES (?, ?)",
            (bot_id, balance),
        )
        await self._db.commit()

    async def get_history(
        self, bot_id: int, limit: int = 500
    ) -> list[dict]:
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
            conditions.append("level = ?")
            params.append(level)

        where = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = await self._db.fetch_all(
            f"SELECT * FROM log_entries {where} "
            "ORDER BY id DESC LIMIT ?",
            tuple(params),
        )
        return [dict(r) for r in rows]
