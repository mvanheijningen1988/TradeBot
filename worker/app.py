"""Worker Node application.

Connects to the Manager Node, receives bot assignments, and runs
bots in-process.  Reports status, performance, and logs via WebSocket.
"""

import asyncio
import logging
import os
import platform
import re
import signal
from typing import Optional

from manager.constants import (
    WS_TYPE_ASSIGN,
    WS_TYPE_SET_LOG_LEVEL,
    WS_TYPE_START_BOT,
    WS_TYPE_STOP_BOT,
)
from worker.bot_runner import BotRunner
from worker.manager_client import ManagerClient

logger = logging.getLogger(__name__)


class _WorkerForwardLogHandler(logging.Handler):
    """Forward worker process logs to manager diagnostics stream."""

    def __init__(self, app: "WorkerApp") -> None:
        """Create a forwarding handler for worker runtime logs.

        Args:
            app: Worker application owning manager client lifecycle.
        """
        super().__init__()
        self._app = app
        self._bot_id_pattern = re.compile(r"\\b[bB]ot\\s+(\\d+)\\b")
        self._excluded_prefixes = (
            "worker.manager_client",
            "websockets",
            "httpx",
            "httpcore",
            "asyncio",
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Forward eligible log records to manager diagnostics stream.

        Args:
            record: Python logging record produced by worker runtime.
        """
        if any(
            record.name.startswith(prefix)
            for prefix in self._excluded_prefixes
        ):
            return

        client = self._app._client
        if client is None:
            return

        try:
            message = record.getMessage()
        except Exception:
            return

        level = record.levelname.upper()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        loop.create_task(
            self._forward(client, record.name, message, level)
        )

    async def _forward(
        self,
        client: ManagerClient,
        logger_name: str,
        message: str,
        level: str,
    ) -> None:
        """Forward one prepared log message using worker/bot channels.

        Args:
            client: Connected manager client.
            logger_name: Logger namespace for subcategory routing.
            message: Rendered log message.
            level: Log level text.
        """
        match = self._bot_id_pattern.search(message)
        if logger_name.startswith("worker.bot_runner") and match:
            await client.send_bot_log(
                int(match.group(1)),
                message,
                level=level,
            )
            return

        await client.send_worker_log(
            message,
            level=level,
            subcategory=logger_name,
        )


class WorkerApp:
    """Worker Node main application."""

    def __init__(self) -> None:
        """Initialize worker runtime configuration and in-memory state."""
        self.address: str = os.getenv(
            "WORKER_ADDRESS", platform.node()
        )
        default_agent_id = f"worker-{self.address}"
        self.agent_id: str = os.getenv(
            "WORKER_AGENT_ID", default_agent_id
        )
        self.manager_url: str = os.getenv(
            "MANAGER_URL", "http://localhost:8000"
        )
        self.manager_ws_url: str = os.getenv(
            "MANAGER_WS_URL", "ws://localhost:8000/ws/worker"
        )
        self.version: str = "0.2.0"

        self._client: Optional[ManagerClient] = None
        self._runners: dict[int, BotRunner] = {}
        self._running = False
        self._forward_log_handler: Optional[logging.Handler] = None

    async def start(self) -> None:
        """Start worker lifecycle: register, connect, and process events.

        Returns:
            ``None``.
        """
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

        if self._forward_log_handler is None:
            self._forward_log_handler = _WorkerForwardLogHandler(self)
            logging.getLogger().addHandler(self._forward_log_handler)

        self._running = True
        logger.info(
            "Worker %s started, connected to %s",
            self.agent_id,
            self.manager_url,
        )
        await self._client.send_worker_log(
            f"Worker {self.agent_id} started (v{self.version})",
            subcategory="lifecycle",
        )

        # Run heartbeat and message receiver concurrently.
        await asyncio.gather(
            self._heartbeat_loop(),
            self._receive_loop(),
        )

    async def stop(self) -> None:
        """Stop all running bot tasks and disconnect from manager."""
        self._running = False
        for bot_id, runner in self._runners.items():
            await runner.stop(report_stopped=False, cancel_strategy=False)
        self._runners.clear()
        if self._client:
            await self._client.disconnect()
        if self._forward_log_handler is not None:
            logging.getLogger().removeHandler(self._forward_log_handler)
            self._forward_log_handler = None
        logger.info("Worker %s stopped.", self.agent_id)

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeat events while worker is active."""
        try:
            while self._running:
                await self._client.send_heartbeat()
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Heartbeat loop error.")

    async def _receive_loop(self) -> None:
        """Receive manager websocket messages and dispatch handlers."""
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
            raise
        except Exception:
            logger.exception("Receive loop error.")

    async def _handle_message(self, msg: dict) -> None:
        """Route one manager message based on websocket type.

        Args:
            msg: Parsed websocket payload from manager.
        """
        msg_type = msg.get("type")

        if msg_type in (WS_TYPE_START_BOT, WS_TYPE_ASSIGN):
            bot_id = msg.get("bot_id")
            bot_config = msg.get("config", {})
            await self._start_bot(bot_id, bot_config)

        elif msg_type == WS_TYPE_STOP_BOT:
            bot_id = msg.get("bot_id")
            await self._stop_bot(bot_id)

        elif msg_type == WS_TYPE_SET_LOG_LEVEL:
            category = msg.get("category", "*")
            level = msg.get("level", "INFO")
            log_name = category if category != "*" else ""
            logging.getLogger(log_name).setLevel(level.upper())
            logger.info(
                "Log level for '%s' set to %s (from manager)",
                category, level.upper(),
            )

    async def _start_bot(self, bot_id: int, config: dict) -> None:
        """Create and run a bot runner for one bot assignment.

        Args:
            bot_id: Bot identifier.
            config: Bot runtime configuration payload.
        """
        if bot_id in self._runners:
            logger.warning("Bot %d already running.", bot_id)
            return

        runner = BotRunner(bot_id, config, self._client)
        self._runners[bot_id] = runner

        async def _run_and_cleanup() -> None:
            try:
                await runner.run()
            finally:
                self._runners.pop(bot_id, None)
                logger.debug("Bot %d runner removed from registry.", bot_id)

        runner.attach_task(asyncio.create_task(_run_and_cleanup()))
        logger.info("Bot %d started.", bot_id)
        await self._client.send_worker_log(
            f"Bot {bot_id} started on worker",
            subcategory="bot-lifecycle",
        )

    async def _stop_bot(self, bot_id: int) -> None:
        """Stop and remove one running bot runner.

        Args:
            bot_id: Bot identifier.
        """
        runner = self._runners.pop(bot_id, None)
        if runner:
            await runner.stop()
            logger.info("Bot %d stopped.", bot_id)
            await self._client.send_worker_log(
                f"Bot {bot_id} stopped on worker",
                subcategory="bot-lifecycle",
            )


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
