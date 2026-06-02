"""Manager Node FastAPI application.

Entry point for the TradeBot Manager.  Wires up all services, registers
API routes, and manages startup / shutdown lifecycle.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from manager.api import api_router, ws_api_router
from manager.api.ws import manager as ws_manager
from manager.config import load_config
from manager.database.connection import Database
from manager.database.repositories import (
    BotRepository,
    BudgetHistoryRepository,
    ExchangeRepository,
    LogEntryRepository,
    OrderHistoryRepository,
    TradeHistoryRepository,
    UserRepository,
    WorkerRepository,
)
from manager.services.auth_service import AuthService
from manager.services.bot_service import BotService
from manager.services.budget_service import BudgetService
from manager.services.cache_service import CacheService
from manager.services.coin_icons import CoinIconService
from manager.services.log_service import LogService
from manager.services.worker_service import WorkerService

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage startup and shutdown of the application."""
    config = app.state.config

    # Database.
    db = Database(config.db_path)
    await db.connect()
    app.state.db = db

    # Repositories.
    user_repo = UserRepository(db)
    exchange_repo = ExchangeRepository(db)
    worker_repo = WorkerRepository(db)
    bot_repo = BotRepository(db)
    order_repo = OrderHistoryRepository(db)
    trade_repo = TradeHistoryRepository(db)
    budget_repo = BudgetHistoryRepository(db)
    log_repo = LogEntryRepository(db)

    app.state.user_repo = user_repo
    app.state.exchange_repo = exchange_repo

    # Services.
    log_service = LogService(config, log_repo)
    log_service.setup_logging()
    app.state.log_service = log_service

    auth_service = AuthService(config, user_repo)
    await auth_service.ensure_admin_exists()
    app.state.auth_service = auth_service

    cache_service = CacheService()
    app.state.cache_service = cache_service

    budget_service = BudgetService(bot_repo, budget_repo)
    app.state.budget_service = budget_service

    worker_service = WorkerService(config, worker_repo, bot_repo)
    worker_service.set_broadcast_callback(ws_manager.broadcast_ui)
    await worker_service.start_health_monitor()
    app.state.worker_service = worker_service

    bot_service = BotService(
        bot_repo, order_repo, trade_repo, worker_service
    )
    app.state.bot_service = bot_service

    coin_icon_service = CoinIconService()
    await coin_icon_service.load()
    app.state.coin_icon_service = coin_icon_service

    logger.info(
        "TradeBot Manager started on %s:%d", config.host, config.port
    )

    yield

    # Shutdown.
    if hasattr(app.state, "worker_service"):
        await app.state.worker_service.stop_health_monitor()
    if hasattr(app.state, "db"):
        await app.state.db.close()
    logger.info("TradeBot Manager shut down.")


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    config = load_config()

    app = FastAPI(
        title="TradeBot Manager",
        version="0.2.0",
        lifespan=lifespan,
    )

    # CORS – allow Angular dev server.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Store config for access in lifespan.
    app.state.config = config

    # Register routes.
    app.include_router(api_router)
    app.include_router(ws_api_router)

    return app


def main() -> None:
    """Run the application via uvicorn."""
    config = load_config()
    app = create_app()
    uvicorn.run(app, host=config.host, port=config.port)


if __name__ == "__main__":
    main()
