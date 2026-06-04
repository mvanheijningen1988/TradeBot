"""Signal store — SQLite persistence and in-memory cache.

Stores signals in the manager's SQLite database and maintains an
in-memory ring buffer of the most recent 1000 signals globally.

Handles DB write failures by retaining signals in memory and
retrying on the next processing cycle.
"""

import logging
from collections import deque

from services.news_engine.signals.signal_models import NewsSignal

logger = logging.getLogger(__name__)

_MAX_IN_MEMORY = 1000
_MAX_DB_FAIL_CYCLES = 3


class SignalStore:
    """Persistent + in-memory signal storage."""

    def __init__(self, db=None) -> None:
        self._db = db
        self._cache: deque[NewsSignal] = deque(maxlen=_MAX_IN_MEMORY)
        self._pending_writes: list[NewsSignal] = []
        self._consecutive_failures: int = 0

    async def ensure_table(self) -> None:
        """Create the news_signals table if it doesn't exist."""
        if not self._db:
            return
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS news_signals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                coin        TEXT    NOT NULL,
                signal      TEXT    NOT NULL,
                score       REAL    NOT NULL,
                confidence  REAL    NOT NULL,
                reason      TEXT    NOT NULL DEFAULT '',
                event_type  TEXT,
                rsi_short   REAL,
                rsi_long    REAL,
                rsi_state   TEXT,
                investment_horizon TEXT NOT NULL DEFAULT 'unknown',
                source      TEXT    NOT NULL,
                article_url TEXT    NOT NULL,
                timestamp   TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await self._ensure_column("rsi_short", "REAL")
        await self._ensure_column("rsi_long", "REAL")
        await self._ensure_column("rsi_state", "TEXT")
        await self._ensure_column(
            "investment_horizon",
            "TEXT NOT NULL DEFAULT 'unknown'",
        )
        await self._db.commit()

    async def _ensure_column(self, name: str, column_def: str) -> None:
        """Add a column to news_signals if it does not exist yet."""
        rows = await self._db.fetch_all("PRAGMA table_info(news_signals)")
        existing = {row["name"] for row in rows}
        if name in existing:
            return
        await self._db.execute(
            f"ALTER TABLE news_signals ADD COLUMN {name} {column_def}"
        )

    async def save_signal(self, signal: NewsSignal) -> None:
        """Save a signal to DB and in-memory cache."""
        self._cache.append(signal)

        if not self._db:
            return

        try:
            await self._db.execute(
                """
                INSERT INTO news_signals
                    (coin, signal, score, confidence, reason,
                     event_type, rsi_short, rsi_long, rsi_state,
                     investment_horizon, source, article_url, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    signal.coin,
                    signal.signal,
                    signal.score,
                    signal.confidence,
                    signal.reason,
                    signal.event_type,
                    signal.rsi_short,
                    signal.rsi_long,
                    signal.rsi_state,
                    signal.investment_horizon,
                    signal.source,
                    signal.article_url,
                    signal.timestamp.isoformat(),
                ),
            )
            await self._db.commit()
            self._consecutive_failures = 0
        except Exception:
            self._consecutive_failures += 1
            self._pending_writes.append(signal)
            logger.exception(
                "DB write failed (attempt %d)",
                self._consecutive_failures,
            )
            if self._consecutive_failures >= _MAX_DB_FAIL_CYCLES:
                logger.critical(
                    "Database persistently unavailable for %d cycles.",
                    self._consecutive_failures,
                )

    async def flush_pending(self) -> None:
        """Retry writing pending signals to the database."""
        if not self._pending_writes or not self._db:
            return

        to_write = self._pending_writes.copy()
        self._pending_writes.clear()

        for signal in to_write:
            try:
                await self._db.execute(
                    """
                    INSERT INTO news_signals
                        (coin, signal, score, confidence, reason,
                         event_type, rsi_short, rsi_long, rsi_state,
                         investment_horizon, source, article_url, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signal.coin,
                        signal.signal,
                        signal.score,
                        signal.confidence,
                        signal.reason,
                        signal.event_type,
                        signal.rsi_short,
                        signal.rsi_long,
                        signal.rsi_state,
                        signal.investment_horizon,
                        signal.source,
                        signal.article_url,
                        signal.timestamp.isoformat(),
                    ),
                )
            except Exception:
                self._pending_writes.append(signal)
                logger.exception("Pending write retry failed")

        if not self._pending_writes:
            await self._db.commit()
            self._consecutive_failures = 0
            logger.info(
                "Flushed %d pending signals to DB.", len(to_write)
            )

    def get_latest(self, limit: int = 50) -> list[NewsSignal]:
        """Return the most recent signals from memory."""
        items = list(self._cache)
        items.reverse()
        return items[:limit]

    def get_by_coin(
        self, coin: str, limit: int = 20
    ) -> list[NewsSignal]:
        """Return recent signals for a specific coin from memory."""
        results = [s for s in reversed(self._cache) if s.coin == coin]
        return results[:limit]

    async def get_latest_from_db(
        self, limit: int = 50
    ) -> list[dict]:
        """Query latest signals from the database."""
        if not self._db:
            return [s.model_dump() for s in self.get_latest(limit)]
        rows = await self._db.fetch_all(
            """
            SELECT coin, signal, score, confidence, reason,
                     event_type, rsi_short, rsi_long, rsi_state,
                     investment_horizon, source, article_url, timestamp
            FROM news_signals
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in rows]

    def get_recommendations(self) -> dict:
        """Get investment recommendations based on recent signals.

        Returns bullish coins to consider investing in and bearish
        coins to consider removing from the portfolio.
        """
        invest: dict[str, dict] = {}
        remove: dict[str, dict] = {}

        for signal in reversed(list(self._cache)):
            coin = signal.coin
            if signal.signal in ("bullish", "strong bullish"):
                if coin not in invest:
                    invest[coin] = {
                        "coin": coin,
                        "signal": signal.signal,
                        "score": signal.score,
                        "confidence": signal.confidence,
                        "reason": signal.reason,
                        "rsi_short": signal.rsi_short,
                        "rsi_long": signal.rsi_long,
                        "rsi_state": signal.rsi_state,
                        "investment_horizon": signal.investment_horizon,
                        "source": signal.source,
                        "article_url": signal.article_url,
                        "timestamp": signal.timestamp.isoformat(),
                    }
            elif signal.signal in ("bearish", "strong bearish"):
                if coin not in remove:
                    remove[coin] = {
                        "coin": coin,
                        "signal": signal.signal,
                        "score": signal.score,
                        "confidence": signal.confidence,
                        "reason": signal.reason,
                        "rsi_short": signal.rsi_short,
                        "rsi_long": signal.rsi_long,
                        "rsi_state": signal.rsi_state,
                        "investment_horizon": signal.investment_horizon,
                        "source": signal.source,
                        "article_url": signal.article_url,
                        "timestamp": signal.timestamp.isoformat(),
                    }

        return {
            "invest": sorted(
                invest.values(),
                key=lambda x: x["score"],
                reverse=True,
            ),
            "remove": sorted(
                remove.values(),
                key=lambda x: x["score"],
            ),
        }
