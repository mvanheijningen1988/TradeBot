"""WebSocket endpoint for UI real-time updates and worker communication."""

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from manager.constants import (
    WS_TYPE_BOT_LOG,
    WS_TYPE_BOT_STATUS,
    WS_TYPE_ERROR,
    WS_TYPE_HEARTBEAT,
    WS_TYPE_ORDER_UPDATE,
    WS_TYPE_STATUS,
    WS_TYPE_WORKER_LOG,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections for the UI and workers."""

    def __init__(self) -> None:
        # UI connections.
        self._ui_clients: list[WebSocket] = []
        # Worker connections: agent_id -> websocket.
        self._worker_clients: dict[str, WebSocket] = {}

    async def connect_ui(self, ws: WebSocket) -> None:
        await ws.accept()
        self._ui_clients.append(ws)

    def disconnect_ui(self, ws: WebSocket) -> None:
        if ws in self._ui_clients:
            self._ui_clients.remove(ws)

    async def connect_worker(
        self, ws: WebSocket, agent_id: str
    ) -> None:
        await ws.accept()
        self._worker_clients[agent_id] = ws

    def disconnect_worker(self, agent_id: str) -> None:
        self._worker_clients.pop(agent_id, None)

    async def broadcast_ui(self, data: dict) -> None:
        """Send a message to all connected UI clients."""
        logger.debug(
            "Broadcasting to %d UI client(s): type=%s",
            len(self._ui_clients),
            data.get("type", "unknown"),
        )
        dead: list[WebSocket] = []
        for client in self._ui_clients:
            try:
                await client.send_json(data)
            except Exception:
                dead.append(client)
        for d in dead:
            self.disconnect_ui(d)

    async def send_to_worker(
        self, agent_id: str, data: dict
    ) -> bool:
        """Send a message to a specific worker."""
        ws = self._worker_clients.get(agent_id)
        if not ws:
            return False
        try:
            await ws.send_json(data)
            return True
        except Exception:
            self.disconnect_worker(agent_id)
            return False

    async def broadcast_workers(self, data: dict) -> None:
        """Send a message to all connected workers."""
        dead: list[str] = []
        for agent_id, ws in self._worker_clients.items():
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(agent_id)
        for d in dead:
            self.disconnect_worker(d)


# Global instance – attached to app.state in app.py.
manager = ConnectionManager()


@router.websocket("/ws/ui")
async def ws_ui(websocket: WebSocket):
    """WebSocket endpoint for UI real-time updates.

    Validates JWT token from query parameter before accepting.
    """
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001)
        return

    auth = websocket.app.state.auth_service
    payload = auth.verify_token(token)
    if not payload:
        await websocket.close(code=4001)
        return

    await manager.connect_ui(websocket)
    logger.info("UI client connected (user=%s)", payload.get("sub"))
    try:
        while True:
            # UI clients mostly receive; ignore incoming for now.
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect_ui(websocket)
        logger.info("UI client disconnected.")


@router.websocket("/ws/worker")
async def ws_worker(websocket: WebSocket):
    """WebSocket endpoint for Worker Node communication.

    Worker identifies itself via agent_id query parameter.
    """
    agent_id = websocket.query_params.get("agent_id")
    if not agent_id:
        await websocket.close(code=4002)
        return

    worker_svc = websocket.app.state.worker_service
    worker = await worker_svc._worker_repo.get_by_agent_id(agent_id)
    if not worker:
        await websocket.close(code=4003)
        return
    if worker.get("status") in ("rejected", "pending"):
        await websocket.close(code=4003)
        return

    await manager.connect_worker(websocket, agent_id)
    worker_svc.register_connection(agent_id, websocket)
    logger.info("Worker connected: %s", agent_id)

    # Restore bots that were previously started before restart/failover.
    try:
        bot_svc = websocket.app.state.bot_service
        restored_assigned = await bot_svc.restore_bots_for_worker(worker["id"])
        restored_unassigned = await bot_svc.restore_unassigned_bots()
        if restored_assigned or restored_unassigned:
            logger.info(
                "Recovered %d assigned and %d unassigned bot(s) on "
                "worker connect %s.",
                restored_assigned,
                restored_unassigned,
                agent_id,
            )
    except Exception:
        logger.exception("Failed bot recovery for worker %s.", agent_id)

    log_svc = websocket.app.state.log_service
    if log_svc.should_log("worker", "INFO"):
        await log_svc.persist(
            category="worker",
            message=f"Worker {agent_id} WebSocket connected",
            level="INFO",
            subcategory="connection",
            worker_id=worker["id"],
        )

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type")
            await _handle_worker_message(
                websocket.app, agent_id, msg_type, msg
            )
    except WebSocketDisconnect:
        manager.disconnect_worker(agent_id)
        worker_svc.unregister_connection(agent_id)
        logger.info("Worker disconnected: %s", agent_id)
        if log_svc.should_log("worker", "WARNING"):
            await log_svc.persist(
                category="worker",
                message=f"Worker {agent_id} WebSocket disconnected",
                level="WARNING",
                subcategory="connection",
                worker_id=worker["id"],
            )


async def _handle_worker_message(
    app: Any, agent_id: str, msg_type: str, msg: dict
) -> None:
    """Route incoming worker messages."""
    if msg_type == WS_TYPE_HEARTBEAT:
        await app.state.worker_service.heartbeat(agent_id)
    elif msg_type == WS_TYPE_BOT_STATUS:
        await _handle_bot_status(app, agent_id, msg)
    elif msg_type == WS_TYPE_BOT_LOG:
        await _handle_bot_log(app, agent_id, msg)
    elif msg_type == WS_TYPE_WORKER_LOG:
        await _handle_worker_log(app, agent_id, msg)
    elif msg_type == WS_TYPE_ERROR:
        await _handle_worker_error(app, agent_id, msg)
    elif msg_type == WS_TYPE_ORDER_UPDATE:
        await _handle_order_update(app, msg)


async def _handle_bot_status(
    app: Any, agent_id: str, msg: dict
) -> None:
    """Process WS_TYPE_BOT_STATUS messages from a worker."""
    bot_svc = app.state.bot_service
    log_svc = app.state.log_service
    bot_id = msg.get("bot_id")
    status = msg.get("status")
    if not (bot_id and status):
        return
    await bot_svc.update_bot_status(bot_id, status)
    await manager.broadcast_ui(
        {"type": WS_TYPE_STATUS, "bot_id": bot_id, "status": status}
    )
    worker_repo = app.state.worker_service._worker_repo
    worker = await worker_repo.get_by_agent_id(agent_id)
    wid = worker["id"] if worker else None
    if log_svc.should_log("bot", "INFO"):
        await log_svc.persist(
            category="bot",
            message=f"Bot {bot_id} status changed to {status}",
            level="INFO",
            subcategory="status",
            bot_id=bot_id,
            worker_id=wid,
        )


async def _handle_bot_log(
    app: Any, agent_id: str, msg: dict
) -> None:
    """Process WS_TYPE_BOT_LOG messages from a worker."""
    log_svc = app.state.log_service
    worker_repo = app.state.worker_service._worker_repo
    worker = await worker_repo.get_by_agent_id(agent_id)
    wid = worker["id"] if worker else None
    msg_level = msg.get("level", "INFO")
    if log_svc.should_log("bot", msg_level):
        await log_svc.persist(
            category="bot",
            message=msg.get("message", ""),
            level=msg_level,
            subcategory=msg.get("subcategory", ""),
            correlation_id=msg.get("correlation_id"),
            bot_id=msg.get("bot_id"),
            worker_id=wid,
        )
    msg["worker_id"] = wid
    await manager.broadcast_ui(msg)


async def _handle_worker_log(
    app: Any, agent_id: str, msg: dict
) -> None:
    """Process WS_TYPE_WORKER_LOG messages from a worker."""
    log_svc = app.state.log_service
    worker_repo = app.state.worker_service._worker_repo
    worker = await worker_repo.get_by_agent_id(agent_id)
    wid = worker["id"] if worker else None
    msg_level = msg.get("level", "INFO")
    if log_svc.should_log("worker", msg_level):
        await log_svc.persist(
            category="worker",
            message=msg.get("message", ""),
            level=msg_level,
            subcategory=msg.get("subcategory", ""),
            correlation_id=msg.get("correlation_id"),
            worker_id=wid,
        )
    fwd = {
        "type": WS_TYPE_BOT_LOG,
        "category": "worker",
        "subcategory": msg.get("subcategory", ""),
        "level": msg_level,
        "message": msg.get("message", ""),
        "worker_id": wid,
        "correlation_id": msg.get("correlation_id"),
    }
    await manager.broadcast_ui(fwd)


async def _handle_worker_error(
    app: Any, agent_id: str, msg: dict
) -> None:
    """Process WS_TYPE_ERROR messages from a worker."""
    bot_svc = app.state.bot_service
    log_svc = app.state.log_service
    bot_id = msg.get("bot_id")
    error_msg = msg.get("message", "Unknown error")
    if bot_id:
        await bot_svc.report_fault(bot_id)
    logger.error("Worker %s error: %s", agent_id, error_msg)
    worker_repo = app.state.worker_service._worker_repo
    worker = await worker_repo.get_by_agent_id(agent_id)
    wid = worker["id"] if worker else None
    if log_svc.should_log("bot", "ERROR"):
        await log_svc.persist(
            category="bot",
            message=error_msg,
            level="ERROR",
            subcategory="fault",
            bot_id=bot_id,
            worker_id=wid,
        )


async def _handle_order_update(
    app: Any, msg: dict
) -> None:
    """Process WS_TYPE_ORDER_UPDATE messages from a worker."""
    bot_svc = app.state.bot_service
    bot_id = msg.get("bot_id")
    if not bot_id:
        return
    bot = await bot_svc.get_bot(bot_id)
    if not bot:
        logger.warning(
            "Ignoring order_update for unknown bot_id=%s", bot_id
        )
        return
    order_id = await app.state.order_repo.create(
        bot_id=bot_id,
        exchange_order_id=msg.get("exchange_order_id", ""),
        market=msg.get("market", ""),
        side=msg.get("side", ""),
        order_type=msg.get("order_type", ""),
        status=msg.get("status", "new"),
        amount=msg.get("amount"),
        price=msg.get("price"),
    )
    await manager.broadcast_ui({
        "type": WS_TYPE_ORDER_UPDATE,
        "bot_id": bot_id,
        "order": {
            "id": order_id,
            "bot_id": bot_id,
            "exchange_order_id": msg.get("exchange_order_id", ""),
            "market": msg.get("market", ""),
            "side": msg.get("side", ""),
            "order_type": msg.get("order_type", ""),
            "status": msg.get("status", "new"),
            "amount": msg.get("amount", ""),
            "price": msg.get("price", ""),
        },
    })
