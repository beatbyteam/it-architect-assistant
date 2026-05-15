from fastapi import APIRouter

from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.knowledge import router as knowledge_router
from app.api.v1.routes.mvp import router as mvp_router
from app.api.v1.routes.operations import router as operations_router

api_router = APIRouter()


@api_router.get("", include_in_schema=False)
def api_index() -> dict[str, object]:
    return {
        "status": "ok",
        "api_version": "v1",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": {
            "live": "/api/v1/health/live",
            "ready": "/api/v1/health/ready",
        },
    }


api_router.include_router(health_router)
api_router.include_router(mvp_router)
api_router.include_router(knowledge_router)
api_router.include_router(operations_router)
