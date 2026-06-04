"""Worker management service.

Handles registration, authorization, heartbeat tracking, health
monitoring, and load balancing of Worker Nodes.
"""

import asyncio
import logging
from typing import Any, Callable, Coroutine, Optional

from manager.config import Config
from manager.constants import (
    WORKER_STATUS_APPROVED,
    WORKER_STATUS_ONLINE,
    WORKER_STATUS_PENDING,
    WORKER_STATUS_REJECTED,
    WORKER_STATUS_UNRESPONSIVE,
    WS_TYPE_WORKER_REGISTERED,
    WS_TYPE_WORKER_STATUS,
)
from manager.database.repositories import BotRepository, WorkerRepository
from manager.services.log_service import LogService

logger = logging.getLogger(__name__)

# Async callback for broadcasting messages to UI clients.
BroadcastFn = Callable[[dict], Coroutine[Any, Any, None]]


class WorkerService:
    """Manages Worker Node lifecycle and health."""

    def __init__(
        self,
        config: Config,
        worker_repo: WorkerRepository,
        bot_repo: BotRepository,
        log_service: Optional["LogService"] = None,
    ) -> None:
        self._config = config
        self._worker_repo = worker_repo
        self._bot_repo = bot_repo
        self._log_service = log_service
        # Connected workers: agent_id -> websocket
        self._connections: dict[str, object] = {}
        self._health_task: Optional[asyncio.Task] = None
        self._broadcast_ui: Optional[BroadcastFn] = None

    def set_broadcast_callback(self, fn: BroadcastFn) -> None:
        """Set the callback used to push events to all connected UI clients."""
        self._broadcast_ui = fn

    async def _notify_ui(self, data: dict) -> None:
        """Broadcast a message to UI clients if callback is set."""
        if self._broadcast_ui:
            logger.info(
                "Broadcasting %s to UI clients.",
                data.get("type", "unknown"),
            )
            await self._broadcast_ui(data)
        else:
            logger.warning(
                "No broadcast callback set, cannot notify UI of %s.",
                data.get("type", "unknown"),
            )

    async def _persist_log(
        self,
        category: str,
        message: str,
        level: str = "INFO",
        subcategory: str = "",
        worker_id: Optional[int] = None,
        bot_id: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Persist a log entry if log service is available and level passes."""
        if not self._log_service:
            return
        if not self._log_service.should_log(category, level):
            return
        await self._log_service.persist(
            category=category,
            message=message,
            level=level,
            subcategory=subcategory,
            worker_id=worker_id,
            bot_id=bot_id,
            correlation_id=correlation_id,
        )

    async def register(
        self, agent_id: str, address: str, version: str
    ) -> dict:
        """Register a new Worker Node or return existing."""
        existing = await self._worker_repo.get_by_agent_id(agent_id)
        if existing:
            if existing["status"] == WORKER_STATUS_REJECTED:
                raise PermissionError(
                    f"Worker {agent_id} was rejected. "
                    "Contact administrator."
                )
            await self._worker_repo.update_heartbeat(existing["id"])
            await self._persist_log(
                "worker", f"Worker {agent_id} re-registered from {address}",
                worker_id=existing["id"], subcategory="registration",
            )
            if existing["status"] == WORKER_STATUS_PENDING:
                await self._notify_ui({
                    "type": WS_TYPE_WORKER_REGISTERED,
                    "worker": existing,
                })
            else:
                await self._notify_ui({
                    "type": WS_TYPE_WORKER_STATUS,
                    "worker_id": existing["id"],
                    "status": existing["status"],
                    "worker": existing,
                })
            return existing

        worker_id = await self._worker_repo.create(
            agent_id=agent_id, address=address, version=version
        )
        worker = await self._worker_repo.get_by_id(worker_id)
        logger.info(
            "Worker registered: agent_id=%s address=%s (pending approval)",
            agent_id,
            address,
        )
        await self._persist_log(
            "worker",
            f"Worker {agent_id} registered from {address}"
            f" v{version} (pending approval)",
            worker_id=worker_id, subcategory="registration",
        )
        # Notify UI about new worker pending approval.
        await self._notify_ui({
            "type": WS_TYPE_WORKER_REGISTERED,
            "worker": worker,
        })
        return worker

    async def approve(self, worker_id: int) -> None:
        """Approve a pending worker."""
        await self._worker_repo.approve(worker_id)
        logger.info("Worker %d approved.", worker_id)
        await self._persist_log(
            "worker", f"Worker {worker_id} approved",
            worker_id=worker_id, subcategory="lifecycle",
        )
        worker = await self._worker_repo.get_by_id(worker_id)
        await self._notify_ui({
            "type": WS_TYPE_WORKER_STATUS,
            "worker_id": worker_id,
            "status": WORKER_STATUS_APPROVED,
            "worker": worker,
        })

    async def reject(self, worker_id: int) -> None:
        """Reject a pending worker."""
        await self._worker_repo.reject(worker_id)
        logger.info("Worker %d rejected.", worker_id)
        await self._persist_log(
            "worker", f"Worker {worker_id} rejected",
            level="WARNING", worker_id=worker_id, subcategory="lifecycle",
        )
        await self._notify_ui({
            "type": WS_TYPE_WORKER_STATUS,
            "worker_id": worker_id,
            "status": WORKER_STATUS_REJECTED,
        })

    async def heartbeat(self, agent_id: str) -> None:
        """Update heartbeat timestamp for a worker."""
        worker = await self._worker_repo.get_by_agent_id(agent_id)
        if worker:
            await self._worker_repo.update_heartbeat(worker["id"])
            if worker["status"] != WORKER_STATUS_ONLINE:
                await self._worker_repo.update_status(
                    worker["id"], WORKER_STATUS_ONLINE
                )
                await self._persist_log(
                    "worker",
                    f"Worker {agent_id} is now online",
                    worker_id=worker["id"], subcategory="lifecycle",
                )

    def register_connection(self, agent_id: str, ws: object) -> None:
        """Track a WebSocket connection for a worker."""
        self._connections[agent_id] = ws

    def unregister_connection(self, agent_id: str) -> None:
        """Remove a tracked WebSocket connection."""
        self._connections.pop(agent_id, None)

    def get_connection(self, agent_id: str) -> Optional[object]:
        """Get the WebSocket connection for a worker."""
        return self._connections.get(agent_id)

    async def send_command(
        self, worker_id: int, message: dict
    ) -> bool:
        """Send a command to a worker via its WebSocket connection."""
        worker = await self._worker_repo.get_by_id(worker_id)
        if not worker:
            logger.error(
                "Cannot send command: worker %d not found.",
                worker_id,
            )
            return False
        agent_id = worker["agent_id"]
        ws = self._connections.get(agent_id)
        if not ws:
            logger.error(
                "Cannot send command: worker %d (%s) not connected.",
                worker_id, agent_id,
            )
            return False
        try:
            await ws.send_json(message)
            logger.info(
                "Sent %s to worker %d (%s).",
                message.get("type", "unknown"), worker_id, agent_id,
            )
            return True
        except Exception:
            logger.exception(
                "Failed to send command to worker %d (%s).",
                worker_id, agent_id,
            )
            self._connections.pop(agent_id, None)
            return False

    async def select_worker(self) -> Optional[dict]:
        """Select the least-loaded approved worker for bot assignment."""
        workers = await self._worker_repo.get_approved_online()
        if not workers:
            return None

        # Load balance: pick worker with fewest bots.
        best = None
        min_bots = float("inf")
        for w in workers:
            bots = await self._bot_repo.list_by_worker(w["id"])
            running = [b for b in bots if b["status"] != "stopped"]
            if len(running) < min_bots:
                min_bots = len(running)
                best = w
        return best

    async def list_workers(self) -> list[dict]:
        """Return all registered workers."""
        return await self._worker_repo.list_all()

    async def remove(self, worker_id: int) -> None:
        """Remove a worker after reassigning its bots."""
        bots = await self._bot_repo.list_by_worker(worker_id)
        for bot in bots:
            await self._bot_repo.update(bot["id"], worker_id=None)
            await self._bot_repo.update_status(bot["id"], "stopped")
        await self._persist_log(
            "worker",
            f"Worker {worker_id} removed, {len(bots)} bot(s) stopped",
            level="WARNING",
            worker_id=worker_id,
            subcategory="lifecycle",
        )
        await self._worker_repo.delete(worker_id)
        logger.info("Worker %d removed, bots stopped.", worker_id)

    def start_health_monitor(self) -> None:
        """Start the background health check loop."""
        self._health_task = asyncio.create_task(self._health_loop())

    async def stop_health_monitor(self) -> None:
        """Stop the health check loop."""
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                raise

    async def _health_loop(self) -> None:
        """Periodically check worker heartbeats."""
        try:
            while True:
                await asyncio.sleep(self._config.worker_heartbeat_timeout)
                workers = await self._worker_repo.list_all()
                for w in workers:
                    if w["status"] in (
                        WORKER_STATUS_PENDING,
                        WORKER_STATUS_REJECTED,
                    ):
                        continue
                    if w["last_heartbeat"] is None:
                        continue
                    # Mark unresponsive if heartbeat stale.
                    if w["agent_id"] not in self._connections:
                        await self._worker_repo.update_status(
                            w["id"], WORKER_STATUS_UNRESPONSIVE
                        )
                        logger.warning(
                            "Worker %s marked unresponsive.",
                            w["agent_id"],
                        )
                        await self._notify_ui({
                            "type": WS_TYPE_WORKER_STATUS,
                            "worker_id": w["id"],
                            "status": WORKER_STATUS_UNRESPONSIVE,
                        })
        except asyncio.CancelledError:
            raise
