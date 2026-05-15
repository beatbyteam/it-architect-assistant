from __future__ import annotations

try:
    from celery.utils.log import get_task_logger  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency fallback
    import logging

    def get_task_logger(name: str):
        return logging.getLogger(name)


from app.core.config import get_settings
from app.db.session import SessionLocal
from app.domain.services.knowledge_core import KnowledgeUpdateService
from app.tasks.workers.celery_app import celery_app

logger = get_task_logger(__name__)


def _knowledge_update_time_limits() -> dict[str, int]:
    limit_sec = max(1, int(get_settings().knowledge_sync_sla_seconds or 3600))
    return {"soft_time_limit": limit_sec, "time_limit": limit_sec + 60}


@celery_app.task(
    name="app.tasks.jobs.knowledge.run_knowledge_update",
    **_knowledge_update_time_limits(),
)
def run_knowledge_update(update_run_id: str) -> dict[str, str]:
    session = SessionLocal()
    try:
        service = KnowledgeUpdateService(session, get_settings())
        run = service.execute_run(update_run_id)
        return {"update_run_id": str(run.update_run_id), "status": run.status.value}
    finally:
        session.close()


@celery_app.task(name="app.tasks.jobs.knowledge.run_scheduled_knowledge_syncs")
def run_scheduled_knowledge_syncs() -> dict[str, object]:
    session = SessionLocal()
    try:
        service = KnowledgeUpdateService(session, get_settings())
        return service.run_due_scheduled_syncs(execute_inline=False)
    finally:
        session.close()
