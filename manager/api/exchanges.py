"""Exchange data API endpoints.

Provides cached market data, fees, balances, and coin icons.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from manager.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/exchanges", tags=["exchanges"])


class CreateExchangeRequest(BaseModel):
    name: str
    api_key: str
    api_secret: str
    rate_limit: int = 1000


class UpdateExchangeRequest(BaseModel):
    api_key: Optional[str] = None
    api_secret: Optional[str] = None
    rate_limit: Optional[int] = None


@router.get("")
async def list_exchanges(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return configured exchanges (without secrets)."""
    return await request.app.state.exchange_repo.list_all()


@router.post("", status_code=201)
async def create_exchange(
    body: CreateExchangeRequest,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Add a new exchange configuration."""
    exchange_id = await request.app.state.exchange_repo.create(
        name=body.name,
        api_key=body.api_key,
        api_secret=body.api_secret,
        rate_limit=body.rate_limit,
    )
    return {"id": exchange_id, "name": body.name}


@router.delete("/{exchange_id}")
async def delete_exchange(
    exchange_id: int,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Remove an exchange configuration."""
    await request.app.state.exchange_repo.delete(exchange_id)
    return {"detail": "Exchange removed."}


@router.put("/{exchange_id}")
async def update_exchange(
    exchange_id: int,
    body: UpdateExchangeRequest,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Update an exchange configuration."""
    repo = request.app.state.exchange_repo
    exchange = await repo.get_by_id(exchange_id)
    if not exchange:
        raise HTTPException(status_code=404, detail="Exchange not found.")
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update.")
    await repo.update(exchange_id, **updates)
    return {"detail": "Exchange updated."}


@router.get("/{exchange_id}/markets")
async def get_markets(
    exchange_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return markets (cached 24h)."""
    cache = request.app.state.cache_service
    cache_key = f"markets:{exchange_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    client = await _get_exchange_client(request, exchange_id)
    markets = await client.get_markets()
    result = [
        {
            "market": m.market,
            "base": m.base,
            "quote": m.quote,
            "status": m.status,
            "min_order_base": m.min_order_base,
            "min_order_quote": m.min_order_quote,
            "quantity_decimals": m.quantity_decimals,
            "tick_size": m.tick_size,
            "order_types": m.order_types,
        }
        for m in markets
    ]
    config = request.app.state.config
    cache.set(cache_key, result, config.cache_markets_ttl)
    await client.disconnect()
    return result


@router.get("/{exchange_id}/fees")
async def get_fees(
    exchange_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return account fees (cached 5min)."""
    cache = request.app.state.cache_service
    cache_key = f"fees:{exchange_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    client = await _get_exchange_client(request, exchange_id)
    fees = await client.get_account_fees()
    result = {"taker": fees.taker, "maker": fees.maker, "volume": fees.volume}
    config = request.app.state.config
    cache.set(cache_key, result, config.cache_fees_ttl)
    await client.disconnect()
    return result


@router.get("/{exchange_id}/balances")
async def get_balances(
    exchange_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return current exchange balances."""
    client = await _get_exchange_client(request, exchange_id)
    balances = await client.get_balance()
    result = [
        {"symbol": b.symbol, "available": b.available, "in_order": b.in_order}
        for b in balances
    ]
    await client.disconnect()
    return result


@router.get("/{exchange_id}/budget-available")
async def get_budget_available(
    exchange_id: int,
    quote: str,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return budget availability for a quote currency on an exchange.

    Returns exchange balance, total allocated to bots, and the
    remaining free amount.  When a wallet exists, wallet limits
    are returned as well.
    """
    client = await _get_exchange_client(request, exchange_id)
    balances = await client.get_balance(symbol=quote.upper())
    await client.disconnect()

    exchange_available = float(balances[0].available) if balances else 0.0
    exchange_in_order = float(balances[0].in_order) if balances else 0.0
    total_on_exchange = exchange_available + exchange_in_order

    budget_service = request.app.state.budget_service
    allocated = float(await budget_service.get_total_allocated(exchange_id))
    free = max(0.0, total_on_exchange - allocated)

    result = {
        "quote": quote.upper(),
        "exchange_total": round(total_on_exchange, 2),
        "allocated": round(allocated, 2),
        "free": round(free, 2),
    }

    # Enrich with wallet info when available.
    wallet_service = request.app.state.wallet_service
    wallet_info = await wallet_service.get_wallet_info(exchange_id)
    if wallet_info and wallet_info["balance"] > 0:
        result["wallet"] = {
            "balance": wallet_info["balance"],
            "allocated": wallet_info["allocated"],
            "unallocated": wallet_info["unallocated"],
        }
        # When wallet is active, free = wallet unallocated
        result["free"] = wallet_info["unallocated"]

    return result


@router.get("/icons")
async def get_coin_icons(request: Request):
    """Return coin icon mappings (public endpoint)."""
    return request.app.state.coin_icon_service.get_all()


async def _get_exchange_client(request: Request, exchange_id: int):
    """Create a temporary exchange client for data queries."""
    exchange = await request.app.state.exchange_repo.get_by_id(exchange_id)
    if not exchange:
        raise HTTPException(status_code=404, detail="Exchange not found.")

    from manager.exchanges.bitvavo.client import BitvavoClient

    client = BitvavoClient(
        api_key=exchange["api_key"],
        api_secret=exchange["api_secret"],
    )
    await client.connect()
    await client.authenticate()
    return client
