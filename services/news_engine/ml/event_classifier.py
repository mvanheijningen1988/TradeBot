"""Keyword-based event classifier per Section 9 of the specification.

Detects market events using case-insensitive substring search with
the keyword-to-event-type mapping table defined in the SKILL.md.
"""

import logging
from typing import Any

from services.news_engine.signals.signal_models import (
    DetectedEvent,
    EventDetectionResult,
)

logger = logging.getLogger(__name__)

# Event type → (score, keywords list).
EVENT_DEFINITIONS: dict[str, tuple[int, list[str]]] = {
    # Bullish events
    "exchange_listing": (
        5,
        [
            "listed on",
            "listing on",
            "now available on",
            "binance listing",
            "coinbase listing",
            "added to exchange",
        ],
    ),
    "partnership_announcement": (
        4,
        [
            "partnership with",
            "partners with",
            "strategic partnership",
            "announces partnership",
        ],
    ),
    "etf_approval": (
        5,
        ["etf approved", "etf approval", "spot etf", "sec approves"],
    ),
    "mainnet_launch": (
        4,
        [
            "mainnet launch",
            "mainnet goes live",
            "launches mainnet",
            "mainnet upgrade",
        ],
    ),
    "token_burn": (
        3,
        ["token burn", "burns tokens", "deflationary burn", "coin burn"],
    ),
    "integration": (
        3,
        [
            "integrates with",
            "integration with",
            "integrated into",
            "now supports",
        ],
    ),
    "institutional_adoption": (
        4,
        [
            "institutional",
            "hedge fund",
            "asset manager",
            "adds to balance sheet",
        ],
    ),
    # Bearish events
    "exchange_delisting": (
        -4,
        ["delisted from", "delisting from", "removed from exchange"],
    ),
    "security_exploit": (
        -5,
        [
            "security exploit",
            "exploited for",
            "exploit attack",
            "vulnerability exploit",
            "zero-day",
            "security flaw",
        ],
    ),
    "hack": (
        -5,
        [
            "was hacked",
            "hack attack",
            "got hacked",
            "stolen funds",
            "data breach",
            "funds stolen",
        ],
    ),
    "regulatory_ban": (
        -4,
        [
            "crypto banned",
            "cryptocurrency banned",
            "trading banned",
            "regulatory ban",
            "government bans crypto",
            "outlawed cryptocurrency",
        ],
    ),
    "lawsuit": (
        -3,
        [
            "lawsuit",
            "sued",
            "legal action",
            "class action",
            "sec charges",
        ],
    ),
    "project_shutdown": (
        -5,
        [
            "shut down",
            "shutting down",
            "project abandoned",
            "ceasing operations",
        ],
    ),
}


class EventClassifier:
    """Keyword-based market event detector."""

    def __init__(
        self,
        definitions: dict[str, tuple[int, list[str]]] | None = None,
    ) -> None:
        self._definitions = definitions or EVENT_DEFINITIONS

    def detect(self, text: str) -> EventDetectionResult:
        """Detect all events in the given article text."""
        text_lower = text.lower()
        events: list[DetectedEvent] = []

        for event_type, (score, keywords) in self._definitions.items():
            matched = [kw for kw in keywords if kw in text_lower]
            if matched:
                events.append(
                    DetectedEvent(
                        event_type=event_type,
                        event_score=score,
                        matched_keywords=matched,
                    )
                )

        # Calculate net event score with capping.
        net = sum(e.event_score for e in events)
        if net > 0:
            net = min(net, 5)
        elif net < 0:
            net = max(net, -5)

        keyword_strength = min(len(events), 10)

        if events:
            logger.debug(
                "Detected %d event types (net_score=%d, kw_str=%d)",
                len(events),
                net,
                keyword_strength,
            )

        return EventDetectionResult(
            events=events,
            net_event_score=net,
            keyword_strength=keyword_strength,
        )
