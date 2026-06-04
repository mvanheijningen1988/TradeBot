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
    NewsSettingsRepository,
    OrderHistoryRepository,
    TradeHistoryRepository,
    UserRepository,
    WalletRepository,
    WorkerRepository,
)
from manager.services.auth_service import AuthService
from manager.services.bot_service import BotService
from manager.services.budget_service import BudgetService
from manager.services.cache_service import CacheService
from manager.services.coin_icons import CoinIconService
from manager.services.log_service import LogService
from manager.services.wallet_service import WalletService
from manager.services.worker_service import WorkerService

logger = logging.getLogger(__name__)

try:
    from services.news_engine.main import NewsEngineService
except ImportError:
    NewsEngineService = None
    logger.warning("News engine not available – services package not found")


async def _seed_news_defaults(repo) -> None:
    """Seed RSS feeds and coin mappings into DB if tables are empty."""
    import json
    import os

    if await repo.count_feeds() == 0:
        try:
            from services.news_engine.config.news_sources import (
                DEFAULT_SOURCES,
            )
            for src in DEFAULT_SOURCES:
                await repo.create_feed(src.name, src.url)
            logger.info(
                "Seeded %d default RSS feeds.", len(DEFAULT_SOURCES)
            )
        except Exception:
            logger.exception("Failed to seed default RSS feeds.")

    if await repo.count_coin_mappings() == 0:
        try:
            mapping_path = os.path.join(
                os.path.dirname(__file__),
                "..",
                "services",
                "news_engine",
                "config",
                "coin_mapping.json",
            )
            mapping_path = os.path.normpath(mapping_path)
            with open(mapping_path, encoding="utf-8") as fh:
                data = json.load(fh)
            ambiguous = set(data.get("ambiguous_symbols", []))
            for name, symbol in data.get("coins", {}).items():
                await repo.create_coin_mapping(
                    name, symbol, symbol in ambiguous
                )
            logger.info(
                "Seeded %d default coin mappings.",
                len(data.get("coins", {})),
            )
        except Exception:
            logger.exception("Failed to seed default coin mappings.")


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
    wallet_repo = WalletRepository(db)

    app.state.user_repo = user_repo
    app.state.exchange_repo = exchange_repo
    app.state.order_repo = order_repo

    news_settings_repo = NewsSettingsRepository(db)
    app.state.news_settings_repo = news_settings_repo
    await _seed_news_defaults(news_settings_repo)

    # Services.
    log_service = LogService(config, log_repo)
    log_service.setup_logging()
    log_service.attach_diagnostics_stream_handler()
    app.state.log_service = log_service

    auth_service = AuthService(config, user_repo)
    await auth_service.ensure_admin_exists()
    app.state.auth_service = auth_service

    cache_service = CacheService()
    app.state.cache_service = cache_service

    budget_service = BudgetService(bot_repo, budget_repo)
    app.state.budget_service = budget_service

    wallet_service = WalletService(wallet_repo)
    app.state.wallet_service = wallet_service

    budget_service.set_wallet_service(wallet_service)

    worker_service = WorkerService(config, worker_repo, bot_repo, log_service)
    worker_service.set_broadcast_callback(ws_manager.broadcast_ui)
    worker_service.start_health_monitor()
    app.state.worker_service = worker_service

    bot_service = BotService(
        bot_repo, order_repo, trade_repo, worker_service, exchange_repo
    )
    app.state.bot_service = bot_service

    coin_icon_service = CoinIconService()
    await coin_icon_service.load()
    app.state.coin_icon_service = coin_icon_service

    # News Signal Engine.
    if NewsEngineService is not None:
        news_engine = NewsEngineService(
            db=db, news_settings_repo=news_settings_repo
        )
        await news_engine.start()
        app.state.news_engine = news_engine

    # Wallet exchange verification.
    async def _make_exchange_client(eid: int):
        from manager.exchanges.bitvavo.client import BitvavoClient

        ex = await exchange_repo.get_by_id(eid)
        if not ex:
            raise ValueError(f"Exchange {eid} not found")
        client = BitvavoClient(
            api_key=ex["api_key"], api_secret=ex["api_secret"]
        )
        await client.connect()
        await client.authenticate()
        return client

    wallet_service.set_exchange_client_factory(_make_exchange_client)
    await wallet_service.start_verification_loop(exchange_repo)

    logger.info(
        "TradeBot Manager started on %s:%d", config.host, config.port
    )

    yield

    # Shutdown.
    if hasattr(app.state, "wallet_service"):
        await app.state.wallet_service.stop_verification_loop()
    if hasattr(app.state, "news_engine"):
        await app.state.news_engine.stop()
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
