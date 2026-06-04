"""Sentiment analysis with VADER and optional FinBERT ensemble.

Primary analysis uses VADER (vaderSentiment).  When the FinBERT
transformer model is enabled the two scores are blended into a
weighted ensemble (70 % FinBERT, 30 % VADER) for higher accuracy
on financial/crypto text.

FinBERT is disabled by default to keep the pipeline lightweight.
Enable it by passing ``use_transformer=True`` or by setting the
``NEWS_ENGINE_USE_FINBERT=1`` environment variable.
"""

import logging
import os
from typing import Optional

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from services.news_engine.signals.signal_models import (
    SentimentLabel,
    SentimentResult,
)

logger = logging.getLogger(__name__)

# FinBERT label → normalised score direction
_FINBERT_LABEL_MAP: dict[str, float] = {
    "positive": 1.0,
    "negative": -1.0,
    "neutral": 0.0,
}

# Ensemble weights (must sum to 1.0)
_FINBERT_WEIGHT = 0.7
_VADER_WEIGHT = 0.3

# FinBERT max input tokens (model limit is 512 WordPiece tokens;
# we truncate the raw text to a safe character count beforehand).
_MAX_INPUT_CHARS = 1500


class SentimentModel:
    """Sentiment analyser with optional FinBERT ensemble."""

    def __init__(self, use_transformer: bool = False) -> None:
        self._vader = SentimentIntensityAnalyzer()
        self._transformer_pipeline = None

        # Allow env-var override: NEWS_ENGINE_USE_FINBERT=1
        env_flag = os.getenv("NEWS_ENGINE_USE_FINBERT", "").strip()
        if use_transformer or env_flag in ("1", "true", "yes"):
            self._load_transformer()

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_transformer(self) -> None:
        """Load ProsusAI/finbert for financial sentiment."""
        try:
            from transformers import pipeline  # noqa: WPS433

            self._transformer_pipeline = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                tokenizer="ProsusAI/finbert",
                truncation=True,
                max_length=512,
            )
            logger.info("FinBERT transformer model loaded.")
        except Exception as exc:
            logger.warning(
                "Could not load FinBERT, falling back to VADER: %s",
                exc,
            )

    @property
    def has_finbert(self) -> bool:
        """Return True when FinBERT is loaded and available."""
        return self._transformer_pipeline is not None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyse(self, text: str) -> Optional[SentimentResult]:
        """Analyse sentiment and return a SentimentResult.

        When FinBERT is available an ensemble score is produced.
        Falls back to VADER-only when FinBERT is unavailable or
        fails at runtime.
        """
        if not text or not text.strip():
            return None

        try:
            vader_result = self._analyse_vader(text)

            if self._transformer_pipeline is not None:
                finbert_result = self._analyse_finbert(text)
                if finbert_result is not None:
                    return self._ensemble(vader_result, finbert_result)

            return vader_result
        except Exception as exc:
            logger.warning("Sentiment analysis failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # VADER
    # ------------------------------------------------------------------

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

        return SentimentResult(label=label, score=compound, model="vader")

    # ------------------------------------------------------------------
    # FinBERT
    # ------------------------------------------------------------------

    def _analyse_finbert(self, text: str) -> Optional[SentimentResult]:
        """Run FinBERT sentiment analysis.

        Returns None when inference fails so the caller can fall
        back to VADER.
        """
        try:
            # Truncate to stay within token limits
            truncated = text[:_MAX_INPUT_CHARS]

            result = self._transformer_pipeline(truncated)[0]
            raw_label: str = result["label"].lower()
            confidence: float = result["score"]

            direction = _FINBERT_LABEL_MAP.get(raw_label, 0.0)
            score = round(direction * confidence, 4)

            if score >= 0.05:
                label = SentimentLabel.BULLISH
            elif score <= -0.05:
                label = SentimentLabel.BEARISH
            else:
                label = SentimentLabel.NEUTRAL

            return SentimentResult(
                label=label, score=score, model="finbert"
            )
        except Exception as exc:
            logger.warning("FinBERT inference failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Ensemble
    # ------------------------------------------------------------------

    @staticmethod
    def _ensemble(
        vader: SentimentResult,
        finbert: SentimentResult,
    ) -> SentimentResult:
        """Blend VADER and FinBERT into a weighted ensemble score."""
        blended = round(
            (_VADER_WEIGHT * vader.score)
            + (_FINBERT_WEIGHT * finbert.score),
            4,
        )

        if blended >= 0.05:
            label = SentimentLabel.BULLISH
        elif blended <= -0.05:
            label = SentimentLabel.BEARISH
        else:
            label = SentimentLabel.NEUTRAL

        return SentimentResult(
            label=label, score=blended, model="ensemble"
        )
