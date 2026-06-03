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
import logging
from typing import Optional

from services.news_engine.collector.news_collector import NewsCollector
from services.news_engine.config.coin_map import CoinMap
from services.news_engine.ml.event_classifier import EventClassifier
from services.news_engine.ml.sentiment_model import SentimentModel
from services.news_engine.processing.article_parser import ArticleParser
from services.news_engine.processing.coin_extractor import CoinExtractor
from services.news_engine.signals.signal_engine import SignalEngine
from services.news_engine.signals.signal_store import SignalStore

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 300  # 5 minutes


class NewsEngineService:
    """Main orchestrator for the crypto news signal pipeline."""

    def __init__(self, db=None) -> None:
        self._db = db
        self._coin_map = CoinMap()
        self._collector = NewsCollector()
        self._parser = ArticleParser()
        self._extractor = CoinExtractor(self._coin_map)
        self._sentiment = SentimentModel()
        self._event_classifier = EventClassifier()
        self._signal_engine = SignalEngine()
        self._store = SignalStore(db=db)
        self._task: Optional[asyncio.Task] = None
        self._running = False

    @property
    def store(self) -> SignalStore:
        """Access the signal store for querying."""
        return self._store

    async def start(self) -> None:
        """Start the background pipeline loop."""
        if self._running:
            logger.warning("News engine already running.")
            return

        await self._store.ensure_table()
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Crypto News Signal Engine started.")

    async def stop(self) -> None:
        """Stop the background pipeline loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._collector.close()
        logger.info("Crypto News Signal Engine stopped.")

    async def _run_loop(self) -> None:
        """Main loop — runs a processing cycle every 5 minutes."""
        while self._running:
            try:
                await self._process_cycle()
            except Exception as exc:
                logger.error(
                    "Processing cycle failed: %s", exc, exc_info=True
                )
            await asyncio.sleep(_POLL_INTERVAL)

    async def _process_cycle(self) -> None:
        """Execute one complete processing cycle."""
        logger.info("Starting news processing cycle.")

        # Check for coin mapping updates.
        self._extractor.reload()

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
            except Exception as exc:
                logger.error(
                    "Failed to process article %s: %s",
                    article.url,
                    exc,
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

        # Step 5: Event detection.
        events = self._event_classifier.detect(parsed.text)

        # Step 6: Generate signals.
        signals = self._signal_engine.generate_signals(
            article=parsed,
            coins=coins,
            sentiment=sentiment,
            events=events,
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
            except Exception as exc:
                logger.error(
                    "Failed to process article %s: %s",
                    article.url,
                    exc,
                )
        return count
