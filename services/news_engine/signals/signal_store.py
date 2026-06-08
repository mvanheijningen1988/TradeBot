"""Signal store — SQLite persistence and in-memory cache.

Stores signals in the manager's SQLite database and maintains an
in-memory ring buffer of the most recent 1000 signals globally.

Handles DB write failures by retaining signals in memory and
retrying on the next processing cycle.
"""

import logging
from collections import deque
import json
from datetime import datetime, timezone

from services.news_engine.signals.signal_models import (
    NewsArticle,
    NewsSignal,
    SentimentLabel,
)

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
                article_summary TEXT NOT NULL DEFAULT '',
                timestamp   TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await self._ensure_column("rsi_short", "REAL")
        await self._ensure_column("rsi_long", "REAL")
        await self._ensure_column("rsi_state", "TEXT")
        await self._ensure_column(
            "article_summary",
            "TEXT NOT NULL DEFAULT ''",
        )
        await self._ensure_column(
            "investment_horizon",
            "TEXT NOT NULL DEFAULT 'unknown'",
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS news_articles (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                title           TEXT    NOT NULL,
                url             TEXT    NOT NULL UNIQUE,
                source          TEXT    NOT NULL,
                source_type     TEXT    NOT NULL DEFAULT 'rss',
                source_weight   REAL    NOT NULL DEFAULT 1.0,
                sentiment_label TEXT    NOT NULL,
                sentiment_score REAL    NOT NULL,
                summary         TEXT    NOT NULL DEFAULT '',
                content         TEXT    NOT NULL DEFAULT '',
                coins_json      TEXT    NOT NULL DEFAULT '[]',
                timestamp       TEXT    NOT NULL,
                created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        await self._ensure_article_column(
            "source_type",
            "TEXT NOT NULL DEFAULT 'rss'",
        )
        await self._ensure_article_column(
            "source_weight",
            "REAL NOT NULL DEFAULT 1.0",
        )
        await self._ensure_article_column(
            "coins_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        await self._db.commit()

    async def _ensure_article_column(self, name: str, column_def: str) -> None:
        """Add a column to news_articles if it does not exist yet."""
        rows = await self._db.fetch_all("PRAGMA table_info(news_articles)")
        existing = {row["name"] for row in rows}
        if name in existing:
            return
        await self._db.execute(
            f"ALTER TABLE news_articles ADD COLUMN {name} {column_def}"
        )

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
                     investment_horizon, source, article_url,
                     article_summary, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    signal.article_summary,
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
                         investment_horizon, source, article_url,
                         article_summary, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        signal.article_summary,
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

    async def save_article(
        self,
        article: NewsArticle,
    ) -> None:
        """Persist a news article snapshot for the news page."""
        if not self._db:
            return

        await self._db.execute(
            """
            INSERT INTO news_articles
                (title, url, source, source_type, source_weight,
                 sentiment_label, sentiment_score, summary, content,
                 coins_json, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                title = excluded.title,
                source = excluded.source,
                source_type = excluded.source_type,
                source_weight = excluded.source_weight,
                sentiment_label = excluded.sentiment_label,
                sentiment_score = excluded.sentiment_score,
                summary = excluded.summary,
                content = excluded.content,
                coins_json = excluded.coins_json,
                timestamp = excluded.timestamp
            """,
            (
                article.title,
                article.url,
                article.source,
                article.source_type,
                article.source_weight,
                article.sentiment_label.value,
                article.sentiment_score,
                article.summary,
                article.content,
                json.dumps(article.coins),
                article.timestamp.isoformat(),
            ),
        )
        await self._db.commit()

    def get_latest(self, limit: int = 50) -> list[NewsSignal]:
        """Return the most recent signals from memory."""
        items = list(self._cache)
        items.reverse()
        return items[:limit]

    async def get_latest_articles(self, limit: int = 100) -> list[dict]:
        """Return the most recent article snapshots from the database."""
        if not self._db:
            return []
        rows = await self._db.fetch_all(
            """
            SELECT title, url, source, source_type, source_weight,
                   sentiment_label, sentiment_score, summary, content,
                   coins_json, timestamp
            FROM news_articles
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        )
        articles: list[dict] = []
        for row in rows:
            article = dict(row)
            article["coins"] = json.loads(article.pop("coins_json") or "[]")
            articles.append(article)
        return articles

    @staticmethod
    def _score_to_label(score: float) -> str:
        """Map a weighted score to a human-friendly day label."""
        if score >= 0.15:
            return "positive"
        if score <= -0.15:
            return "negative"
        return "neutral"

    @staticmethod
    def _article_weight(article: dict, now: datetime) -> float:
        """Return the weighted importance for a single article."""
        timestamp = article.get("timestamp", "")
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        age_hours = max((now - parsed).total_seconds() / 3600.0, 0.0)
        recency_weight = 1.0 / (1.0 + age_hours)
        source_type = str(article.get("source_type") or "rss")
        source_type_weight = 1.0 if source_type == "rss" else 0.9
        source_weight = float(article.get("source_weight") or 1.0)
        return recency_weight * source_type_weight * source_weight

    async def get_news_overview(self, limit: int = 100) -> dict:
        """Return a weighted sentiment summary for recent articles."""
        articles = await self.get_latest_articles(limit=limit)
        if not articles:
            return {
                "overall_score": 0.0,
                "label": "neutral",
                "positive_day": False,
                "article_count": 0,
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
            }

        now = datetime.now(timezone.utc)
        total_weight = 0.0
        weighted_score = 0.0
        counts = {"positive": 0, "negative": 0, "neutral": 0}

        for article in articles:
            weight = self._article_weight(article, now)
            score = float(article.get("sentiment_score") or 0.0)
            weighted_score += score * weight
            total_weight += weight

            label = str(article.get("sentiment_label") or "neutral")
            if label == SentimentLabel.BULLISH.value:
                counts["positive"] += 1
            elif label == SentimentLabel.BEARISH.value:
                counts["negative"] += 1
            else:
                counts["neutral"] += 1

        overall_score = weighted_score / total_weight if total_weight else 0.0
        label = self._score_to_label(overall_score)

        return {
            "overall_score": round(overall_score, 4),
            "label": label,
            "positive_day": label == "positive",
            "article_count": len(articles),
            "positive_count": counts["positive"],
            "negative_count": counts["negative"],
            "neutral_count": counts["neutral"],
        }

    async def purge_below_confidence(
        self, threshold: float
    ) -> None:
        """Remove signals below *threshold* from memory and the DB."""
        if threshold <= 0.0:
            return
        before = len(self._cache)
        self._cache = deque(
            (s for s in self._cache if s.confidence >= threshold),
            maxlen=_MAX_IN_MEMORY,
        )
        purged_mem = before - len(self._cache)

        if not self._db:
            if purged_mem:
                logger.info(
                    "Purged %d in-memory signal(s) below "
                    "confidence %.2f (no DB).",
                    purged_mem,
                    threshold,
                )
            return

        try:
            await self._db.execute(
                "DELETE FROM news_signals WHERE confidence < ?",
                (threshold,),
            )
            await self._db.commit()
            logger.info(
                "Purged signal(s) below confidence %.2f "
                "(%d from memory).",
                threshold,
                purged_mem,
            )
        except Exception:
            logger.exception(
                "Failed to purge low-confidence signals from DB"
            )

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
                     investment_horizon, source, article_url,
                     article_summary, timestamp
            FROM news_signals
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [dict(r) for r in rows]

    @staticmethod
    def _normalize_signal_label(value: str) -> str:
        """Normalize signal labels to support legacy underscore values."""
        return (value or "").strip().lower().replace("_", " ")

    @classmethod
    def _build_recommendations(cls, items: list[dict]) -> dict:
        """Build unique invest/remove recommendations from signal items."""
        invest: dict[str, dict] = {}
        remove: dict[str, dict] = {}

        for signal in items:
            coin = signal["coin"]
            label = cls._normalize_signal_label(signal["signal"])
            if label in ("bullish", "strong bullish") and coin not in invest:
                invest[coin] = signal
            elif label in ("bearish", "strong bearish") and coin not in remove:
                remove[coin] = signal

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

    async def get_recommendations(self, limit: int = 300) -> dict:
        """Return recommendations from cache with DB fallback.

        Uses in-memory cache first for fresh real-time signals. If cache is
        empty (e.g. directly after manager restart), it falls back to latest
        persisted signals from the database.
        """
        cache_items = [
            {
                "coin": signal.coin,
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
                "article_summary": signal.article_summary,
                "timestamp": signal.timestamp.isoformat(),
            }
            for signal in reversed(list(self._cache))
        ]
        if cache_items:
            return self._build_recommendations(cache_items)

        db_items = await self.get_latest_from_db(limit=limit)
        return self._build_recommendations(db_items)
