"""API package – FastAPI router registration."""

from fastapi import APIRouter

from manager.api.auth import router as auth_router
from manager.api.bots import router as bots_router
from manager.api.diagnostics import router as diag_router
from manager.api.exchanges import router as exchanges_router
from manager.api.settings import router as settings_router
from manager.api.signals import router as signals_router
from manager.api.workers import router as workers_router
from manager.api.ws import router as ws_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(bots_router)
api_router.include_router(workers_router)
api_router.include_router(exchanges_router)
api_router.include_router(settings_router)
api_router.include_router(diag_router)
api_router.include_router(signals_router)

# WebSocket routes are at root level (/ws/ui, /ws/worker).
ws_api_router = ws_router
