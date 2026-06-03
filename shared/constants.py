"""Application-wide constants shared between manager and worker."""

# ── Bot statuses ─────────────────────────────────────────────────
BOT_STATUS_STOPPED = "stopped"
BOT_STATUS_ASSIGNING = "assigning"
BOT_STATUS_INITIALIZING = "initializing"
BOT_STATUS_RUNNING = "running"
BOT_STATUS_FAULT = "fault"

BOT_STATUSES = [
    BOT_STATUS_STOPPED,
    BOT_STATUS_ASSIGNING,
    BOT_STATUS_INITIALIZING,
    BOT_STATUS_RUNNING,
    BOT_STATUS_FAULT,
]

# ── Worker statuses ──────────────────────────────────────────────
WORKER_STATUS_PENDING = "pending"
WORKER_STATUS_APPROVED = "approved"
WORKER_STATUS_REJECTED = "rejected"
WORKER_STATUS_ONLINE = "online"
WORKER_STATUS_UNRESPONSIVE = "unresponsive"

# ── Profit modes ─────────────────────────────────────────────────
PROFIT_MODE_WITHDRAW = "withdraw"
PROFIT_MODE_COMPOUND = "compound"
PROFIT_MODE_SKIM = "skim"

PROFIT_MODES = [PROFIT_MODE_WITHDRAW, PROFIT_MODE_COMPOUND, PROFIT_MODE_SKIM]

# ── User roles ───────────────────────────────────────────────────
ROLE_ADMIN = "admin"
ROLE_USER = "user"

# ── WebSocket message types ──────────────────────────────────────
WS_TYPE_COMMAND = "command"
WS_TYPE_STATUS = "status"
WS_TYPE_LOG = "log"
WS_TYPE_HEARTBEAT = "heartbeat"
WS_TYPE_ASSIGN = "assign_bot"
WS_TYPE_START_BOT = "start_bot"
WS_TYPE_STOP_BOT = "stop_bot"
WS_TYPE_BOT_STATUS = "bot_status"
WS_TYPE_BOT_LOG = "bot_log"
WS_TYPE_WORKER_LOG = "worker_log"
WS_TYPE_ERROR = "error"
WS_TYPE_WORKER_REGISTERED = "worker_registered"
WS_TYPE_WORKER_STATUS = "worker_status"
WS_TYPE_ALERT = "alert"

# ── Supported languages ─────────────────────────────────────────
LANG_EN = "en"
LANG_NL = "nl"
DEFAULT_LANGUAGE = LANG_EN
