"""Application configuration.

All settings are loaded from environment variables with sensible
defaults for local development.  Secrets must be provided via env vars
in production—never hard-coded.
"""

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Config:
    """Immutable runtime configuration loaded from environment values."""

    # ── Database ─────────────────────────────────────────────────
    db_path: str = field(
        default_factory=lambda: os.getenv("TRADEBOT_DB_PATH", "tradebot.db")
    )

    # ── JWT ──────────────────────────────────────────────────────
    jwt_secret: str = field(
        default_factory=lambda: os.getenv("TRADEBOT_JWT_SECRET", "")
    )
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = field(
        default_factory=lambda: int(
            os.getenv("TRADEBOT_JWT_EXPIRE_MIN", "60")
        )
    )

    # ── Server ───────────────────────────────────────────────────
    host: str = field(
        default_factory=lambda: os.getenv("TRADEBOT_HOST", "0.0.0.0")
    )
    port: int = field(
        default_factory=lambda: int(os.getenv("TRADEBOT_PORT", "8000"))
    )

    # ── Cache TTLs (seconds) ─────────────────────────────────────
    cache_markets_ttl: int = 86400   # 24 hours
    cache_fees_ttl: int = 300        # 5 minutes

    # ── Coin icons ───────────────────────────────────────────────
    coin_map_url: str = (
        "https://raw.githubusercontent.com/ErikThiart/cryptocurrency-icons/"
        "refs/heads/master/coin_map.json"
    )

    # ── Worker health ────────────────────────────────────────────
    worker_heartbeat_timeout: int = field(
        default_factory=lambda: int(
            os.getenv("TRADEBOT_WORKER_TIMEOUT", "30")
        )
    )

    # ── Bot retry ────────────────────────────────────────────────
    bot_max_retries: int = 3

    # ── Logging ──────────────────────────────────────────────────
    log_level: str = field(
        default_factory=lambda: os.getenv("TRADEBOT_LOG_LEVEL", "INFO")
    )
    log_dir: str = field(
        default_factory=lambda: os.getenv("TRADEBOT_LOG_DIR", "logs")
    )
    log_max_bytes: int = 10 * 1024 * 1024  # 10 MB
    log_backup_count: int = 7


def load_config() -> Config:
    """Create a Config instance from the current environment."""
    cfg = Config()
    if not cfg.jwt_secret:
        import secrets
        object.__setattr__(cfg, "jwt_secret", secrets.token_hex(32))
    return cfg
