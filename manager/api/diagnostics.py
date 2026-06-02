"""Diagnostics API endpoints.

Provides system stats, log access, and log level management.
"""

import os
import platform
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from manager.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


class SetLogLevelRequest(BaseModel):
    category: str
    level: str


@router.get("/stats")
async def get_stats(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return system resource statistics."""
    try:
        import psutil

        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        return {
            "cpu_percent": cpu,
            "memory_total": mem.total,
            "memory_available": mem.available,
            "memory_percent": mem.percent,
            "platform": platform.platform(),
            "python": platform.python_version(),
        }
    except ImportError:
        return {
            "cpu_percent": None,
            "memory_total": None,
            "memory_available": None,
            "memory_percent": None,
            "platform": platform.platform(),
            "python": platform.python_version(),
            "note": "Install psutil for full diagnostics.",
        }


@router.get("/logs")
async def get_logs(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
    category: Optional[str] = None,
    correlation_id: Optional[str] = None,
    bot_id: Optional[int] = None,
    worker_id: Optional[int] = None,
    level: Optional[str] = None,
    limit: int = 200,
):
    """Search persisted log entries."""
    return await request.app.state.log_service.search(
        category=category,
        correlation_id=correlation_id,
        bot_id=bot_id,
        worker_id=worker_id,
        level=level,
        limit=limit,
    )


@router.post("/log-level")
async def set_log_level(
    body: SetLogLevelRequest,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Change log level for a category without restart."""
    request.app.state.log_service.set_level(body.category, body.level)
    return {"detail": f"Log level for '{body.category}' set to '{body.level}'."}


@router.get("/log-levels")
async def get_log_levels(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return current log level overrides."""
    return request.app.state.log_service.get_levels()
