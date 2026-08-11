from fastapi import APIRouter

from app.api.routes import auth, catalog, export, health, stats, sync, transactions

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(catalog.router)
api_router.include_router(transactions.router)
api_router.include_router(stats.router)
api_router.include_router(sync.router)
api_router.include_router(export.router)

__all__ = ["api_router"]
