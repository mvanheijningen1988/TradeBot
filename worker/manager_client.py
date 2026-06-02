"""Manager Node client for the Worker.

Handles REST registration and WebSocket communication with the Manager.
"""

import json
import logging
from typing import Optional

import httpx
import websockets

from manager.constants import (
    WS_TYPE_BOT_LOG,
    WS_TYPE_BOT_STATUS,
    WS_TYPE_ERROR,
    WS_TYPE_HEARTBEAT,
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
        self._manager_url = manager_url.rstrip("/")
        self._manager_ws_url = manager_ws_url
        self._agent_id = agent_id
        self._address = address
        self._version = version
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._max_retries = 5

    async def register(self) -> bool:
        """Register this worker with the Manager via REST.

        Retries with exponential backoff on network errors.
        Stops immediately on explicit rejection (403).
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

        logger.error("Registration failed after %d attempts.", self._max_retries)
        return False

    async def connect_ws(self) -> bool:
        """Establish the WebSocket connection to the Manager."""
        try:
            url = f"{self._manager_ws_url}?agent_id={self._agent_id}"
            self._ws = await websockets.connect(url)
            logger.info("WebSocket connected to manager.")
            return True
        except Exception as exc:
            logger.error("WebSocket connection failed: %s", exc)
            return False

    async def disconnect(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def receive(self) -> Optional[dict]:
        """Receive and parse a JSON message from the Manager."""
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
        """Send a heartbeat to the Manager."""
        await self._send({"type": WS_TYPE_HEARTBEAT})

    async def send_bot_status(
        self, bot_id: int, status: str
    ) -> None:
        """Report bot status change."""
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
        """Send a bot log entry to the Manager."""
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
        """Report an error for a bot."""
        await self._send(
            {"type": WS_TYPE_ERROR, "bot_id": bot_id, "message": message}
        )

    async def _send(self, data: dict) -> None:
        """Send a JSON message to the Manager."""
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
