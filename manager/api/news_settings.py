"""News engine settings API endpoints.

Provides CRUD for RSS feeds, coin name→symbol mappings, and
include/exclude word filters used by the news sentiment engine.
All changes take effect on the next processing cycle (≤ 5 min).
"""

from typing import Annotated, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from manager.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/news", tags=["news-settings"])


def _get_engine(request: Request):
    """Return the news engine if it is available."""
    return getattr(request.app.state, "news_engine", None)


# ── Request models ────────────────────────────────────────────────


class CreateFeedRequest(BaseModel):
    """Payload for adding a new RSS news feed."""

    name: str
    url: str
    source_type: str = "rss"
    weight: float = 1.0


class UpdateFeedRequest(BaseModel):
    """Payload for updating an existing feed (all fields optional)."""

    name: Optional[str] = None
    enabled: Optional[bool] = None
    source_type: Optional[str] = None
    weight: Optional[float] = None


class CreateCoinMappingRequest(BaseModel):
    """Payload for adding a coin name → symbol mapping."""

    name: str
    symbol: str
    ambiguous: bool = False


class UpdateCoinMappingRequest(BaseModel):
    """Payload for updating a coin mapping entry."""

    name: Optional[str] = None
    symbol: Optional[str] = None
    ambiguous: Optional[bool] = None


class CreateWordFilterRequest(BaseModel):
    """Payload for adding an include or exclude word filter."""

    word: str
    filter_type: str  # 'include' | 'exclude'


# ── Helpers ───────────────────────────────────────────────────────


def _repo(request: Request):
    """Return the NewsSettingsRepository from application state."""
    return request.app.state.news_settings_repo


async def _trigger_reload(request: Request) -> None:
    """Ask the news engine to reload settings immediately, if running."""
    engine = getattr(request.app.state, "news_engine", None)
    if engine is not None:
        await engine.reload_settings()


# ── Feed endpoints ────────────────────────────────────────────────


@router.get("/feeds")
async def list_feeds(
    request: Request,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """Return all configured RSS news feeds."""
    return await _repo(request).list_feeds()


@router.post(
    "/feeds",
    status_code=201,
    responses={409: {"description": "Feed URL already exists."}},
)
async def create_feed(
    body: CreateFeedRequest,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    """Add a new RSS feed (admin only)."""
    repo = _repo(request)
    try:
        feed_id = await repo.create_feed(
            body.name,
            body.url,
            body.source_type,
            body.weight,
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(
                status_code=409, detail="Feed URL already exists."
            )
        raise
    await _trigger_reload(request)
    return {
        "id": feed_id,
        "name": body.name,
        "url": body.url,
        "source_type": body.source_type,
        "weight": body.weight,
    }


@router.patch(
    "/feeds/{feed_id}",
    responses={404: {"description": "Feed not found."}},
)
async def update_feed(
    feed_id: int,
    body: UpdateFeedRequest,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, str]:
    """Update a feed's name or enabled state (admin only)."""
    repo = _repo(request)
    feeds = await repo.list_feeds()
    if not any(f["id"] == feed_id for f in feeds):
        raise HTTPException(status_code=404, detail="Feed not found.")
    updates = body.model_dump(exclude_none=True)
    if updates:
        if "enabled" in updates:
            updates["enabled"] = int(updates["enabled"])
        await repo.update_feed(feed_id, **updates)
    await _trigger_reload(request)
    return {"detail": "Feed updated."}


@router.delete(
    "/feeds/{feed_id}",
    responses={404: {"description": "Feed not found."}},
)
async def delete_feed(
    feed_id: int,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, str]:
    """Delete an RSS feed by id (admin only)."""
    repo = _repo(request)
    feeds = await repo.list_feeds()
    if not any(f["id"] == feed_id for f in feeds):
        raise HTTPException(status_code=404, detail="Feed not found.")
    await repo.delete_feed(feed_id)
    await _trigger_reload(request)
    return {"detail": "Feed deleted."}


# ── Coin mapping endpoints ────────────────────────────────────────


@router.get("/coin-mappings")
async def list_coin_mappings(
    request: Request,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """Return all coin name → symbol mappings."""
    return await _repo(request).list_coin_mappings()


@router.post(
    "/coin-mappings",
    status_code=201,
    responses={409: {"description": "Coin name already exists."}},
)
async def create_coin_mapping(
    body: CreateCoinMappingRequest,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    """Add a coin mapping (admin only)."""
    repo = _repo(request)
    try:
        mapping_id = await repo.create_coin_mapping(
            body.name, body.symbol, body.ambiguous
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(
                status_code=409,
                detail="A mapping for this coin name already exists.",
            )
        raise
    await _trigger_reload(request)
    return {
        "id": mapping_id,
        "name": body.name,
        "symbol": body.symbol,
        "ambiguous": body.ambiguous,
    }


@router.patch(
    "/coin-mappings/{mapping_id}",
    responses={404: {"description": "Mapping not found."}},
)
async def update_coin_mapping(
    mapping_id: int,
    body: UpdateCoinMappingRequest,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, str]:
    """Update a coin mapping entry (admin only)."""
    repo = _repo(request)
    mappings = await repo.list_coin_mappings()
    if not any(m["id"] == mapping_id for m in mappings):
        raise HTTPException(status_code=404, detail="Mapping not found.")
    updates = body.model_dump(exclude_none=True)
    if updates:
        await repo.update_coin_mapping(mapping_id, **updates)
    await _trigger_reload(request)
    return {"detail": "Coin mapping updated."}


@router.delete(
    "/coin-mappings/{mapping_id}",
    responses={404: {"description": "Mapping not found."}},
)
async def delete_coin_mapping(
    mapping_id: int,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, str]:
    """Delete a coin mapping by id (admin only)."""
    repo = _repo(request)
    mappings = await repo.list_coin_mappings()
    if not any(m["id"] == mapping_id for m in mappings):
        raise HTTPException(status_code=404, detail="Mapping not found.")
    await repo.delete_coin_mapping(mapping_id)
    await _trigger_reload(request)
    return {"detail": "Coin mapping deleted."}


# ── Word filter endpoints ─────────────────────────────────────────


@router.get("/word-filters")
async def list_word_filters(
    request: Request,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> list[dict[str, Any]]:
    """Return all include/exclude word filters."""
    return await _repo(request).list_word_filters()


@router.post(
    "/word-filters",
    status_code=201,
    responses={
        400: {"description": "Invalid filter_type."},
        409: {"description": "Word already exists in filters."},
    },
)
async def create_word_filter(
    body: CreateWordFilterRequest,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    """Add a word to the include or exclude filter list (admin only)."""
    if body.filter_type not in ("include", "exclude"):
        raise HTTPException(
            status_code=400,
            detail="filter_type must be 'include' or 'exclude'.",
        )
    repo = _repo(request)
    try:
        filter_id = await repo.create_word_filter(
            body.word, body.filter_type
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(
                status_code=409,
                detail="This word already exists in the filter list.",
            )
        raise
    await _trigger_reload(request)
    return {
        "id": filter_id,
        "word": body.word.lower(),
        "filter_type": body.filter_type,
    }


@router.delete(
    "/word-filters/{filter_id}",
    responses={404: {"description": "Word filter not found."}},
)
async def delete_word_filter(
    filter_id: int,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, str]:
    """Remove a word filter by id (admin only)."""
    repo = _repo(request)
    filters = await repo.list_word_filters()
    if not any(f["id"] == filter_id for f in filters):
        raise HTTPException(
            status_code=404, detail="Word filter not found."
        )
    await repo.delete_word_filter(filter_id)
    await _trigger_reload(request)
    return {"detail": "Word filter deleted."}


# ── Engine parameter endpoints ────────────────────────────────────

_PARAM_MIN_CONFIDENCE = "min_confidence"
_DEFAULT_MIN_CONFIDENCE = 0.0


class UpdateParamsRequest(BaseModel):
    """Payload for updating news engine parameters."""

    min_confidence: Optional[float] = None
    poll_interval_minutes: Optional[float] = None
    finbert_enabled: Optional[bool] = None


@router.get("/params")
async def get_params(
    request: Request,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, float]:
    """Return current news engine parameters."""
    repo = _repo(request)
    raw = await repo.get_param(
        _PARAM_MIN_CONFIDENCE,
        str(_DEFAULT_MIN_CONFIDENCE),
    )
    poll_raw = await repo.get_param("poll_interval_minutes", "5")
    engine = _get_engine(request)
    finbert_default = (
        "1"
        if (engine is not None and engine.sentiment_model_name != "vader")
        else "0"
    )
    finbert_raw = await repo.get_param("finbert_enabled", finbert_default)
    finbert_enabled = str(finbert_raw).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return {
        "min_confidence": float(raw),
        "poll_interval_minutes": float(poll_raw),
        "finbert_enabled": finbert_enabled,
    }


@router.put(
    "/params",
    responses={
        400: {
            "description": (
                "min_confidence must be between 0.0 and 1.0."
            )
        }
    },
)
async def update_params(
    body: UpdateParamsRequest,
    request: Request,
    _user: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    """Update news engine parameters (admin only)."""
    if (
        body.min_confidence is not None
        and not 0.0 <= body.min_confidence <= 1.0
    ):
        raise HTTPException(
            status_code=400,
            detail="min_confidence must be between 0.0 and 1.0.",
        )
    if (
        body.poll_interval_minutes is not None
        and body.poll_interval_minutes < 1
    ):
        raise HTTPException(
            status_code=400,
            detail="poll_interval_minutes must be at least 1 minute.",
        )
    repo = _repo(request)
    if body.min_confidence is not None:
        await repo.set_param(
            _PARAM_MIN_CONFIDENCE, str(body.min_confidence)
        )
    if body.poll_interval_minutes is not None:
        await repo.set_param(
            "poll_interval_minutes",
            str(body.poll_interval_minutes),
        )
    if body.finbert_enabled is not None:
        await repo.set_param(
            "finbert_enabled",
            "1" if body.finbert_enabled else "0",
        )
    await _trigger_reload(request)
    engine = getattr(request.app.state, "news_engine", None)
    refresh_started = False
    if engine is not None:
        refresh_started = engine.trigger_refresh_cycle()
    return {
        "min_confidence": body.min_confidence,
        "poll_interval_minutes": body.poll_interval_minutes,
        "finbert_enabled": body.finbert_enabled,
        "refresh_started": refresh_started,
    }


@router.get(
    "/articles",
    responses={503: {"description": "News engine not available."}},
)
async def list_articles(
    request: Request,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return recent crypto news articles for the feed page."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="News engine not available.",
        )
    return await engine.store.get_latest_articles(limit=limit)


@router.get(
    "/overview",
    responses={503: {"description": "News engine not available."}},
)
async def get_overview(
    request: Request,
    _user: Annotated[dict[str, Any], Depends(get_current_user)],
    limit: int = 100,
) -> dict[str, Any]:
    """Return the weighted crypto sentiment overview."""
    engine = _get_engine(request)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="News engine not available.",
        )
    return await engine.store.get_news_overview(limit=limit)
