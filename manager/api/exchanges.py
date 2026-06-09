"""Exchange data API endpoints.

Provides cached market data, fees, balances, and coin icons.
"""

import logging
from decimal import Decimal, InvalidOperation

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from manager.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/exchanges", tags=["exchanges"])
logger = logging.getLogger(__name__)


async def _persist_exchange_error(request: Request, message: str) -> None:
    """Persist exchange API errors to DB-backed diagnostics logs."""
    log_service = getattr(request.app.state, "log_service", None)
    if not log_service:
        return
    try:
        await log_service.persist(
            category="manager",
            subcategory="api.exchanges",
            level="ERROR",
            message=message,
        )
    except Exception:
        logger.debug("Failed to persist exchange error log entry.")


class CreateExchangeRequest(BaseModel):
    """Payload for storing a new exchange credential configuration."""

    name: str
    api_key: str
    api_secret: str
    rate_limit: int = 1000


class UpdateExchangeRequest(BaseModel):
    """Payload for partial updates to an existing exchange config."""

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


@router.put(
    "/{exchange_id}",
    responses={
        404: {"description": "Exchange not found."},
        400: {"description": "No updatable fields provided."},
    },
)
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


@router.get(
    "/{exchange_id}/markets",
    responses={
        404: {"description": "Exchange not found."},
        502: {"description": "Exchange API unreachable."},
    },
)
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


@router.get(
    "/{exchange_id}/fees",
    responses={
        404: {"description": "Exchange not found."},
        502: {"description": "Exchange API unreachable."},
    },
)
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


@router.get(
    "/{exchange_id}/balances",
    responses={
        502: {
            "description": (
                "Exchange balance fetch failed due to upstream "
                "API/auth issue."
            )
        }
    },
)
async def get_balances(
    exchange_id: int,
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return current exchange balances."""
    client = await _get_exchange_client(request, exchange_id)
    try:
        balances = await client.get_balance()
        bot_repo = request.app.state.bot_service._bot_repo
        exchange_bots = await _get_active_exchange_bots(bot_repo, exchange_id)
        manager_allocated_by_symbol, operator_ids = _build_manager_allocation(
            exchange_bots
        )
        bot_ids = [int(b["id"]) for b in exchange_bots if b.get("id")]
        bot_order_ids = (
            await request.app.state.order_repo
            .list_exchange_order_ids_by_bots(bot_ids)
        )
        manager_in_order_by_symbol = await _build_manager_in_order(
            client,
            operator_ids,
            bot_order_ids,
        )
        return _serialize_balances(
            balances,
            manager_allocated_by_symbol,
            manager_in_order_by_symbol,
        )
    except Exception as exc:
        await _persist_exchange_error(
            request,
            (
                f"Exchange {exchange_id} balance fetch failed: {exc}. "
                "Verify API credentials and permissions."
            ),
        )
        logger.warning(
            "Failed to load balances for exchange %d: %s",
            exchange_id,
            exc,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to load exchange balances. Verify exchange API "
                "credentials and permissions."
            ),
        ) from exc
    finally:
        await client.disconnect()


@router.get(
    "/{exchange_id}/budget-available",
    responses={
        404: {"description": "Exchange not found."},
        502: {"description": "Exchange API unreachable."},
    },
)
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
        raise HTTPException(  # NOSONAR
            status_code=404, detail="Exchange not found."
        )

    from manager.exchanges.bitvavo.client import BitvavoClient

    client = BitvavoClient(
        api_key=exchange["api_key"],
        api_secret=exchange["api_secret"],
    )
    try:
        await client.connect()
        await client.authenticate()
    except Exception as exc:
        await _persist_exchange_error(
            request,
            (
                f"Exchange {exchange_id} client init failed: {exc}. "
                "Connect/authenticate could not complete."
            ),
        )
        logger.exception(
            "Failed to initialize exchange client for exchange %d.",
            exchange_id,
        )
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to connect/authenticate exchange API. "
                "Check API key, secret, and exchange permissions."
            ),
        ) from exc
    return client


def _to_decimal(value: object) -> Decimal:
    """Safely convert raw numeric payload values to Decimal."""
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


async def _get_active_exchange_bots(
    bot_repo,
    exchange_id: int,
) -> list[dict]:
    """Return non-stopped bots for one exchange."""
    bots = await bot_repo.list_all()
    return [
        b for b in bots
        if b.get("exchange_id") == exchange_id
        and b.get("status") != "stopped"
    ]


def _build_manager_allocation(
    exchange_bots: list[dict],
) -> tuple[dict[str, Decimal], set[int]]:
    """Aggregate manager-allocated quote budget and operator ids."""
    allocated: dict[str, Decimal] = {}
    operator_ids: set[int] = set()

    for bot in exchange_bots:
        market = str(bot.get("market", ""))
        if "-" not in market:
            continue
        _base, quote = market.split("-", 1)
        quote_symbol = quote.upper()
        budget_quote = _to_decimal(bot.get("budget_quote", "0"))
        allocated[quote_symbol] = (
            allocated.get(quote_symbol, Decimal("0")) + budget_quote
        )

        operator_id = bot.get("operator_id")
        if operator_id is not None:
            operator_ids.add(int(operator_id))

    return allocated, operator_ids


async def _build_manager_in_order(
    client,
    operator_ids: set[int],
    bot_order_ids: set[str],
) -> dict[str, Decimal]:
    """Aggregate in-order amounts for bot-owned open orders by asset."""
    in_order: dict[str, Decimal] = {}
    if not operator_ids:
        return in_order

    open_orders = await client.get_open_orders()
    for order in open_orders:
        operator_id = _normalize_operator_id(order.operator_id)
        if operator_id not in operator_ids:
            continue
        if bot_order_ids and order.order_id not in bot_order_ids:
            continue

        market = str(order.market or "")
        if "-" not in market:
            continue
        base_symbol, quote_symbol = market.split("-", 1)
        base_symbol = base_symbol.upper()
        quote_symbol = quote_symbol.upper()

        side_val = (
            order.side.value
            if hasattr(order.side, "value")
            else str(order.side)
        )
        amount = _to_decimal(order.amount_remaining or order.amount or "0")

        if side_val == "buy":
            locked_quote = _estimate_locked_quote(order, amount, quote_symbol)
            _add_amount(in_order, quote_symbol, locked_quote)
            continue

        _add_amount(in_order, base_symbol, amount)

    return in_order


def _estimate_locked_quote(
    order,
    amount: Decimal,
    quote_symbol: str,
) -> Decimal:
    """Estimate quote value currently locked by a BUY order."""
    on_hold = _to_decimal(order.on_hold or "0")
    on_hold_currency = str(order.on_hold_currency or "").upper()
    if on_hold > 0 and on_hold_currency == quote_symbol:
        return on_hold

    amount_quote = _to_decimal(
        order.amount_quote_remaining or order.amount_quote or "0"
    )
    if amount_quote > 0:
        return amount_quote

    price = _to_decimal(order.price or "0")
    if amount > 0 and price > 0:
        return amount * price
    return Decimal("0")


def _normalize_operator_id(value: object) -> Optional[int]:
    """Normalize operator id values from exchange payload to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _add_amount(
    store: dict[str, Decimal],
    symbol: str,
    amount: Decimal,
) -> None:
    """Accumulate positive Decimal amounts by symbol."""
    if amount <= 0:
        return
    store[symbol] = store.get(symbol, Decimal("0")) + amount


def _serialize_balances(
    balances,
    manager_allocated_by_symbol: dict[str, Decimal],
    manager_in_order_by_symbol: dict[str, Decimal],
) -> list[dict[str, str]]:
    """Serialize exchange balances with manager-side enrichment."""
    payload: list[dict[str, str]] = []
    for bal in balances:
        symbol = bal.symbol.upper()
        payload.append(
            {
                "symbol": bal.symbol,
                "available": bal.available,
                "in_order": bal.in_order,
                "manager_allocated": str(
                    manager_allocated_by_symbol.get(symbol, Decimal("0"))
                ),
                "manager_in_order": str(
                    manager_in_order_by_symbol.get(symbol, Decimal("0"))
                ),
            }
        )
    return payload
