"""FastAPI dependency injection helpers.

Provides the ``get_current_user`` dependency that validates the
Authorization bearer token on every request.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

security = HTTPBearer()


async def get_current_user(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials, Depends(security)
    ],
) -> dict:
    """Validate JWT and return the authenticated user payload.

    Raises 401 if the token is missing, expired, or invalid.
    """
    auth_service = request.app.state.auth_service
    payload = auth_service.verify_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    return payload


async def require_admin(
    user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Require admin role."""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required.",
        )
    return user
