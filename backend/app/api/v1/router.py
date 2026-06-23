from fastapi import APIRouter

from app.api.v1.endpoints import auth, brand, health, management, monitor

api_router = APIRouter()
api_router.include_router(health.router, tags=["System"])
api_router.include_router(auth.router, tags=["Authentication"])
api_router.include_router(management.router, tags=["Management"])
api_router.include_router(monitor.router, tags=["GEO Monitor"])
api_router.include_router(brand.router, tags=["Brand Asset"])
