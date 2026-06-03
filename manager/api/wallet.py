"""Wallet management API endpoints.

Provides virtual deposit/withdraw operations and balance queries
for the manager's per-exchange wallets.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from manager.api.deps import get_current_user

router = APIRouter(prefix="/wallet", tags=["wallet"])


class WalletAmountRequest(BaseModel):
    """Request body for deposit/withdraw."""

    amount: float = Field(gt=0)
    quote_currency: str = "EUR"


@router.get("/{exchange_id}")
async def get_wallet(
    exchange_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return wallet info for an exchange."""
    svc = request.app.state.wallet_service
    info = await svc.get_wallet_info(exchange_id)
    if not info:
        # Auto-create on first access
        await svc.get_or_create(exchange_id)
        info = await svc.get_wallet_info(exchange_id)
    return info


@router.post("/{exchange_id}/deposit")
async def deposit(
    exchange_id: int,
    body: WalletAmountRequest,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Virtually deposit funds into the wallet."""
    svc = request.app.state.wallet_service
    try:
        return await svc.deposit(
            exchange_id, body.amount, body.quote_currency
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{exchange_id}/withdraw")
async def withdraw(
    exchange_id: int,
    body: WalletAmountRequest,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Virtually withdraw funds from the wallet."""
    svc = request.app.state.wallet_service
    try:
        return await svc.withdraw(exchange_id, body.amount)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{exchange_id}/transactions")
async def get_transactions(
    exchange_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    limit: int = 100,
):
    """Return wallet transaction history."""
    svc = request.app.state.wallet_service
    wallet = await svc._repo.get_by_exchange(exchange_id)
    if not wallet:
        return []
    return await svc._repo.get_transactions(wallet["id"], limit)


@router.get("/{exchange_id}/verify")
async def verify_wallet(
    exchange_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Verify wallet balance against exchange."""
    svc = request.app.state.wallet_service
    result = await svc.verify_against_exchange(exchange_id)
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Verification unavailable.",
        )
    return result
