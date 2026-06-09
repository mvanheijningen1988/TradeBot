"""Crypto News Signal Engine — main pipeline service.

Runs the full news→signal pipeline on a 5-minute cycle:
  1. Collect articles from RSS feeds
  2. Parse and clean articles
  3. Extract coin mentions
  4. Analyse sentiment (VADER)
  5. Detect market events (keyword classifier)
  6. Generate trading signals (scoring engine)
  7. Store signals (SQLite + in-memory cache)

Designed to run as a background asyncio task within the
TradeBot Manager FastAPI application.
"""

import asyncio
import contextlib
import logging
from typing import Optional

from services.news_engine.collector.news_collector import NewsCollector
from services.news_engine.config.coin_map import CoinMap
from services.news_engine.config.news_sources import NewsSource
from services.news_engine.ml.event_classifier import EventClassifier
from services.news_engine.ml.rsi_model import RSIModel
from services.news_engine.ml.sentiment_model import SentimentModel
from services.news_engine.processing.article_parser import ArticleParser
from services.news_engine.processing.coin_extractor import CoinExtractor
from services.news_engine.signals.signal_engine import SignalEngine
from services.news_engine.signals.signal_models import NewsArticle
from services.news_engine.signals.signal_store import SignalStore

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 300  # 5 minutes
_DEFAULT_POLL_INTERVAL_MINUTES = 5
_PARAM_POLL_INTERVAL_MINUTES = "poll_interval_minutes"
_PARAM_FINBERT_ENABLED = "finbert_enabled"


class NewsEngineService:
    """Main orchestrator for the crypto news signal pipeline."""

    def __init__(self, db=None, news_settings_repo=None) -> None:
        self._db = db
        self._settings_repo = news_settings_repo
        self._min_confidence: float = 0.0
        self._coin_map = CoinMap()
        self._collector = NewsCollector()
        self._parser = ArticleParser()
        self._extractor = CoinExtractor(self._coin_map)
        self._sentiment = SentimentModel()
        self._event_classifier = EventClassifier()
        self._rsi_model = RSIModel(db=db)
        self._signal_engine = SignalEngine()
        self._store = SignalStore(db=db)
        self._task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._cycle_lock = asyncio.Lock()
        self._active_cycles = 0
        self._running = False
        self._poll_interval_seconds = _POLL_INTERVAL

    @property
    def store(self) -> SignalStore:
        """Access the signal store for querying."""
        return self._store

    @property
    def is_running(self) -> bool:
        """Return True when the pipeline loop is active."""
        return self._running

    @property
    def is_processing(self) -> bool:
        """Return True while a processing cycle is currently running."""
        return self._active_cycles > 0

    @property
    def sentiment_model_name(self) -> str:
        """Return the active sentiment model name."""
        if self._sentiment.has_finbert:
            return "ensemble"
        return "vader"

    async def start(self) -> None:
        """Start the background pipeline loop."""
        if self._running:
            logger.warning("News engine already running.")
            return

        await self._store.ensure_table()
        await self._load_settings()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Crypto News Signal Engine started.")

    async def stop(self) -> None:
        """Stop the background pipeline loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._collector.close()
        logger.info("Crypto News Signal Engine stopped.")

    async def _run_loop(self) -> None:
        """Main loop — runs a processing cycle every 5 minutes."""
        while self._running:
            try:
                await self._run_cycle_once()
            except Exception:
                logger.exception("Processing cycle failed")
            await asyncio.sleep(self._poll_interval_seconds)

    async def _run_cycle_once(self) -> None:
        """Run one cycle with a lock and processing state tracking."""
        async with self._cycle_lock:
            self._active_cycles += 1
            try:
                await self._process_cycle()
            finally:
                self._active_cycles = max(0, self._active_cycles - 1)

    def trigger_refresh_cycle(self) -> bool:
        """Start an immediate cycle in the background if not already queued."""
        if self._refresh_task and not self._refresh_task.done():
            return False
        self._refresh_task = asyncio.create_task(self._run_cycle_once())
        return True

    async def reload_settings(self) -> None:
        """Public method to reload all settings from the DB immediately."""
        await self._load_settings()
        await self._store.purge_below_confidence(self._min_confidence)
        logger.info("News engine settings reloaded.")

    async def _load_settings(self) -> None:
        """Reload feeds, coin mappings, and word filters from the database."""
        if not self._settings_repo:
            return

        # Feeds → collector sources.
        feeds = await self._settings_repo.list_feeds()
        sources = [
            NewsSource(
                name=f["name"],
                url=f["url"],
                source_type=f.get("source_type", "rss"),
                weight=float(f.get("weight", 1.0) or 1.0),
            )
            for f in feeds
            if f["enabled"]
        ]
        self._collector.update_sources(sources)

        # Coin mappings → coin map + extractor.
        mappings = await self._settings_repo.list_coin_mappings()
        coins = {m["name"]: m["symbol"] for m in mappings}
        ambiguous = [
            m["symbol"] for m in mappings if m["ambiguous"]
        ]
        self._coin_map.load_from_db_data(coins, ambiguous)
        self._extractor.reload()

        # Word filters → article parser.
        filters = await self._settings_repo.list_word_filters()
        include_words = {
            f["word"] for f in filters if f["filter_type"] == "include"
        }
        exclude_words = {
            f["word"] for f in filters if f["filter_type"] == "exclude"
        }
        self._parser.update_filters(include_words, exclude_words)

        # Engine parameters.
        raw = await self._settings_repo.get_param(
            "min_confidence", "0.0"
        )
        try:
            self._min_confidence = float(raw)
        except ValueError:
            self._min_confidence = 0.0
        poll_raw = await self._settings_repo.get_param(
            _PARAM_POLL_INTERVAL_MINUTES,
            str(_DEFAULT_POLL_INTERVAL_MINUTES),
        )
        try:
            poll_minutes = max(float(poll_raw), 0.5)
        except ValueError:
            poll_minutes = _DEFAULT_POLL_INTERVAL_MINUTES
        self._poll_interval_seconds = int(poll_minutes * 60)
        finbert_default = "1" if self._sentiment.has_finbert else "0"
        finbert_raw = await self._settings_repo.get_param(
            _PARAM_FINBERT_ENABLED,
            finbert_default,
        )
        finbert_enabled = str(finbert_raw).strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        active_finbert = self._sentiment.set_finbert_enabled(finbert_enabled)
        logger.debug(
            "min_confidence threshold: %.2f", self._min_confidence
        )
        logger.debug("finbert enabled: %s", active_finbert)

    async def _process_cycle(self) -> None:
        """Execute one complete processing cycle."""
        logger.info("Starting news processing cycle.")

        # Reload settings (feeds, coin maps, word filters) from DB.
        await self._load_settings()

        # Flush any pending DB writes from previous failures.
        await self._store.flush_pending()

        # Step 1: Collect articles.
        articles = await self._collector.collect()
        if not articles:
            logger.info("No new articles collected.")
            return

        signal_count = 0

        for article in articles:
            try:
                signals = await self._process_article(article)
                for sig in signals:
                    await self._store.save_signal(sig)
                    signal_count += 1
            except Exception:
                logger.exception(
                    "Failed to process article %s",
                    article.url,
                )

        logger.info(
            "Cycle complete: %d articles processed, %d signals "
            "generated.",
            len(articles),
            signal_count,
        )

    async def _process_article(self, article):
        """Process a single article through the full pipeline."""
        # Step 2: Parse.
        parsed = self._parser.parse(article)
        if not parsed:
            return []

        # Step 3: Extract coins.
        coins = self._extractor.extract(parsed.text)
        if not coins:
            logger.debug(
                "No coins detected in article: %s", article.url
            )
            return []

        # Step 4: Sentiment analysis.
        sentiment = self._sentiment.analyse(parsed.text)
        if not sentiment:
            logger.warning(
                "Sentiment analysis failed for: %s", article.url
            )
            return []

        await self._store.save_article(
            NewsArticle(
                title=parsed.title,
                url=parsed.url,
                source=parsed.source,
                source_type=parsed.source_type,
                source_weight=parsed.source_weight,
                timestamp=parsed.timestamp,
                summary=article.summary or parsed.text[:320],
                content=parsed.text,
                sentiment_label=sentiment.label,
                sentiment_score=sentiment.score,
                coins=[],
            )
        )

        # Step 5: Event detection.
        events = self._event_classifier.detect(parsed.text)

        # Step 6: RSI context.
        rsi_context = await self._rsi_model.analyse(coins)

        # Step 7: Generate signals.
        signals = self._signal_engine.generate_signals(
            article=parsed,
            coins=coins,
            sentiment=sentiment,
            events=events,
            rsi_context=rsi_context,
        )

        # Filter by minimum confidence threshold.
        if self._min_confidence > 0.0:
            before = len(signals)
            signals = [
                s for s in signals
                if s.confidence >= self._min_confidence
            ]
            dropped = before - len(signals)
            if dropped:
                logger.debug(
                    "Dropped %d signal(s) below min_confidence "
                    "%.2f for %s",
                    dropped,
                    self._min_confidence,
                    article.url,
                )

        return signals

    async def run_once(self) -> int:
        """Run a single processing cycle (for testing/manual use).

        Returns the number of signals generated.
        """
        await self._store.ensure_table()
        self._extractor.reload()
        await self._store.flush_pending()

        articles = await self._collector.collect()
        if not articles:
            return 0

        count = 0
        for article in articles:
            try:
                signals = await self._process_article(article)
                for sig in signals:
                    await self._store.save_signal(sig)
                    count += 1
            except Exception:
                logger.exception(
                    "Failed to process article %s",
                    article.url,
                )
        return count
