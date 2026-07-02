from fastapi import APIRouter

from app.api.v1.endpoints import auth, brand, health, knowledge, management, monitor, notifications
from app.api.v1.endpoints import ops as ops_endpoints
from app.api.v1.endpoints import diagnosis as diagnosis_endpoints
from app.api.v1.endpoints import analytics as analytics_endpoints
from app.api.v1.endpoints import reports as reports_endpoints
from app.api.v1.endpoints import lead_diagnosis as lead_diagnosis_endpoints
from app.api.v1.endpoints.platforms import router as platforms_router, alert_router as alerts_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["System"])
api_router.include_router(auth.router, tags=["Authentication"])
api_router.include_router(management.router, tags=["Management"])
api_router.include_router(monitor.router, tags=["GEO Monitor"])
api_router.include_router(brand.router, tags=["Brand Asset"])
api_router.include_router(knowledge.router, tags=["Knowledge File"])
api_router.include_router(ops_endpoints.router, tags=["Operations & Config"])
api_router.include_router(diagnosis_endpoints.router, tags=["Brand Diagnosis"])
api_router.include_router(analytics_endpoints.router, tags=["Analytics"])
api_router.include_router(reports_endpoints.router, tags=["Reports"])
api_router.include_router(lead_diagnosis_endpoints.router, tags=["Lead Diagnosis"])
api_router.include_router(notifications.router, tags=["Notifications"])
api_router.include_router(platforms_router, tags=["Platforms"])
api_router.include_router(alerts_router, tags=["Alert Thresholds"])
