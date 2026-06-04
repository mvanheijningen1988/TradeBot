"""Tests for the manager services and API layer."""

import asyncio
import os
import tempfile

import pytest

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
from manager.services.log_service import LogService
from manager.services.worker_service import WorkerService


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
    os.environ["TRADEBOT_JWT_SECRET"] = "test-secret-key-12345678901234567890abcd"
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

    async def test_token_roundtrip(self, config, repos):
        """Create and verify a token to validate payload roundtrip."""
        auth = AuthService(config, repos["user"])
        token = auth.create_access_token(1, "admin")
        payload = auth.verify_token(token)
        assert payload is not None
        assert payload["sub"] == "1"
        assert payload["role"] == "admin"

    async def test_verify_invalid_token(self, config, repos):
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
            repos["bot"], repos["order"], repos["trade"], worker_svc
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
            repos["bot"], repos["order"], repos["trade"], worker_svc
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
            repos["bot"], repos["order"], repos["trade"], worker_svc
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
            repos["bot"], repos["order"], repos["trade"], worker_svc
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


# ── Worker service tests ─────────────────────────────────────────


class TestWorkerService:
    """Tests for worker registration, approval, and selection logic."""

    async def test_register_worker(self, config, repos):
        """Register a new worker and verify initial pending state."""
        svc = WorkerService(config, repos["worker"], repos["bot"])
        worker = await svc.register("agent-1", "192.168.1.1", "0.2.0")
        assert worker["agent_id"] == "agent-1"
        assert worker["status"] == "pending"

    async def test_register_rejected_worker_raises(self, config, repos):
        """Block re-registration attempts for workers marked rejected."""
        svc = WorkerService(config, repos["worker"], repos["bot"])
        worker = await svc.register("agent-2", "192.168.1.2", "0.2.0")
        await svc.reject(worker["id"])

        with pytest.raises(PermissionError):
            await svc.register("agent-2", "192.168.1.2", "0.2.0")

    async def test_approve_worker(self, config, repos):
        """Approve a worker and verify list output reflects approval."""
        svc = WorkerService(config, repos["worker"], repos["bot"])
        worker = await svc.register("agent-3", "10.0.0.1", "0.2.0")
        await svc.approve(worker["id"])

        workers = await svc.list_workers()
        approved = [w for w in workers if w["agent_id"] == "agent-3"]
        assert approved[0]["status"] == "approved"

    async def test_select_worker(self, config, repos):
        """Select an approved worker when one is available."""
        svc = WorkerService(config, repos["worker"], repos["bot"])
        worker = await svc.register("agent-4", "10.0.0.2", "0.2.0")
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
