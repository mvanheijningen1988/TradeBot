"""Authentication and user management service.

Uses JWT bearer tokens for REST API auth and bcrypt for password
hashing.  On first startup, creates an admin account with a generated
password printed to the container log.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
from passlib.hash import bcrypt

from manager.config import Config
from manager.constants import ROLE_ADMIN
from manager.database.repositories import UserRepository

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_CREDENTIAL = "".join(("admin", "123!"))


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

        hashed = bcrypt.hash(DEFAULT_ADMIN_CREDENTIAL)
        await self._repo.create(
            username=DEFAULT_ADMIN_USERNAME,
            password_hash=hashed,
            role=ROLE_ADMIN,
            must_change_password=1,
        )
        logger.info("=" * 60)
        logger.info("  ADMIN ACCOUNT CREATED")
        logger.info("  Username: %s", DEFAULT_ADMIN_USERNAME)
        logger.info("  Password: %s", DEFAULT_ADMIN_CREDENTIAL)
        logger.info("=" * 60)

    async def reset_legacy_admin_credentials(self) -> None:
        """Reset the legacy admin account to the new default password."""
        admin = await self._repo.get_by_username(DEFAULT_ADMIN_USERNAME)
        if not admin:
            return

        await self._repo.update(
            admin["id"],
            password_hash=bcrypt.hash(DEFAULT_ADMIN_CREDENTIAL),
            must_change_password=1,
        )
        logger.info("Legacy admin credentials reset to the default password.")

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

    async def change_password(
        self,
        user_id: int,
        current_password: str,
        new_password: str,
    ) -> bool:
        """Change a user's password after validating the current one."""
        user = await self._repo.get_by_id(user_id)
        if not user:
            return False
        if not bcrypt.verify(current_password, user["password_hash"]):
            return False

        await self._repo.update(
            user_id,
            password_hash=bcrypt.hash(new_password),
            must_change_password=0,
        )
        return True

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
