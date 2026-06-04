"""News signals API endpoints.

Provides REST access to the Crypto News Signal Engine's generated
signals, including investment recommendations for the dashboard.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from manager.api.deps import get_current_user

router = APIRouter(prefix="/signals", tags=["signals"])


def _get_engine(request: Request):
    """Return the news engine or raise 503 if unavailable."""
    engine = getattr(request.app.state, "news_engine", None)
    if engine is None:
        raise HTTPException(
            status_code=503,
            detail="News signal engine not available.",
        )
    return engine


@router.get("/latest")
async def get_latest_signals(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    limit: int = 50,
):
    """Return the most recent news signals."""
    engine = _get_engine(request)
    return engine.store.get_latest(limit=limit)


@router.get("/recommendations")
async def get_recommendations(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return investment recommendations based on recent signals.

    Returns coins with bullish signals (consider investing) and
    coins with bearish signals (consider removing from wallet).
    """
    engine = _get_engine(request)
    return await engine.store.get_recommendations()


@router.get("/coin/{coin}")
async def get_signals_by_coin(
    coin: str,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    limit: int = 20,
):
    """Return recent signals for a specific coin."""
    engine = _get_engine(request)
    return engine.store.get_by_coin(coin.upper(), limit=limit)


@router.get("/status")
async def get_engine_status(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return news engine status including active sentiment model."""
    engine = _get_engine(request)
    return {
        "running": engine.is_running,
        "finbert_enabled": engine.sentiment_model_name != "vader",
        "sentiment_model": engine.sentiment_model_name,
    }
