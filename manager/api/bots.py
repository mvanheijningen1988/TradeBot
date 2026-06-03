"""Bot management API endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from manager.api.deps import get_current_user

router = APIRouter(prefix="/bots", tags=["bots"])


class CreateBotRequest(BaseModel):
    name: str
    exchange_id: int
    market: str
    strategy: str
    strategy_params: dict = Field(default_factory=dict)
    budget_quote: float
    profit_mode: str = "withdraw"
    profit_skim_pct: float = 0.0


class UpdateBotRequest(BaseModel):
    name: Optional[str] = None
    strategy_params: Optional[dict] = None
    budget_quote: Optional[float] = None
    profit_mode: Optional[str] = None
    profit_skim_pct: Optional[float] = None


class StartBotRequest(BaseModel):
    worker_id: Optional[int] = None


class DeleteBotRequest(BaseModel):
    mode: str = "stop_cancel"


@router.get("")
async def list_bots(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return all bots."""
    return await request.app.state.bot_service.list_bots()


@router.post("", status_code=201)
async def create_bot(
    body: CreateBotRequest,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Create a new bot."""
    svc = request.app.state.bot_service
    return await svc.create_bot(
        name=body.name,
        exchange_id=body.exchange_id,
        market=body.market,
        strategy=body.strategy,
        strategy_params=body.strategy_params,
        budget_quote=body.budget_quote,
        profit_mode=body.profit_mode,
        profit_skim_pct=body.profit_skim_pct,
    )


@router.get("/{bot_id}")
async def get_bot(
    bot_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return a single bot."""
    bot = await request.app.state.bot_service.get_bot(bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found.")
    return bot


@router.put("/{bot_id}")
async def update_bot(
    bot_id: int,
    body: UpdateBotRequest,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Update a bot's configuration."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="Nothing to update.")
    return await request.app.state.bot_service.update_bot(bot_id, **updates)


@router.post("/{bot_id}/start")
async def start_bot(
    bot_id: int,
    body: StartBotRequest,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Start a bot."""
    return await request.app.state.bot_service.start_bot(
        bot_id, worker_id=body.worker_id
    )


@router.post("/{bot_id}/stop")
async def stop_bot(
    bot_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Stop a bot."""
    return await request.app.state.bot_service.stop_bot(bot_id)


@router.delete("/{bot_id}")
async def delete_bot(
    bot_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    body: DeleteBotRequest = DeleteBotRequest(),
):
    """Delete a bot."""
    await request.app.state.bot_service.delete_bot(bot_id, mode=body.mode)
    return {"detail": "Bot deleted."}


@router.get("/{bot_id}/orders")
async def get_bot_orders(
    bot_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    limit: int = 100,
):
    """Return order history for a bot."""
    return await request.app.state.bot_service.get_orders(bot_id, limit)


@router.get("/{bot_id}/open-orders")
async def get_bot_open_orders(
    bot_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return live open orders from the exchange for a bot."""
    return await request.app.state.bot_service.get_open_orders(bot_id)


@router.get("/{bot_id}/trades")
async def get_bot_trades(
    bot_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    limit: int = 100,
):
    """Return trade history for a bot."""
    return await request.app.state.bot_service.get_trades(bot_id, limit)


@router.get("/overview/budget-history")
async def get_overall_budget_history(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    limit: int = 500,
):
    """Return budget trend data aggregated across all bots."""
    return await request.app.state.budget_service.get_all_history(limit)


@router.get("/{bot_id}/budget-history")
async def get_budget_history(
    bot_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    limit: int = 500,
):
    """Return budget trend data for a bot."""
    return await request.app.state.budget_service.get_history(bot_id, limit)
