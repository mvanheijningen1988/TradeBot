"""Worker management API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from manager.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/workers", tags=["workers"])


class RegisterWorkerRequest(BaseModel):
    """Payload sent by worker nodes when registering with a manager."""

    agent_id: str
    address: str
    version: str = ""


@router.get("")
async def list_workers(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return all registered workers."""
    return await request.app.state.worker_service.list_workers()


@router.post("/register", status_code=201)
async def register_worker(
    body: RegisterWorkerRequest,
    request: Request,
):
    """Register a new Worker Node (called by the worker itself)."""
    try:
        return await request.app.state.worker_service.register(
            agent_id=body.agent_id,
            address=body.address,
            version=body.version,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/{worker_id}/approve")
async def approve_worker(
    worker_id: int,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Approve a pending worker."""
    await request.app.state.worker_service.approve(worker_id)
    return {"detail": "Worker approved."}


@router.post("/{worker_id}/reject")
async def reject_worker(
    worker_id: int,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Reject a pending worker."""
    await request.app.state.worker_service.reject(worker_id)
    return {"detail": "Worker rejected."}


@router.delete("/{worker_id}")
async def delete_worker(
    worker_id: int,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Remove a worker and stop its bots."""
    await request.app.state.worker_service.remove(worker_id)
    return {"detail": "Worker removed."}
