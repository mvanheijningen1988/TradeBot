"""Log management service.

Sets up categorised rotating file + console handlers and exposes
a DB-backed log store for UI searching and correlation ID tracing.
"""

import logging
import os
import asyncio
from logging.handlers import RotatingFileHandler
from typing import Optional

from manager.config import Config
from manager.database.repositories import LogEntryRepository

logger = logging.getLogger(__name__)


class _DiagnosticsDbHandler(logging.Handler):
    """Persist selected log records to diagnostics DB asynchronously."""

    def __init__(self, service: "LogService") -> None:
        super().__init__()
        self._service = service

    def emit(self, record: logging.LogRecord) -> None:
        """Forward selected log records to the async diagnostics pipeline."""
        if record.name.startswith("manager.services.log_service"):
            return

        category = self._categorize(record.name)
        level = record.levelname.upper()
        if not self._service.should_log(category, level):
            return

        try:
            message = record.getMessage()
        except Exception:
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        loop.create_task(
            self._service.persist(
                category=category,
                message=message,
                level=level,
                subcategory=record.name,
            )
        )

    @staticmethod
    def _categorize(logger_name: str) -> str:
        if logger_name.startswith("worker"):
            return "worker"
        if logger_name.startswith("bot"):
            return "bot"
        return "manager"


class LogService:
    """Centralised log configuration and DB-backed log store."""

    def __init__(
        self, config: Config, log_repo: LogEntryRepository
    ) -> None:
        self._config = config
        self._repo = log_repo
        self._level_overrides: dict[str, str] = {"*": "INFO"}
        self._db_handler: Optional[logging.Handler] = None

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

    def attach_diagnostics_stream_handler(self) -> None:
        """Mirror regular logger output into diagnostics DB."""
        if self._db_handler is not None:
            return

        root = logging.getLogger()
        handler = _DiagnosticsDbHandler(self)
        root.addHandler(handler)
        self._db_handler = handler

    def set_level(self, category: str, level: str) -> None:
        """Change log level for a category without restart."""
        log = logging.getLogger(category if category != "*" else "")
        log.setLevel(level.upper())
        self._level_overrides[category] = level.upper()
        logger.info(
            "Log level for '%s' set to %s", category, level.upper()
        )

    def get_levels(self) -> dict[str, str]:
        """Return current level overrides."""
        return dict(self._level_overrides)

    def remove_level(self, category: str) -> bool:
        """Remove a log level override. Returns False if not found or is *."""
        if category == "*" or category not in self._level_overrides:
            return False
        del self._level_overrides[category]
        logging.getLogger(category).setLevel(logging.NOTSET)
        logger.info("Log level override for '%s' removed.", category)
        return True

    def should_log(self, category: str, level: str) -> bool:
        """Check whether a message should be persisted based on overrides."""
        levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        threshold = self._level_overrides.get(
            category, self._level_overrides.get("*", "INFO")
        ).upper()
        try:
            return levels.index(level.upper()) >= levels.index(threshold)
        except ValueError:
            return True

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
