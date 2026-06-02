"""Authentication API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from manager.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    language: str


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, request: Request):
    """Authenticate and return a JWT token."""
    auth = request.app.state.auth_service
    user = await auth.authenticate(body.username, body.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
        )
    token = auth.create_access_token(user["id"], user["role"])
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserResponse)
async def get_me(
    request: Request,
    payload: Annotated[dict, Depends(get_current_user)],
):
    """Return the current authenticated user."""
    user_repo = request.app.state.user_repo
    user = await user_repo.get_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    return UserResponse(
        id=user["id"],
        username=user["username"],
        role=user["role"],
        language=user["language"],
    )
