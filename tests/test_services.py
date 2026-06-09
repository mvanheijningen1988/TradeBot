"""Tests for the manager services and API layer."""

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

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
    WorkerRepository,
)
from manager.services.auth_service import AuthService
from manager.services.bot_service import BotService
from manager.services.budget_service import BudgetService
from manager.services.cache_service import CacheService
from manager.services.log_service import LogService
from manager.services.worker_service import WorkerService
from manager.api.ws import _handle_budget_snapshot
from manager.models import Order, OrderFill, OrderSide, OrderStatus, OrderType
from services.news_engine.signals.signal_models import (
    NewsArticle,
    SentimentLabel,
)
from services.news_engine.signals.signal_store import SignalStore


@pytest.fixture
async def db():
    """Create a temporary in-memory database for testing."""
    database = Database(":memory:")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def config():
    """Provide a config object with deterministic JWT secret for tests."""
    jwt_secret = "test-secret-key-12345678901234567890abcd"
    os.environ["TRADEBOT_JWT_SECRET"] = jwt_secret
    cfg = load_config()
    os.environ.pop("TRADEBOT_JWT_SECRET", None)
    return cfg


@pytest.fixture
async def repos(db):
    """Build repository instances backed by the test database."""
    return {
        "user": UserRepository(db),
        "exchange": ExchangeRepository(db),
        "worker": WorkerRepository(db),
        "bot": BotRepository(db),
        "news": NewsSettingsRepository(db),
        "order": OrderHistoryRepository(db),
        "trade": TradeHistoryRepository(db),
        "budget": BudgetHistoryRepository(db),
        "log": LogEntryRepository(db),
    }


# ── Auth service tests ───────────────────────────────────────────


class TestAuthService:
    """Tests for authentication setup, credential checks, and tokens."""

    async def test_ensure_admin_exists(self, config, repos):
        """Ensure startup creates a single default admin account."""
        auth = AuthService(config, repos["user"])
        await auth.ensure_admin_exists()

        users = await repos["user"].list_all()
        assert len(users) == 1
        assert users[0]["username"] == "admin"
        assert users[0]["role"] == "admin"

    async def test_ensure_admin_idempotent(self, config, repos):
        """Ensure repeated admin initialization does not duplicate users."""
        auth = AuthService(config, repos["user"])
        await auth.ensure_admin_exists()
        await auth.ensure_admin_exists()

        users = await repos["user"].list_all()
        assert len(users) == 1

    async def test_authenticate_valid(self, config, repos):
        """Authenticate successfully when username and password are valid."""
        from passlib.hash import bcrypt

        hashed = bcrypt.hash("password123")
        await repos["user"].create("testuser", hashed, "user")

        auth = AuthService(config, repos["user"])
        user = await auth.authenticate("testuser", "password123")
        assert user is not None
        assert user["username"] == "testuser"

    async def test_authenticate_invalid(self, config, repos):
        """Return no user when password validation fails."""
        from passlib.hash import bcrypt

        hashed = bcrypt.hash("password123")
        await repos["user"].create("testuser", hashed, "user")

        auth = AuthService(config, repos["user"])
        user = await auth.authenticate("testuser", "wrongpassword")
        assert user is None

    def test_token_roundtrip(self, config, repos):
        """Create and verify a token to validate payload roundtrip."""
        auth = AuthService(config, repos["user"])
        token = auth.create_access_token(1, "admin")
        payload = auth.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["role"] == "admin"

    def test_verify_invalid_token(self, config, repos):
        """Return None when token verification receives invalid input."""
        auth = AuthService(config, repos["user"])
        result = auth.verify_token("invalid.token.value")
        assert result is None


# ── Cache service tests ──────────────────────────────────────────


class TestCacheService:
    """Tests for the in-memory cache service behavior."""

    def test_set_and_get(self):
        """Store and retrieve a cached value by key."""
        cache = CacheService()
        cache.set("key1", "value1", 60)
        assert cache.get("key1") == "value1"

    def test_get_missing(self):
        """Return None when the requested cache key does not exist."""
        cache = CacheService()
        assert cache.get("nonexistent") is None

    def test_invalidate(self):
        """Invalidate a key and confirm it is no longer retrievable."""
        cache = CacheService()
        cache.set("key1", "value1", 60)
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_clear(self):
        """Clear cache and verify all existing keys are removed."""
        cache = CacheService()
        cache.set("a", 1, 60)
        cache.set("b", 2, 60)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None


# ── Bot service tests ────────────────────────────────────────────


class TestBotService:
    """Tests for bot lifecycle behavior in the bot service."""

    async def test_create_bot(self, config, repos):
        """Create a bot and verify persisted defaults and identifiers."""
        # Need an exchange first.
        exchange_id = await repos["exchange"].create(
            "bitvavo", "key", "secret"
        )

        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )

        bot = await bot_svc.create_bot(
            name="Test Bot",
            exchange_id=exchange_id,
            market="BTC-EUR",
            strategy="grid_trading",
            strategy_params={"upper_price": 50000, "lower_price": 40000},
            budget_quote=100.0,
        )
        assert bot["name"] == "Test Bot"
        assert bot["status"] == "stopped"
        assert bot["market"] == "BTC-EUR"
        assert bot["operator_id"] == 1

    async def test_create_bot_invalid_profit_mode(self, config, repos):
        """Reject bot creation when profit mode value is unsupported."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )

        with pytest.raises(ValueError, match="Invalid profit_mode"):
            await bot_svc.create_bot(
                name="Bad",
                exchange_id=exchange_id,
                market="BTC-EUR",
                strategy="grid_trading",
                strategy_params={},
                budget_quote=100.0,
                profit_mode="invalid",
            )

    async def test_stop_bot(self, config, repos):
        """Stop an existing bot and verify status transitions to stopped."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )

        bot = await bot_svc.create_bot(
            name="Bot1", exchange_id=exchange_id, market="ETH-EUR",
            strategy="dca", strategy_params={}, budget_quote=50.0,
        )
        stopped = await bot_svc.stop_bot(bot["id"])
        assert stopped["status"] == "stopped"

    async def test_list_bots(self, config, repos):
        """List all bots and validate expected count is returned."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )

        await bot_svc.create_bot(
            name="A", exchange_id=exchange_id, market="BTC-EUR",
            strategy="grid_trading", strategy_params={}, budget_quote=10,
        )
        await bot_svc.create_bot(
            name="B", exchange_id=exchange_id, market="ETH-EUR",
            strategy="dca", strategy_params={}, budget_quote=20,
        )

        bots = await bot_svc.list_bots()
        assert len(bots) == 2

    async def test_cancel_exchange_orders_only_for_exact_operator_id(
        self, config, repos, monkeypatch
    ):
        """Never cancel untagged/manual orders during bot cleanup."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="Scoped",
            exchange_id=exchange_id,
            market="BTC-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        open_orders = [
            Order(
                order_id="owned",
                market="BTC-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=bot["operator_id"],
            ),
            Order(
                order_id="manual",
                market="BTC-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=None,
            ),
            Order(
                order_id="other-bot",
                market="BTC-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=bot["operator_id"] + 1,
            ),
        ]

        cancelled: list[str] = []

        def _cancel_order(market, order_id, operator_id, **_kwargs):
            cancelled.append(order_id)
            return {"orderId": order_id, "market": market}

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_open_orders",
            AsyncMock(return_value=open_orders),
        )
        monkeypatch.setattr(
            BitvavoClient,
            "cancel_order",
            AsyncMock(side_effect=_cancel_order),
        )

        await bot_svc._cancel_exchange_orders(bot, bot["id"])
        assert cancelled == ["owned"]

    async def test_delete_bot_only_cancels_matching_operator_orders(
        self, config, repos, monkeypatch
    ):
        """Delete cleanup should not remove manual or foreign orders."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="DeleteScoped",
            exchange_id=exchange_id,
            market="BTC-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        open_orders = [
            Order(
                order_id="owned",
                market="BTC-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=bot["operator_id"],
            ),
            Order(
                order_id="manual",
                market="BTC-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=None,
                client_order_id=f"{bot['uuid']}:grid:2",
            ),
            Order(
                order_id="other-bot",
                market="BTC-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=bot["operator_id"] + 1,
            ),
        ]

        cancelled: list[str] = []

        def _cancel_order(market, order_id, operator_id, **_kwargs):
            cancelled.append(order_id)
            return {"orderId": order_id, "market": market}

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_open_orders",
            AsyncMock(return_value=open_orders),
        )
        monkeypatch.setattr(
            BitvavoClient,
            "cancel_order",
            AsyncMock(side_effect=_cancel_order),
        )

        await bot_svc.delete_bot(bot["id"])

        assert cancelled == ["owned"]

    async def test_get_open_orders_excludes_non_bot_order_ids(
        self, config, repos, monkeypatch
    ):
        """Return only exchange open orders for the bot reference."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="GridOwnedOnly",
            exchange_id=exchange_id,
            market="XRP-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        await repos["order"].create(
            bot_id=bot["id"],
            exchange_order_id="bot-order-1",
            market="XRP-EUR",
            side="sell",
            order_type="limit",
            status="new",
            amount="10",
            price="1.29",
        )

        open_orders = [
            Order(
                order_id="bot-order-1",
                market="XRP-EUR",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=bot["operator_id"],
                price="1.29",
                client_order_id=f"{bot['uuid']}:grid:1",
            ),
            Order(
                order_id="manual-order-1",
                market="XRP-EUR",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=bot["operator_id"],
                price="1.30",
                client_order_id="manual-order-1",
            ),
        ]

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_open_orders",
            AsyncMock(return_value=open_orders),
        )

        result = await bot_svc.get_open_orders(bot["id"])

        assert len(result) == 1
        assert result[0]["exchange_order_id"] == "bot-order-1"

    async def test_get_orders_filters_by_reference_id(
        self, config, repos, monkeypatch
    ):
        """Return only exchange order history rows for the bot reference."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="HistoryRef",
            exchange_id=exchange_id,
            market="XRP-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        orders = [
            Order(
                order_id="bot-order-1",
                market="XRP-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.FILLED,
                created=1,
                updated=2,
                amount="10",
                amount_remaining="0",
                price="1.29",
                operator_id=bot["operator_id"],
                client_order_id=f"{bot['uuid']}:grid:1",
            ),
            Order(
                order_id="manual-order-1",
                market="XRP-EUR",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                status=OrderStatus.FILLED,
                created=1,
                updated=2,
                amount="10",
                amount_remaining="0",
                price="1.30",
                operator_id=bot["operator_id"],
                client_order_id="manual-order-1",
            ),
        ]

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_orders",
            AsyncMock(return_value=orders),
        )

        result = await bot_svc.get_orders(bot["id"])

        assert len(result) == 1
        assert result[0]["exchange_order_id"] == "bot-order-1"

    async def test_get_orders_accepts_known_exchange_order_id_without_prefix(
        self, config, repos, monkeypatch
    ):
        """Accept persisted bot orders without a bot-like client id."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="HistoryKnownOrder",
            exchange_id=exchange_id,
            market="XRP-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        await repos["order"].create(
            bot_id=bot["id"],
            exchange_order_id="bot-order-1",
            market="XRP-EUR",
            side="buy",
            order_type="limit",
            status="new",
        )

        orders = [
            Order(
                order_id="bot-order-1",
                market="XRP-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.FILLED,
                created=1,
                updated=2,
                amount="10",
                amount_remaining="0",
                price="1.29",
                operator_id=None,
                client_order_id="6b8a54d7-f727-4310-bfd7-85c61bd1990d",
            )
        ]

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_orders",
            AsyncMock(return_value=orders),
        )

        result = await bot_svc.get_orders(bot["id"])

        assert len(result) == 1
        assert result[0]["exchange_order_id"] == "bot-order-1"

    async def test_get_trades_filters_by_reference_id(
        self, config, repos, monkeypatch
    ):
        """Return only exchange trades from bot-referenced orders."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="TradesRef",
            exchange_id=exchange_id,
            market="XRP-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        orders = [
            Order(
                order_id="bot-order-1",
                market="XRP-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.FILLED,
                created=1,
                updated=2,
                amount="10",
                amount_remaining="0",
                price="1.29",
                operator_id=bot["operator_id"],
                client_order_id=f"{bot['uuid']}:grid:1",
                fills=[
                    OrderFill(
                        fill_id="fill-1",
                        timestamp=1234567890,
                        amount="10",
                        price="1.29",
                        taker=False,
                        fee="0.01",
                        fee_currency="XRP",
                    )
                ],
            ),
            Order(
                order_id="manual-order-1",
                market="XRP-EUR",
                side=OrderSide.SELL,
                order_type=OrderType.LIMIT,
                status=OrderStatus.FILLED,
                created=1,
                updated=2,
                amount="10",
                amount_remaining="0",
                price="1.30",
                operator_id=bot["operator_id"],
                client_order_id="manual-order-1",
                fills=[
                    OrderFill(
                        fill_id="fill-2",
                        timestamp=1234567891,
                        amount="10",
                        price="1.30",
                        taker=False,
                        fee="0.01",
                        fee_currency="XRP",
                    )
                ],
            ),
        ]

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_orders",
            AsyncMock(return_value=orders),
        )

        result = await bot_svc.get_trades(bot["id"])

        assert len(result) == 1
        assert result[0]["exchange_trade_id"] == "fill-1"

    async def test_get_open_orders_requires_matching_operator_id(
        self, config, repos, monkeypatch
    ):
        """Keep bot orders when operator id is missing.

        The bot client id still has to match.
        """
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="StrictOpenOrders",
            exchange_id=exchange_id,
            market="XRP-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        orders = [
            Order(
                order_id="wrong-operator-order",
                market="XRP-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=bot["operator_id"] + 1,
                price="1.29",
                client_order_id=f"{bot['uuid']}:grid:1",
            ),
            Order(
                order_id="missing-operator-order",
                market="XRP-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.NEW,
                created=1,
                updated=1,
                operator_id=None,
                price="1.28",
                client_order_id=f"{bot['uuid']}:grid:2",
            ),
        ]

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_open_orders",
            AsyncMock(return_value=orders),
        )

        result = await bot_svc.get_open_orders(bot["id"])

        assert [row["exchange_order_id"] for row in result] == [
            "missing-operator-order"
        ]

    async def test_get_trades_requires_matching_operator_id(
        self, config, repos, monkeypatch
    ):
        """Exclude trade rows when the parent order operator id mismatches."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="StrictTrades",
            exchange_id=exchange_id,
            market="XRP-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        orders = [
            Order(
                order_id="wrong-operator-order",
                market="XRP-EUR",
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                status=OrderStatus.FILLED,
                created=1,
                updated=2,
                amount="10",
                amount_remaining="0",
                price="1.29",
                operator_id=bot["operator_id"] + 1,
                client_order_id=f"{bot['uuid']}:grid:1",
                fills=[
                    OrderFill(
                        fill_id="fill-bad",
                        timestamp=1234567890,
                        amount="10",
                        price="1.29",
                        taker=False,
                        fee="0.01",
                        fee_currency="XRP",
                    )
                ],
            )
        ]

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_orders",
            AsyncMock(return_value=orders),
        )

        result = await bot_svc.get_trades(bot["id"])

        assert result == []

    async def test_get_grid_levels_marks_only_on_grid_prices(
        self, config, repos, monkeypatch
    ):
        """Mark only bot-owned orders that are effectively on grid levels."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="GridLevels",
            exchange_id=exchange_id,
            market="XRP-EUR",
            strategy="grid_trading",
            strategy_params={
                "lower_price": 1.20,
                "upper_price": 1.40,
                "num_grids": 4,
            },
            budget_quote=100.0,
        )

        monkeypatch.setattr(
            bot_svc,
            "get_open_orders",
            AsyncMock(
                return_value=[
                    {"side": "sell", "price": "1.30"},
                    {"side": "sell", "price": "1.333"},
                ]
            ),
        )

        levels = await bot_svc.get_grid_levels(bot["id"])

        assert len(levels) == 5
        active = [lvl for lvl in levels if lvl["order_type"]]
        assert len(active) == 1
        assert active[0]["index"] == 2
        assert active[0]["order_type"] == "sell"


# ── Worker service tests ─────────────────────────────────────────


class TestWorkerService:
    """Tests for worker registration, approval, and selection logic."""

    async def test_register_worker(self, config, repos):
        """Register a new worker and verify initial pending state."""
        svc = WorkerService(config, repos["worker"], repos["bot"])
        addr = "192.168.1.1"  # NOSONAR
        worker = await svc.register("agent-1", addr, "0.2.0")
        assert worker["agent_id"] == "agent-1"
        assert worker["status"] == "pending"

    async def test_register_rejected_worker_raises(self, config, repos):
        """Block re-registration attempts for workers marked rejected."""
        svc = WorkerService(config, repos["worker"], repos["bot"])
        addr = "192.168.1.2"  # NOSONAR
        worker = await svc.register("agent-2", addr, "0.2.0")
        await svc.reject(worker["id"])

        with pytest.raises(PermissionError):
            await svc.register("agent-2", addr, "0.2.0")

    async def test_approve_worker(self, config, repos):
        """Approve a worker and verify list output reflects approval."""
        svc = WorkerService(config, repos["worker"], repos["bot"])
        addr = "10.0.0.1"  # NOSONAR
        worker = await svc.register("agent-3", addr, "0.2.0")
        await svc.approve(worker["id"])

        workers = await svc.list_workers()
        approved = [w for w in workers if w["agent_id"] == "agent-3"]
        assert approved[0]["status"] == "approved"

    async def test_select_worker(self, config, repos):
        """Select an approved worker when one is available."""
        svc = WorkerService(config, repos["worker"], repos["bot"])
        addr = "10.0.0.2"  # NOSONAR
        worker = await svc.register("agent-4", addr, "0.2.0")
        await svc.approve(worker["id"])

        selected = await svc.select_worker()
        assert selected is not None
        assert selected["agent_id"] == "agent-4"


# ── Log service tests ────────────────────────────────────────────


class TestLogService:
    """Tests for diagnostics log persistence and filtering behavior."""

    async def test_persist_and_search(self, config, repos):
        """Persist a log entry and fetch it by correlation id."""
        log_svc = LogService(config, repos["log"])
        await log_svc.persist(
            category="bot",
            message="Test log message",
            level="INFO",
            correlation_id="abc-123",
            bot_id=1,
        )

        results = await log_svc.search(correlation_id="abc-123")
        assert len(results) == 1
        assert results[0]["message"] == "Test log message"

    async def test_search_by_category(self, config, repos):
        """Filter persisted logs by category and verify only matches return."""
        log_svc = LogService(config, repos["log"])
        await log_svc.persist(category="manager", message="m1")
        await log_svc.persist(category="worker", message="w1")

        results = await log_svc.search(category="manager")
        assert len(results) == 1
        assert results[0]["category"] == "manager"

    def test_set_level(self, config, repos):
        """Set a category override and verify it is stored in memory."""
        log_svc = LogService(config, repos["log"])
        log_svc.set_level("manager.services", "DEBUG")
        levels = log_svc.get_levels()
        assert levels["manager.services"] == "DEBUG"


class TestNewsSettingsRepository:
    """Tests for news source persistence and metadata handling."""

    async def test_create_feed_stores_type_and_weight(self, repos):
        """Persist a feed source with scrape metadata and read it back."""
        feed_id = await repos["news"].create_feed(
            "Example",
            "https://example.com/news",
            source_type="scrape",
            weight=1.5,
        )

        feeds = await repos["news"].list_feeds()
        assert feed_id == feeds[0]["id"]
        assert feeds[0]["source_type"] == "scrape"
        assert feeds[0]["weight"] == pytest.approx(1.5)


class TestNewsOverview:
    """Tests for the weighted crypto news overview calculation."""

    async def test_overview_is_positive_for_weighted_bullish_news(self, db):
        """Combine positive and negative items into a positive overview."""
        store = SignalStore(db)
        await store.ensure_table()

        now = datetime.now(timezone.utc)
        await store.save_article(
            NewsArticle(
                title="Bullish headline",
                url="https://example.com/1",
                source="CoinDesk",
                source_type="rss",
                source_weight=2.0,
                timestamp=now,
                summary="Positive market reaction.",
                content="Bitcoin and Ethereum rally on strong demand.",
                sentiment_label=SentimentLabel.BULLISH,
                sentiment_score=0.8,
                coins=["BTC", "ETH"],
            )
        )
        await store.save_article(
            NewsArticle(
                title="Bearish headline",
                url="https://example.com/2",
                source="Decrypt",
                source_type="rss",
                source_weight=1.0,
                timestamp=now,
                summary="Negative market reaction.",
                content="Crypto sellers take profits after the move.",
                sentiment_label=SentimentLabel.BEARISH,
                sentiment_score=-0.4,
                coins=["BTC"],
            )
        )

        overview = await store.get_news_overview()
        articles = await store.get_latest_articles()

        assert len(articles) == 2
        assert overview["article_count"] == 2
        assert overview["positive_day"] is True
        assert overview["label"] == "positive"


# ── Budget service tests ─────────────────────────────────────────


class TestBudgetService:
    """Tests for recording and retrieving bot budget history."""

    async def test_record_and_get_history(self, config, repos):
        """Record budget snapshots and retrieve them in history output."""
        # Need a bot for FK constraint.
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        bot = await repos["bot"].create(
            name="Bot", exchange_id=exchange_id, market="BTC-EUR",
            strategy="grid_trading", strategy_params={}, operator_id=1,
            budget_quote=100.0,
        )

        svc = BudgetService(repos["bot"], repos["budget"])
        await svc.record_snapshot(bot["id"], 100.50)
        await svc.record_snapshot(bot["id"], 101.25)

        history = await svc.get_history(bot["id"])
        assert len(history) == 2

    async def test_get_all_history_dedups_same_second_per_bot(
        self,
        config,
        repos,
    ):
        """Avoid doubled spikes when one bot reports twice in one second."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        bot = await repos["bot"].create(
            name="Bot",
            exchange_id=exchange_id,
            market="BTC-EUR",
            strategy="grid_trading",
            strategy_params={},
            operator_id=1,
            budget_quote=100.0,
        )

        await repos["budget"].record(bot["id"], 300.0)
        await repos["budget"].record(bot["id"], 300.0)

        history = await repos["budget"].get_all_history(limit=10)

        assert history
        assert history[0]["balance"] == pytest.approx(300.0)

    async def test_get_history_applies_since_minutes_filter(
        self,
        config,
        repos,
        db,
    ):
        """Return only snapshots inside the requested time window."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        bot = await repos["bot"].create(
            name="Bot",
            exchange_id=exchange_id,
            market="BTC-EUR",
            strategy="grid_trading",
            strategy_params={},
            operator_id=1,
            budget_quote=100.0,
        )

        await repos["budget"].record(bot["id"], 200.0)
        await repos["budget"].record(bot["id"], 210.0)

        rows = await db.fetch_all(
            "SELECT id FROM budget_history WHERE bot_id = ? ORDER BY id ASC",
            (bot["id"],),
        )
        await db.execute(
            "UPDATE budget_history SET timestamp = "
            "datetime('now', '-2 hours') "
            "WHERE id = ?",
            (rows[0]["id"],),
        )
        await db.commit()

        recent = await repos["budget"].get_history(
            bot["id"],
            limit=10,
            since_minutes=60,
        )

        assert len(recent) == 1
        assert recent[0]["balance"] == pytest.approx(210.0)

    async def test_get_all_history_applies_since_minutes_filter(
        self,
        config,
        repos,
        db,
    ):
        """Filter aggregated overall history by requested time window."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        bot = await repos["bot"].create(
            name="Bot",
            exchange_id=exchange_id,
            market="ETH-EUR",
            strategy="grid_trading",
            strategy_params={},
            operator_id=1,
            budget_quote=100.0,
        )

        await repos["budget"].record(bot["id"], 300.0)
        await repos["budget"].record(bot["id"], 305.0)

        rows = await db.fetch_all(
            "SELECT id FROM budget_history WHERE bot_id = ? ORDER BY id ASC",
            (bot["id"],),
        )
        await db.execute(
            "UPDATE budget_history SET timestamp = "
            "datetime('now', '-3 hours') "
            "WHERE id = ?",
            (rows[0]["id"],),
        )
        await db.commit()

        overall = await repos["budget"].get_all_history(
            limit=10,
            since_minutes=60,
        )

        assert len(overall) == 1
        assert overall[0]["balance"] == pytest.approx(305.0)


class TestOrderHistoryRepository:
    """Tests for order-history helper lookups."""

    async def test_list_exchange_order_ids_by_bots(self, config, repos):
        """Return only known non-empty exchange ids for provided bots."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        bot1 = await repos["bot"].create(
            name="Bot A",
            exchange_id=exchange_id,
            market="BTC-EUR",
            strategy="grid_trading",
            strategy_params={},
            operator_id=1,
            budget_quote=100.0,
        )
        bot2 = await repos["bot"].create(
            name="Bot B",
            exchange_id=exchange_id,
            market="ETH-EUR",
            strategy="grid_trading",
            strategy_params={},
            operator_id=2,
            budget_quote=100.0,
        )

        await repos["order"].create(
            bot_id=bot1["id"],
            exchange_order_id="ord-1",
            market="BTC-EUR",
            side="buy",
            order_type="limit",
            status="new",
        )
        await repos["order"].create(
            bot_id=bot2["id"],
            exchange_order_id="ord-2",
            market="ETH-EUR",
            side="sell",
            order_type="limit",
            status="new",
        )

        ids = await repos["order"].list_exchange_order_ids_by_bots(
            [bot1["id"]]
        )

        assert ids == {"ord-1"}


class TestBotOrderIsolation:
    """Tests for strict bot-only order visibility and persistence."""

    async def test_get_orders_filters_manual_exchange_history(
        self, config, repos, monkeypatch
    ):
        """Hide history rows whose exchange owner no longer matches."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        worker_svc = WorkerService(config, repos["worker"], repos["bot"])
        bot_svc = BotService(
            repos["bot"], repos["order"], repos["trade"],
            worker_svc, repos["exchange"]
        )
        bot = await bot_svc.create_bot(
            name="OrdersOnly",
            exchange_id=exchange_id,
            market="BTC-EUR",
            strategy="grid_trading",
            strategy_params={},
            budget_quote=100.0,
        )

        await repos["order"].create(
            bot_id=bot["id"],
            exchange_order_id="bot-order-1",
            market="BTC-EUR",
            side="buy",
            order_type="limit",
            status="new",
        )
        await repos["order"].create(
            bot_id=bot["id"],
            exchange_order_id="manual-order-1",
            market="BTC-EUR",
            side="sell",
            order_type="limit",
            status="new",
        )

        from manager.exchanges.bitvavo.client import BitvavoClient

        monkeypatch.setattr(BitvavoClient, "connect", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "authenticate", AsyncMock())
        monkeypatch.setattr(BitvavoClient, "disconnect", AsyncMock())
        monkeypatch.setattr(
            BitvavoClient,
            "get_orders",
            AsyncMock(
                return_value=[
                    Order(
                        order_id="bot-order-1",
                        market="BTC-EUR",
                        side=OrderSide.BUY,
                        order_type=OrderType.LIMIT,
                        status=OrderStatus.NEW,
                        created=1,
                        updated=1,
                        operator_id=bot["operator_id"],
                        client_order_id=f"{bot['uuid']}:grid:1",
                    ),
                    Order(
                        order_id="manual-order-1",
                        market="BTC-EUR",
                        side=OrderSide.SELL,
                        order_type=OrderType.LIMIT,
                        status=OrderStatus.NEW,
                        created=1,
                        updated=1,
                        operator_id=bot["operator_id"] + 99,
                        client_order_id="manual-order-1",
                    ),
                ]
            ),
        )

        orders = await bot_svc.get_orders(bot["id"])

        assert [row["exchange_order_id"] for row in orders] == ["bot-order-1"]

    async def test_handle_order_update_ignores_operator_mismatch(
        self, repos
    ):
        """Drop websocket order updates that do not match the bot operator."""
        exchange_id = await repos["exchange"].create("bitvavo", "k", "s")
        bot = await repos["bot"].create(
            name="WsScope",
            exchange_id=exchange_id,
            market="BTC-EUR",
            strategy="grid_trading",
            strategy_params={},
            operator_id=22,
            budget_quote=100.0,
        )

        state = SimpleNamespace(
            bot_service=SimpleNamespace(get_bot=AsyncMock(return_value=bot)),
            order_repo=SimpleNamespace(create=AsyncMock()),
        )
        app = SimpleNamespace(state=state)

        import manager.api.ws as ws_module

        original_manager = ws_module.manager
        ws_module.manager = SimpleNamespace(broadcast_ui=AsyncMock())
        try:
            await ws_module._handle_order_update(
                app,
                {
                    "bot_id": bot["id"],
                    "exchange_order_id": "manual-1",
                    "market": "BTC-EUR",
                    "side": "sell",
                    "order_type": "limit",
                    "status": "new",
                    "operator_id": 999,
                },
            )
        finally:
            ws_module.manager = original_manager

        state.order_repo.create.assert_not_awaited()


class TestBudgetSnapshotWs:
    """Tests for budget snapshot websocket ingestion."""

    @pytest.mark.asyncio
    async def test_handle_budget_snapshot_records_point(self):
        """Persist valid worker budget snapshots for known bots."""
        bot_service = SimpleNamespace(
            get_bot=AsyncMock(return_value={"id": 7})
        )
        budget_service = SimpleNamespace(record_snapshot=AsyncMock())
        manager_stub = SimpleNamespace(broadcast_ui=AsyncMock())
        state = SimpleNamespace(
            bot_service=bot_service,
            budget_service=budget_service,
        )
        app = SimpleNamespace(state=state)

        import manager.api.ws as ws_module

        original_manager = ws_module.manager
        ws_module.manager = manager_stub
        try:
            await _handle_budget_snapshot(
                app,
                {"bot_id": 7, "balance": "101.23", "price": "2.01"},
            )
        finally:
            ws_module.manager = original_manager

        budget_service.record_snapshot.assert_awaited_once_with(7, 101.23)
        manager_stub.broadcast_ui.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_budget_snapshot_ignores_unknown_bot(self):
        """Skip persistence for snapshot events with unknown bot id."""
        bot_service = SimpleNamespace(get_bot=AsyncMock(return_value=None))
        budget_service = SimpleNamespace(record_snapshot=AsyncMock())
        state = SimpleNamespace(
            bot_service=bot_service,
            budget_service=budget_service,
        )
        app = SimpleNamespace(state=state)

        await _handle_budget_snapshot(
            app,
            {"bot_id": 404, "balance": "88.1", "price": "1.0"},
        )

        budget_service.record_snapshot.assert_not_awaited()
