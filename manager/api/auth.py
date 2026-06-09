"""Authentication API endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from manager.api.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Credentials payload used to request a JWT token."""

    username: str
    password: str


class TokenResponse(BaseModel):
    """Authentication response containing bearer token metadata."""

    access_token: str
    token_type: str = "bearer"
    must_change_password: bool = False


class ChangePasswordRequest(BaseModel):
    """Payload for changing the current user's password."""

    current_password: str
    new_password: str


class UserResponse(BaseModel):
    """Safe user profile payload returned for authenticated sessions."""

    id: int
    username: str
    role: str
    language: str
    time_display: str
    must_change_password: bool


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
    return TokenResponse(
        access_token=token,
        must_change_password=bool(user.get("must_change_password", 0)),
    )


@router.put("/password")
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    payload: Annotated[dict, Depends(get_current_user)],
):
    """Change the current user's password."""
    auth = request.app.state.auth_service
    changed = await auth.change_password(
        int(payload["sub"]), body.current_password, body.new_password
    )
    if not changed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is invalid.",
        )
    return {"detail": "Password updated."}


@router.get(
    "/me",
    response_model=UserResponse,
    responses={404: {"description": "Authenticated user not found."}},
)
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
        time_display=user.get("time_display", "local"),
        must_change_password=bool(user.get("must_change_password", 0)),
    )
