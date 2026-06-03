"""VADER-based sentiment analysis with optional transformer fallback.

Primary analysis uses VADER (vaderSentiment) per the specification.
The transformers-based FinBERT model is available as an optional
enhancement — disabled by default to keep the pipeline lightweight.
"""

import logging
from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from services.news_engine.signals.signal_models import (
    SentimentLabel,
    SentimentResult,
)

logger = logging.getLogger(__name__)


class SentimentModel:
    """VADER sentiment analyser with configurable transformer backend."""

    def __init__(self, use_transformer: bool = False) -> None:
        self._vader = SentimentIntensityAnalyzer()
        self._transformer_pipeline = None
        if use_transformer:
            self._load_transformer()

    def _load_transformer(self) -> None:
        """Optionally load ProsusAI/finbert for enhanced sentiment."""
        try:
            from transformers import pipeline

            self._transformer_pipeline = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
            )
            logger.info("FinBERT transformer model loaded.")
        except Exception as exc:
            logger.warning(
                "Could not load transformer model, using VADER only: %s",
                exc,
            )

    def analyse(self, text: str) -> Optional[SentimentResult]:
        """Analyse sentiment and return a SentimentResult.

        Returns None if analysis fails (e.g., empty text).
        """
        if not text or not text.strip():
            return None

        try:
            return self._analyse_vader(text)
        except Exception as exc:
            logger.warning(
                "Sentiment analysis failed: %s", exc
            )
            return None

    def _analyse_vader(self, text: str) -> SentimentResult:
        """Run VADER sentiment analysis."""
        scores = self._vader.polarity_scores(text)
        compound = scores["compound"]

        if compound >= 0.05:
            label = SentimentLabel.BULLISH
        elif compound <= -0.05:
            label = SentimentLabel.BEARISH
        else:
            label = SentimentLabel.NEUTRAL

        return SentimentResult(label=label, score=compound)
