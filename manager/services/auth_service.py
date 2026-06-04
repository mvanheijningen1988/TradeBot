"""Authentication and user management service.

Uses JWT bearer tokens for REST API auth and bcrypt for password
hashing.  On first startup, creates an admin account with a generated
password printed to the container log.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.hash import bcrypt

from manager.config import Config
from manager.constants import ROLE_ADMIN
from manager.database.repositories import UserRepository

logger = logging.getLogger(__name__)


class AuthService:
    """Handles authentication, token management, and user lifecycle."""

    def __init__(self, config: Config, user_repo: UserRepository) -> None:
        self._config = config
        self._repo = user_repo

    async def ensure_admin_exists(self) -> None:
        """Create the default admin account if no users exist."""
        count = await self._repo.count()
        if count > 0:
            return

        password = secrets.token_urlsafe(16)
        hashed = bcrypt.hash(password)
        await self._repo.create(
            username="admin",
            password_hash=hashed,
            role=ROLE_ADMIN,
        )
        logger.info("=" * 60)
        logger.info("  ADMIN ACCOUNT CREATED")
        logger.info("  Username: admin")
        logger.info("  Password: %s", password)
        logger.info("=" * 60)

    async def authenticate(
        self, username: str, password: str
    ) -> Optional[dict]:
        """Validate credentials and return the user dict or None."""
        user = await self._repo.get_by_username(username)
        if not user:
            return None
        if not bcrypt.verify(password, user["password_hash"]):
            return None
        return user

    def create_access_token(self, user_id: int, role: str) -> str:
        """Issue a signed JWT access token."""
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=self._config.jwt_access_token_expire_minutes
        )
        payload = {
            "sub": str(user_id),
            "role": role,
            "exp": expire,
        }
        return jwt.encode(
            payload,
            self._config.jwt_secret,
            algorithm=self._config.jwt_algorithm,
        )

    def verify_token(self, token: str) -> Optional[dict]:
        """Decode and validate a JWT token. Returns payload or None."""
        try:
            payload = jwt.decode(
                token,
                self._config.jwt_secret,
                algorithms=[self._config.jwt_algorithm],
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.debug("Token expired.")
            return None
        except jwt.InvalidTokenError:
            logger.debug("Invalid token.")
            return None
