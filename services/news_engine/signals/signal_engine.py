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
import re

from services.news_engine.signals.signal_models import (
    EventDetectionResult,
    NewsSignal,
    ParsedArticle,
    SentimentResult,
)

logger = logging.getLogger(__name__)
_SUMMARY_MAX_LEN = 240
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


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


def _truncate_text(value: str, max_len: int = _SUMMARY_MAX_LEN) -> str:
    """Trim text for compact UI display without cutting mid-word badly."""
    value = value.strip()
    if len(value) <= max_len:
        return value

    shortened = value[: max_len - 1].rsplit(" ", 1)[0].strip()
    if not shortened:
        shortened = value[: max_len - 1].strip()
    return f"{shortened}..."


def _build_article_summary(
    article: ParsedArticle,
    signal_label: str,
) -> str:
    """Create a short user-facing explanation from the article context."""
    prefix = {
        "bullish": "Positive context",
        "bearish": "Negative context",
    }.get(signal_label, "Market context")

    title = article.title.strip()
    context = article.text.strip()
    if title and context.lower().startswith(title.lower()):
        context = context[len(title):].strip(" .:-")

    first_sentence = ""
    if context:
        parts = _SENTENCE_RE.split(context, maxsplit=1)
        first_sentence = parts[0].strip()

    if first_sentence and title and first_sentence.lower() != title.lower():
        combined = f"{title}. {first_sentence}"
    else:
        combined = title or first_sentence or context

    return f"{prefix}: {_truncate_text(combined)}"


class SignalEngine:
    """Computes trading signals from sentiment + events + keywords."""

    def generate_signals(
        self,
        article: ParsedArticle,
        coins: list[str],
        sentiment: SentimentResult,
        events: EventDetectionResult,
        rsi_context: dict[str, dict] | None = None,
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
        rsi_context = rsi_context or {}

        signals: list[NewsSignal] = []
        for coin in coins:
            coin_rsi = rsi_context.get(coin, {})
            rsi_short = coin_rsi.get("rsi_short")
            rsi_long = coin_rsi.get("rsi_long")

            sig = NewsSignal(
                coin=coin,
                signal=signal_label,
                score=round(signal_score, 2),
                confidence=round(confidence, 2),
                reason=reason,
                source=article.source,
                article_url=article.url,
                article_summary=_build_article_summary(
                    article,
                    signal_label,
                ),
                timestamp=article.timestamp,
                event_type=primary_event,
                rsi_short=rsi_short,
                rsi_long=rsi_long,
                rsi_state=coin_rsi.get("rsi_state"),
                investment_horizon=self._derive_horizon(
                    signal_score=signal_score,
                    rsi_short=rsi_short,
                    rsi_long=rsi_long,
                ),
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

    @staticmethod
    def _derive_horizon(
        signal_score: float,
        rsi_short: float | None,
        rsi_long: float | None,
    ) -> str:
        """Classify whether setup looks better for long or short horizon."""
        long_term = (
            rsi_long is not None
            and rsi_long <= 35
            and signal_score > 0
        )
        short_term = (
            rsi_short is not None
            and (
                (rsi_short <= 30 and signal_score > 0)
                or (40 <= rsi_short <= 60 and abs(signal_score) >= 2)
            )
        )
        avoid = (
            (rsi_short is not None and rsi_short >= 70 and signal_score < 0)
            or (rsi_long is not None and rsi_long >= 70 and signal_score < 0)
        )

        if long_term and short_term:
            return "both"
        if long_term:
            return "long_term"
        if short_term:
            return "short_term"
        if avoid:
            return "avoid"
        return "unknown"
