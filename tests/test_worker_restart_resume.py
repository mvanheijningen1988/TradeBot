"""Regression tests for worker restart and bot resume behavior."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from worker.app import WorkerApp
from worker.bot_runner import BotRunner


@pytest.mark.asyncio
async def test_worker_shutdown_preserves_bot_state() -> None:
    """Worker shutdown should not mark bots as stopped."""
    app = WorkerApp()
    app._client = SimpleNamespace(disconnect=AsyncMock())

    runner = SimpleNamespace(stop=AsyncMock())
    app._runners = {1: runner}

    await app.stop()

    runner.stop.assert_awaited_once_with(
        report_stopped=False,
        cancel_strategy=False,
    )
    app._client.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_bot_runner_skip_stopped_status_on_restart_shutdown() -> None:
    """Runner can stop without reporting STOPPED for restart recovery."""
    client = SimpleNamespace(
        send_bot_status=AsyncMock(),
        send_bot_log=AsyncMock(),
        send_error=AsyncMock(),
        send_order_update=AsyncMock(),
    )
    runner = BotRunner(7, {"strategy": "grid_trading"}, client)
    task = asyncio.create_task(asyncio.sleep(60))
    runner.attach_task(task)

    await runner.stop(report_stopped=False, cancel_strategy=False)

    client.send_bot_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot_runner_does_not_cancel_strategy_on_restart_shutdown(
) -> None:
    """Runner finalization should skip strategy.stop during worker restart."""
    client = SimpleNamespace(
        send_bot_status=AsyncMock(),
        send_bot_log=AsyncMock(),
        send_error=AsyncMock(),
        send_order_update=AsyncMock(),
    )
    runner = BotRunner(42, {"strategy": "grid_trading"}, client)

    fake_strategy = SimpleNamespace(
        _exchange=SimpleNamespace(
            get_ticker_price=AsyncMock(
                return_value=SimpleNamespace(price="1")
            )
        ),
        _config=SimpleNamespace(market="BTC-EUR"),
        set_log_callback=lambda *_args, **_kwargs: None,
        set_order_callback=lambda *_args, **_kwargs: None,
        start=AsyncMock(),
        on_tick=AsyncMock(),
        stop=AsyncMock(),
    )

    runner._create_strategy = AsyncMock(return_value=fake_strategy)

    task = asyncio.create_task(runner.run())
    runner.attach_task(task)
    await asyncio.sleep(0)

    await runner.stop(report_stopped=False, cancel_strategy=False)

    fake_strategy.stop.assert_not_awaited()


def test_worker_default_agent_id_is_stable(monkeypatch) -> None:
    """Without env override, worker id should be deterministic."""
    monkeypatch.delenv("WORKER_AGENT_ID", raising=False)
    monkeypatch.setenv("WORKER_ADDRESS", "node-1")

    app = WorkerApp()

    assert app.agent_id == "worker-node-1"
