"""Settings and user management API endpoints."""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from passlib.hash import bcrypt
from pydantic import BaseModel

from manager.api.deps import get_current_user, require_admin

router = APIRouter(prefix="/settings", tags=["settings"])


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    language: Optional[str] = None


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"
    language: str = "en"


class UpdateLanguageRequest(BaseModel):
    language: str


@router.get("/users")
async def list_users(
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Return all users (admin only)."""
    return await request.app.state.user_repo.list_all()


@router.post("/users", status_code=201)
async def create_user(
    body: CreateUserRequest,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Create a new user (admin only)."""
    hashed = bcrypt.hash(body.password)
    user_id = await request.app.state.user_repo.create(
        username=body.username,
        password_hash=hashed,
        role=body.role,
        language=body.language,
    )
    return {"id": user_id, "username": body.username}


@router.put("/users/{user_id}")
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Update a user (admin only)."""
    updates = body.model_dump(exclude_none=True)
    if "password" in updates:
        updates["password_hash"] = bcrypt.hash(updates.pop("password"))
    await request.app.state.user_repo.update(user_id, **updates)
    return {"detail": "User updated."}


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    request: Request,
    _user: Annotated[dict, Depends(require_admin)],
):
    """Delete a user (admin only)."""
    await request.app.state.user_repo.delete(user_id)
    return {"detail": "User deleted."}


@router.put("/language")
async def update_language(
    body: UpdateLanguageRequest,
    request: Request,
    payload: Annotated[dict, Depends(get_current_user)],
):
    """Update the current user's language preference."""
    if body.language not in ("en", "nl"):
        raise HTTPException(
            status_code=400, detail="Supported languages: en, nl"
        )
    await request.app.state.user_repo.update(
        int(payload["sub"]), language=body.language
    )
    return {"detail": "Language updated."}


@router.get("/strategies")
async def list_strategies(
    request: Request,
    _user: Annotated[dict, Depends(get_current_user)],
):
    """Return available strategies and their default parameters."""
    from manager.strategies.registry import StrategyRegistry

    return StrategyRegistry.list_strategies()
