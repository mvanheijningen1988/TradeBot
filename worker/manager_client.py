"""Manager Node client for the Worker.

Handles REST registration and WebSocket communication with the Manager.
"""

import json
import logging
from typing import Optional

import httpx
import websockets

from manager.constants import (
    WS_TYPE_BUDGET_SNAPSHOT,
    WS_TYPE_BOT_LOG,
    WS_TYPE_BOT_STATUS,
    WS_TYPE_ERROR,
    WS_TYPE_HEARTBEAT,
    WS_TYPE_ORDER_UPDATE,
    WS_TYPE_WORKER_LOG,
)

logger = logging.getLogger(__name__)


class ManagerClient:
    """Handles communication between Worker and Manager."""

    def __init__(
        self,
        manager_url: str,
        manager_ws_url: str,
        agent_id: str,
        address: str,
        version: str,
    ) -> None:
        """Initialize manager API and websocket client state.

        Args:
            manager_url: Base HTTP url for manager REST endpoints.
            manager_ws_url: WebSocket endpoint base url for worker channel.
            agent_id: Worker agent identity.
            address: Worker network address metadata.
            version: Worker runtime version string.
        """
        self._manager_url = manager_url.rstrip("/")
        self._manager_ws_url = manager_ws_url
        self._agent_id = agent_id
        self._address = address
        self._version = version
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._max_retries = 5

    async def register(self) -> bool:
        """Register this worker with the Manager via REST.

        Retries with exponential backoff on network errors and stops
        immediately on explicit rejection (HTTP 403).

        Returns:
            ``True`` when worker registration succeeds; otherwise ``False``.
        """
        import asyncio

        for attempt in range(self._max_retries):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(
                        f"{self._manager_url}/api/workers/register",
                        json={
                            "agent_id": self._agent_id,
                            "address": self._address,
                            "version": self._version,
                        },
                    )
                if resp.status_code == 201:
                    logger.info("Registered with manager.")
                    return True
                if resp.status_code == 403:
                    logger.error(
                        "Registration rejected: %s", resp.text
                    )
                    return False
                logger.warning(
                    "Registration attempt %d/%d: %s",
                    attempt + 1, self._max_retries, resp.text,
                )
            except Exception as exc:
                logger.warning(
                    "Registration attempt %d/%d failed: %s",
                    attempt + 1, self._max_retries, exc,
                )

            backoff = min(2 ** attempt, 30)
            await asyncio.sleep(backoff)

        logger.error(
            "Registration failed after %d attempts.",
            self._max_retries,
        )
        return False

    async def connect_ws(self) -> bool:
        """Establish worker websocket connection to manager.

        Returns:
            ``True`` when the socket is connected; otherwise ``False``.
        """
        try:
            url = f"{self._manager_ws_url}?agent_id={self._agent_id}"
            self._ws = await websockets.connect(url)
            logger.info("WebSocket connected to manager.")
            return True
        except Exception:
            logger.exception("WebSocket connection failed.")
            return False

    async def disconnect(self) -> None:
        """Close active websocket connection if connected."""
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def receive(self) -> Optional[dict]:
        """Receive and parse one manager websocket payload.

        Returns:
            Parsed payload dictionary, or ``None`` when disconnected/error.
        """
        if not self._ws:
            return None
        try:
            raw = await self._ws.recv()
            return json.loads(raw)
        except websockets.ConnectionClosed:
            self._ws = None
            return None
        except Exception:
            logger.exception("Error receiving message.")
            return None

    async def send_heartbeat(self) -> None:
        """Send worker heartbeat message to manager."""
        await self._send({"type": WS_TYPE_HEARTBEAT})

    async def send_bot_status(
        self, bot_id: int, status: str
    ) -> None:
        """Report bot status transition to manager.

        Args:
            bot_id: Bot identifier.
            status: New bot status.
        """
        await self._send(
            {"type": WS_TYPE_BOT_STATUS, "bot_id": bot_id, "status": status}
        )

    async def send_bot_log(
        self,
        bot_id: int,
        message: str,
        level: str = "INFO",
        correlation_id: Optional[str] = None,
    ) -> None:
        """Send bot-scoped diagnostic log message.

        Args:
            bot_id: Bot identifier.
            message: Log message text.
            level: Log level string.
            correlation_id: Optional trace correlation id.
        """
        await self._send(
            {
                "type": WS_TYPE_BOT_LOG,
                "bot_id": bot_id,
                "message": message,
                "level": level,
                "correlation_id": correlation_id,
            }
        )

    async def send_error(
        self, bot_id: int, message: str
    ) -> None:
        """Report a bot error event to manager.

        Args:
            bot_id: Bot identifier.
            message: Error message.
        """
        await self._send(
            {"type": WS_TYPE_ERROR, "bot_id": bot_id, "message": message}
        )

    async def send_order_update(
        self, bot_id: int, order_data: dict
    ) -> None:
        """Report an order event payload to manager.

        Args:
            bot_id: Bot identifier.
            order_data: Order event fields to merge into websocket payload.
        """
        await self._send(
            {
                "type": WS_TYPE_ORDER_UPDATE,
                "bot_id": bot_id,
                **order_data,
            }
        )

    async def send_worker_log(
        self,
        message: str,
        level: str = "INFO",
        subcategory: str = "",
        correlation_id: Optional[str] = None,
    ) -> None:
        """Send worker-scoped diagnostic log message.

        Args:
            message: Log message text.
            level: Log level string.
            subcategory: Logger/category subgroup.
            correlation_id: Optional trace correlation id.
        """
        await self._send(
            {
                "type": WS_TYPE_WORKER_LOG,
                "message": message,
                "level": level,
                "subcategory": subcategory,
                "correlation_id": correlation_id,
            }
        )

    async def send_budget_snapshot(
        self,
        bot_id: int,
        balance: str,
        price: str,
    ) -> None:
        """Send a bot budget snapshot to manager.

        Args:
            bot_id: Bot identifier.
            balance: Bot mark-to-market value in quote currency.
            price: Market price used to value current holdings.
        """
        await self._send(
            {
                "type": WS_TYPE_BUDGET_SNAPSHOT,
                "bot_id": bot_id,
                "balance": balance,
                "price": price,
            }
        )

    async def _send(self, data: dict) -> None:
        """Send one JSON websocket payload to manager.

        Args:
            data: Payload dictionary.
        """
        if not self._ws:
            logger.warning("Cannot send: not connected.")
            return
        try:
            await self._ws.send(json.dumps(data))
        except websockets.ConnectionClosed:
            self._ws = None
            logger.warning("Connection lost while sending.")
        except Exception:
            logger.exception("Error sending message.")
