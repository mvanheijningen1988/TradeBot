"""Worker Node application.

Connects to the Manager Node, receives bot assignments, and runs
bots in-process.  Reports status, performance, and logs via WebSocket.
"""

import asyncio
import json
import logging
import os
import platform
import signal
import uuid
from typing import Optional

import websockets

from manager.constants import (
    WS_TYPE_ASSIGN,
    WS_TYPE_BOT_LOG,
    WS_TYPE_BOT_STATUS,
    WS_TYPE_ERROR,
    WS_TYPE_HEARTBEAT,
    WS_TYPE_START_BOT,
    WS_TYPE_STOP_BOT,
)
from worker.bot_runner import BotRunner
from worker.manager_client import ManagerClient

logger = logging.getLogger(__name__)


class WorkerApp:
    """Worker Node main application."""

    def __init__(self) -> None:
        self.agent_id: str = os.getenv(
            "WORKER_AGENT_ID", str(uuid.uuid4())[:8]
        )
        self.manager_url: str = os.getenv(
            "MANAGER_URL", "http://localhost:8000"
        )
        self.manager_ws_url: str = os.getenv(
            "MANAGER_WS_URL", "ws://localhost:8000/ws/worker"
        )
        self.version: str = "0.2.0"
        self.address: str = os.getenv(
            "WORKER_ADDRESS", platform.node()
        )

        self._client: Optional[ManagerClient] = None
        self._runners: dict[int, BotRunner] = {}
        self._running = False

    async def start(self) -> None:
        """Register with manager and start the main loop."""
        logging.basicConfig(
            level=os.getenv("WORKER_LOG_LEVEL", "INFO"),
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

        self._client = ManagerClient(
            manager_url=self.manager_url,
            manager_ws_url=self.manager_ws_url,
            agent_id=self.agent_id,
            address=self.address,
            version=self.version,
        )

        # Register with manager (REST).
        registered = await self._client.register()
        if not registered:
            logger.error("Failed to register with manager. Exiting.")
            return

        # Connect WebSocket.
        connected = await self._client.connect_ws()
        if not connected:
            logger.error("Failed to connect WebSocket. Exiting.")
            return

        self._running = True
        logger.info(
            "Worker %s started, connected to %s",
            self.agent_id,
            self.manager_url,
        )

        # Run heartbeat and message receiver concurrently.
        await asyncio.gather(
            self._heartbeat_loop(),
            self._receive_loop(),
        )

    async def stop(self) -> None:
        """Stop all bots and disconnect."""
        self._running = False
        for bot_id, runner in list(self._runners.items()):
            await runner.stop()
        self._runners.clear()
        if self._client:
            await self._client.disconnect()
        logger.info("Worker %s stopped.", self.agent_id)

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to the manager."""
        try:
            while self._running:
                await self._client.send_heartbeat()
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Heartbeat loop error.")

    async def _receive_loop(self) -> None:
        """Receive and handle messages from the manager."""
        try:
            while self._running:
                msg = await self._client.receive()
                if msg is None:
                    # Connection lost, try reconnect.
                    logger.warning("Manager connection lost, reconnecting...")
                    reconnected = await self._client.connect_ws()
                    if not reconnected:
                        logger.error("Reconnection failed.")
                        self._running = False
                        break
                    continue

                await self._handle_message(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Receive loop error.")

    async def _handle_message(self, msg: dict) -> None:
        """Route an incoming manager message."""
        msg_type = msg.get("type")

        if msg_type == WS_TYPE_START_BOT:
            bot_id = msg.get("bot_id")
            bot_config = msg.get("config", {})
            await self._start_bot(bot_id, bot_config)

        elif msg_type == WS_TYPE_STOP_BOT:
            bot_id = msg.get("bot_id")
            await self._stop_bot(bot_id)

        elif msg_type == WS_TYPE_ASSIGN:
            bot_id = msg.get("bot_id")
            bot_config = msg.get("config", {})
            await self._start_bot(bot_id, bot_config)

    async def _start_bot(self, bot_id: int, config: dict) -> None:
        """Start a bot runner for the given bot."""
        if bot_id in self._runners:
            logger.warning("Bot %d already running.", bot_id)
            return

        runner = BotRunner(bot_id, config, self._client)
        self._runners[bot_id] = runner
        asyncio.create_task(runner.run())
        logger.info("Bot %d started.", bot_id)

    async def _stop_bot(self, bot_id: int) -> None:
        """Stop a running bot."""
        runner = self._runners.pop(bot_id, None)
        if runner:
            await runner.stop()
            logger.info("Bot %d stopped.", bot_id)


def main() -> None:
    """Entry point for the worker process."""
    app = WorkerApp()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _shutdown(sig, _frame):
        loop.create_task(app.stop())

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(app.start())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
