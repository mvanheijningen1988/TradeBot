"""Log management service.

Sets up categorised rotating file + console handlers and exposes
a DB-backed log store for UI searching and correlation ID tracing.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from typing import Optional

from manager.config import Config
from manager.database.repositories import LogEntryRepository

logger = logging.getLogger(__name__)


class LogService:
    """Centralised log configuration and DB-backed log store."""

    def __init__(
        self, config: Config, log_repo: LogEntryRepository
    ) -> None:
        self._config = config
        self._repo = log_repo
        self._level_overrides: dict[str, str] = {}

    def setup_logging(self) -> None:
        """Configure root logger with console + rotating file handlers."""
        log_dir = self._config.log_dir
        os.makedirs(log_dir, exist_ok=True)

        root = logging.getLogger()
        root.setLevel(self._config.log_level)

        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler.
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)

        # Rotating file handler.
        file_handler = RotatingFileHandler(
            os.path.join(log_dir, "tradebot.log"),
            maxBytes=self._config.log_max_bytes,
            backupCount=self._config.log_backup_count,
        )
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)

    def set_level(self, category: str, level: str) -> None:
        """Change log level for a category without restart."""
        log = logging.getLogger(category)
        log.setLevel(level.upper())
        self._level_overrides[category] = level.upper()
        logger.info(
            "Log level for '%s' set to %s", category, level.upper()
        )

    def get_levels(self) -> dict[str, str]:
        """Return current level overrides."""
        return dict(self._level_overrides)

    async def persist(
        self,
        category: str,
        message: str,
        level: str = "INFO",
        subcategory: str = "",
        correlation_id: Optional[str] = None,
        bot_id: Optional[int] = None,
        worker_id: Optional[int] = None,
    ) -> None:
        """Write a log entry to the database for UI access."""
        await self._repo.create(
            category=category,
            message=message,
            level=level,
            subcategory=subcategory,
            correlation_id=correlation_id,
            bot_id=bot_id,
            worker_id=worker_id,
        )

    async def search(self, **filters) -> list[dict]:
        """Search persisted logs with optional filters."""
        return await self._repo.search(**filters)
