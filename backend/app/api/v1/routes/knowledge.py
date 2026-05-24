from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.routes.knowledge_bases_routes import router as bases_router
from app.api.v1.routes.knowledge_documents_routes import router as documents_router
from app.api.v1.routes.knowledge_evaluation_routes import router as evaluation_router
from app.api.v1.routes.knowledge_sources_routes import router as sources_router
from app.api.v1.routes.knowledge_update_runs_routes import router as update_runs_router
from app.api.v1.routes.knowledge_versions_routes import router as versions_router

router = APIRouter(prefix="/knowledge", tags=["Базы знаний"])
router.include_router(bases_router)
router.include_router(sources_router)
router.include_router(documents_router)
router.include_router(update_runs_router)
router.include_router(versions_router)
router.include_router(evaluation_router)
