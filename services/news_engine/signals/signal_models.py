"""Pydantic data models for the news signal engine pipeline."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    """Signal direction derived from score thresholds."""

    STRONG_BULLISH = "strong bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong bearish"


class SentimentLabel(str, Enum):
    """VADER sentiment classification."""

    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"


class RSIState(str, Enum):
    """RSI state buckets used for signal interpretation."""

    OVERBOUGHT = "overbought"
    OVERSOLD = "oversold"
    NEUTRAL = "neutral"


class Article(BaseModel):
    """Raw article collected from an RSS feed."""

    title: str
    url: str
    source: str
    timestamp: datetime
    summary: str = ""
    content: str = ""
    content_hash: str = ""


class ParsedArticle(BaseModel):
    """Article after HTML cleaning and text normalisation."""

    text: str
    title: str
    url: str
    source: str
    timestamp: datetime


class SentimentResult(BaseModel):
    """Output of sentiment analysis (VADER, FinBERT, or ensemble)."""

    label: SentimentLabel
    score: float = Field(ge=-1.0, le=1.0)
    model: str = "vader"


class DetectedEvent(BaseModel):
    """A single detected market event."""

    event_type: str
    event_score: int
    matched_keywords: list[str] = Field(default_factory=list)


class EventDetectionResult(BaseModel):
    """Aggregated event detection for one article."""

    events: list[DetectedEvent] = Field(default_factory=list)
    net_event_score: int = 0
    keyword_strength: int = 0

    @property
    def has_events(self) -> bool:
        return len(self.events) > 0


class NewsSignal(BaseModel):
    """Final trading signal produced by the engine."""

    coin: str
    signal: str
    score: float
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    source: str
    article_url: str
    article_summary: str = ""
    timestamp: datetime
    event_type: Optional[str] = None
    rsi_short: Optional[float] = None
    rsi_long: Optional[float] = None
    rsi_state: Optional[str] = None
    investment_horizon: str = "unknown"

    class Config:
        from_attributes = True
