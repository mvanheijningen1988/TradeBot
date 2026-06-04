# Functional Requirements — Crypto News Signal Engine

## 1. Purpose

The Crypto News Signal Engine analyzes cryptocurrency news and produces structured trading signals based on detected events, sentiment, and coin mentions.

The engine must not execute trades.  
It only produces signals that can be consumed by the strategy engine.

Signals represent potential bullish or bearish market events.

---

# 2. High-Level Architecture

The system must implement a pipeline consisting of the following stages:

1. News ingestion
2. Article parsing
3. Coin extraction
4. Sentiment analysis
5. Event detection
6. Signal scoring
7. Signal storage and publishing

Pipeline flow:

News Sources  
→ News Collector  
→ Article Parser  
→ Coin Extraction  
→ Sentiment Analysis  
→ Event Detection  
→ Signal Scoring  
→ Signal Store  
→ Strategy Engine Consumption

All components must be implemented as modular Python services.

---

# 3. Technology Requirements

Language:
Python 3.12+

Libraries:

News ingestion
- feedparser
- aiohttp

Text processing
- spaCy
- vaderSentiment

Async execution
- asyncio

Data models
- pydantic

Logging
- Python logging module

All network operations must be asynchronous.

---

# 4. News Sources

The engine must support RSS feeds.

Initial supported sources:

CoinDesk  
https://www.coindesk.com/arc/outboundfeeds/rss/

CoinTelegraph  
https://cointelegraph.com/rss

Decrypt  
https://decrypt.co/feed

BeInCrypto  
https://beincrypto.com/feed/

The system must allow additional RSS feeds to be added via configuration.

---

# 5. News Collector

The News Collector retrieves articles from RSS feeds.

Functional requirements:

The collector must:

- fetch RSS feeds asynchronously
- extract article metadata
- avoid duplicate articles
- normalize timestamps
- cache previously processed articles

If an RSS feed returns HTTP 429 or 503, apply exponential backoff starting at 30 seconds, doubling up to a maximum of 10 minutes, before retrying that feed.

Collected article fields:

title  
url  
source  
timestamp  
summary  
content (optional if available)

Example output:

{
"title": "Solana announces major partnership with Visa",
"url": "https://...",
"source": "CoinDesk",
"timestamp": "2026-05-10T12:32:00Z",
"content": "Solana has partnered with Visa to..."
}

Duplicate detection must be based on URL or content hash.

---

# 6. Article Parser

The Article Parser extracts relevant text from the article.

Requirements:

- remove HTML tags
- normalize whitespace
- combine title and content into a single analysis text

Only process English-language articles. Use language detection (e.g., the article feed language tag or a detection library) and skip non-English articles at the parsing stage, logging at DEBUG level with the article_url.

Output:

{
"text": "Solana announces major partnership with Visa...",
"title": "...",
"source": "...",
"timestamp": "..."
}

---

# 7. Coin Extraction

The system must detect cryptocurrencies mentioned in the article.

Detection methods:

1. Coin symbol detection (BTC, ETH, SOL)
2. Coin name detection (Bitcoin, Ethereum, Solana)

Coin symbol matching must require symbols to appear as whole words (not substrings) and be uppercase in the source text. For ambiguous symbols that are common English words (e.g., ONE, NEAR, SAND), require the coin's full name to also appear in the article to confirm the match.

A coin mapping dictionary must be used.

The coin mapping dictionary must be configurable via an external JSON or YAML file, reloaded without service restart. The coin mapping file must be checked for changes every processing cycle (5 minutes). Use file modification timestamp to detect changes.

If the coin mapping file is missing or malformed at startup, fail with an error. If a hot-reload fails due to a malformed file, retain the previous valid mapping, log at ERROR level, and retry on the next reload cycle.

If a detected token symbol or coin name is not present in the mapping dictionary, log a warning and skip signal generation for that mention.

Example mapping:

Bitcoin → BTC  
Ethereum → ETH  
Solana → SOL  
Chainlink → LINK

If multiple coins are mentioned, signals must be generated for each coin.

When multiple coins and multiple events are detected in one article, generate one signal per coin using all detected events combined. Each coin signal receives the same total event_score and keyword_strength. See Section 10 for the complete scoring algorithm including event_score capping, keyword_strength sign logic, and signal label determination.

Worked example: Article mentions BTC and ETH. Three events detected: partnership_announcement (4), exchange_listing (5), hack (-5).

Net event_score = 4 + 5 + (-5) = 4. Net is positive, so event_score = min(4, 5) = 4.  
keyword_strength = 3 distinct event types detected.  
sentiment_score = 0.61 (bullish article).

For both BTC and ETH:  
signal_score = (0.61 * 3) + (4 * 0.5) + (3 * 0.2) = 1.83 + 2.0 + 0.6 = 4.43  
confidence = min(1.0, 4.43 / 10) = 0.44  
score 4.43 falls in 2 <= score < 5 → signal = "bullish"  
reason = "exchange_listing, partnership_announcement, hack"

If no coins are detected in an article, discard the article and log at DEBUG level.

If coins are detected but no event types are detected, still generate a signal using sentiment_score only (event_score = 0, keyword_strength = 0). If coins are detected but no events are detected and the sentiment-only signal_score falls outside the neutral range (-2 < score < 2), store the signal normally with event_score=0 and keyword_strength=0.

Example output:

{
"coins_detected": ["SOL"]
}

---

# 8. Sentiment Analysis

Sentiment must be calculated using the VADER sentiment analyzer.

VADER compound score mapping:

compound >= 0.05 → bullish  
compound <= -0.05 → bearish  
otherwise → neutral

If sentiment analysis or NLP processing fails for an article (e.g., unsupported language, model loading error), skip the article, log the error at WARNING level with the article_url, and continue processing.

Output values:

- sentiment_label
- sentiment_score

Sentiment labels:

bullish  
neutral  
bearish

Example output:

{
"sentiment_label": "bullish",
"sentiment_score": 0.61
}

---

# 9. Event Detection

The system must detect specific market events using keyword analysis.

## 9.1 Bullish Events

Each bullish event type has a defined score:

exchange_listing: 5  
partnership_announcement: 4  
etf_approval: 5  
mainnet_launch: 4  
token_burn: 3  
integration: 3  
institutional_adoption: 4

Example detected keywords:

"Binance listing"  
"partnership with"  
"mainnet launch"

Example event output:

{
"event_type": "exchange_listing",
"event_score": 5
}

## 9.2 Bearish Events

Each bearish event type has a defined score:

exchange_delisting: -4  
security_exploit: -5  
hack: -5  
regulatory_ban: -4  
lawsuit: -3  
project_shutdown: -5

Example:

{
"event_type": "security_exploit",
"event_score": -5
}

Multiple events may exist in a single article.

## 9.3 Keyword Matching Rules

Event types are detected using case-insensitive substring search on the combined article text.

Keyword-to-event-type mapping:

exchange_listing: ["listed on", "listing on", "now available on", "Binance listing", "Coinbase listing", "added to exchange"]  
partnership_announcement: ["partnership with", "partners with", "strategic partnership", "announces partnership"]  
etf_approval: ["ETF approved", "ETF approval", "spot ETF", "SEC approves"]  
mainnet_launch: ["mainnet launch", "mainnet goes live", "launches mainnet", "mainnet upgrade"]  
token_burn: ["token burn", "burns tokens", "deflationary burn", "coin burn"]  
integration: ["integrates with", "integration with", "integrated into", "now supports"]  
institutional_adoption: ["institutional", "hedge fund", "asset manager", "adds to balance sheet"]  
exchange_delisting: ["delisted from", "delisting from", "removed from exchange"]  
security_exploit: ["security exploit", "exploited for", "exploit attack", "vulnerability exploit", "zero-day", "security flaw"]  
hack: ["was hacked", "hack attack", "got hacked", "stolen funds", "data breach", "funds stolen"]  
regulatory_ban: ["crypto banned", "cryptocurrency banned", "trading banned", "regulatory ban", "government bans crypto", "outlawed cryptocurrency"]  
lawsuit: ["lawsuit", "sued", "legal action", "class action", "SEC charges"]  
project_shutdown: ["shut down", "shutting down", "project abandoned", "ceasing operations"]

If multiple keywords for the same event type match, it counts as one event type detection.

A single text passage may match keywords from multiple different event types. Each distinct event type that matches any of its keywords is counted separately.

---

# 10. Signal Scoring

Signals must be calculated using weighted scoring.

keyword_strength is the count of distinct event types (from Section 9) detected in the article, capped at 10. keyword_strength is always stored as a positive integer. At formula application time only: if the net event_score is negative, multiply keyword_strength by -1 so that more matched event types strengthen the bearish signal. If the net event_score is zero, keyword_strength is treated as positive in the formula.

Step-by-step signal calculation algorithm:

1. Detect all event types and their scores from Section 9.
2. Sum all event scores (positive and negative — they may cancel out). If net > 0, clamp to min(net, 5). If net < 0, clamp to max(net, -5). If net == 0, event_score = 0.
3. Count distinct event types detected → keyword_strength (cap at 10).
4. Calculate sentiment_score using VADER compound.
5. Determine keyword_sign: if event_score < 0, keyword_sign = -1. Otherwise keyword_sign = 1.
6. signal_score = (sentiment_score * 3) + (event_score * 0.5) + (keyword_sign * keyword_strength * 0.2)
7. Apply score interpretation thresholds to determine signal label (bullish/bearish/neutral).
8. confidence = min(1.0, abs(signal_score) / 10)
9. reason = comma-separated event types ordered by absolute score descending.

Bearish worked example: Article mentions SOL. One event detected: hack (-5). Sentiment is negative, compound = -0.72.

Net event_score = -5. Negative, already at cap → event_score = -5.  
keyword_strength = 1 (one distinct event type). Net event_score negative → apply as -1 at formula time.  
sentiment_score = -0.72.

signal_score = (-0.72 * 3) + (-5 * 0.5) + (-1 * 0.2) = -2.16 + -2.5 + -0.2 = -4.86  
confidence = min(1.0, 4.86 / 10) = 0.49  
score -4.86 falls in -5 < score <= -2 → signal = "bearish"  
reason = "hack"

The canonical formula is defined in the step-by-step algorithm above (step 6). The score interpretation thresholds below are the sole reference for mapping signal_score to signal labels.

Score interpretation (evaluated in order, first match wins):

score >= 5 → strong bullish → signal output: "strong bullish"  
2 <= score < 5 → moderate bullish → signal output: "bullish"  
-2 < score < 2 → neutral → signal output: "neutral"  
-5 < score <= -2 → moderate bearish → signal output: "bearish"  
score <= -5 → strong bearish → signal output: "strong bearish"

Note: event_score is capped at ±5, so an event_score of exactly -5 combined with negative sentiment can produce a signal_score <= -5 (strong bearish).

The signal field value (bullish, bearish, neutral) in the output must be derived from the score interpretation thresholds above, not from the sentiment_label. Use the direction only (bullish/bearish/neutral), not the strength label.

Example signal:

{
"coin": "SOL",
"signal": "bullish",
"score": 4.73,
"confidence": 0.47,
"reason": "partnership announcement",
"source": "CoinDesk",
"timestamp": "2026-05-10T12:32:00Z"
}

The reason field must contain a comma-separated list of all detected event types, ordered by absolute event_score descending. If only one event is detected, reason contains that event type name.

---

# 11. Signal Storage

Signals must be stored in a persistent store.

Initial implementation:

SQLite database

Table: news_signals

Columns:

id  
coin  
signal  
score  
confidence  
reason  
source  
timestamp  
article_url

Signals must also be available in memory for fast access. Retain the most recent 1000 signals globally (across all coins) in memory, evicting oldest first.

If the database write fails, retain the signal in memory, log the error, and retry on the next processing cycle.

A processing cycle is one complete execution of the pipeline triggered every 5 minutes per Section 13.

If the database is persistently unavailable for more than 3 consecutive processing cycles, log at CRITICAL level. If in-memory signal count exceeds the 1000 limit due to accumulated unwritten signals, prioritize retaining the most recent 1000.

---

# 12. Signal Publishing

The engine must publish signals for consumption by other services.

Supported methods:

1. internal Python API
2. WebSocket message
3. REST endpoint

If WebSocket or REST publishing fails, log the error at WARNING level, retain the signal in the internal store, and retry publishing on the next cycle.

Example REST response:

GET /signals/latest

Response:

[
{
"coin": "SOL",
"signal": "bullish",
"score": 6.4
}
]

---

# 13. Execution Frequency

The engine must poll news sources every 5 minutes.

Processing must be asynchronous and non-blocking.

---

# 14. Logging

The system must log:

news fetch operations  
article processing  
detected coins  
detected events  
generated signals

Log context must include:

article_url  
coin  
source

Example log:

INFO NewsProcessor: bullish signal detected for SOL from CoinDesk

---

# 15. Error Handling

The system must handle:

RSS feed failure  
network timeouts  
malformed articles  
invalid text parsing

Failures must not stop the pipeline.

Errors must be logged and skipped.

---

# 16. Performance Requirements

The engine must support processing at least:

100 articles per minute

Memory usage must remain below:

500MB

---

# 17. Security

The system must:

sanitize input text by stripping HTML tags, removing control characters (U+0000–U+001F except newline and tab), and escaping any content before SQL insertion  
validate RSS sources by checking URLs against a configured allowlist and verifying responses contain valid RSS/Atom XML before parsing  
avoid executing external content

---

# 18. Future Extensions (Optional)

The architecture must allow future addition of:

social media sentiment (Twitter, Reddit)  
volume spike detection  
machine learning models  
whale wallet tracking

These features must not require redesign of the pipeline.

---

# End of Requirements
