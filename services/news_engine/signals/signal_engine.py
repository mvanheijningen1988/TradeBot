"""Signal scoring engine — Section 10 of the specification.

Implements the complete step-by-step signal calculation algorithm:
  1. Detect events → net_event_score (capped ±5)
  2. Count distinct event types → keyword_strength (capped 10)
  3. Calculate sentiment_score via VADER
  4. Determine keyword_sign (+1 or -1 based on event_score sign)
  5. signal_score = (sentiment * 3) + (event * 0.5) + (ks_sign * kw * 0.2)
  6. Map score to signal label via thresholds
  7. confidence = min(1.0, abs(signal_score) / 10)
"""

import logging

from services.news_engine.signals.signal_models import (
    EventDetectionResult,
    NewsSignal,
    ParsedArticle,
    SentimentResult,
)

logger = logging.getLogger(__name__)


def _score_to_signal(score: float) -> str:
    """Map signal_score to signal label per score interpretation."""
    if score >= 5:
        return "bullish"
    if score >= 2:
        return "bullish"
    if score <= -5:
        return "bearish"
    if score <= -2:
        return "bearish"
    return "neutral"


def _build_reason(events: EventDetectionResult) -> str:
    """Build comma-separated reason ordered by |event_score| desc."""
    if not events.events:
        return "sentiment_only"
    sorted_events = sorted(
        events.events,
        key=lambda e: abs(e.event_score),
        reverse=True,
    )
    return ", ".join(e.event_type for e in sorted_events)


class SignalEngine:
    """Computes trading signals from sentiment + events + keywords."""

    def generate_signals(
        self,
        article: ParsedArticle,
        coins: list[str],
        sentiment: SentimentResult,
        events: EventDetectionResult,
    ) -> list[NewsSignal]:
        """Generate one signal per detected coin.

        Suppresses neutral signals when no events are detected.
        """
        if not coins:
            logger.debug(
                "No coins detected, skipping: %s", article.url
            )
            return []

        event_score = events.net_event_score
        keyword_strength = events.keyword_strength

        # Step 5: keyword_sign
        keyword_sign = -1 if event_score < 0 else 1

        # Step 6: compute signal_score
        signal_score = (
            (sentiment.score * 3)
            + (event_score * 0.5)
            + (keyword_sign * keyword_strength * 0.2)
        )

        # Step 7: map to label
        signal_label = _score_to_signal(signal_score)

        # Step 8: confidence
        confidence = min(1.0, abs(signal_score) / 10)

        # Suppress neutral signals with no events.
        if signal_label == "neutral" and not events.has_events:
            logger.debug(
                "Suppressing neutral sentiment-only signal for %s",
                article.url,
            )
            return []

        reason = _build_reason(events)
        primary_event = (
            events.events[0].event_type if events.events else None
        )

        signals: list[NewsSignal] = []
        for coin in coins:
            sig = NewsSignal(
                coin=coin,
                signal=signal_label,
                score=round(signal_score, 2),
                confidence=round(confidence, 2),
                reason=reason,
                source=article.source,
                article_url=article.url,
                timestamp=article.timestamp,
                event_type=primary_event,
            )
            signals.append(sig)
            logger.info(
                "%s signal for %s (score=%.2f, conf=%.2f) "
                "from %s: %s",
                signal_label.upper(),
                coin,
                signal_score,
                confidence,
                article.source,
                reason,
            )

        return signals
