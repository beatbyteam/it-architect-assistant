from __future__ import annotations

try:
    from celery.utils.log import get_task_logger  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency fallback
    import logging

    def get_task_logger(name: str):
        return logging.getLogger(name)


from app.core.config import get_settings
from app.db.session import SessionLocal
from app.domain.services.generation_core import GenerationRunService
from app.tasks.workers.celery_app import ARCHITECTURE_GENERATION_QUEUE, celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    name="app.tasks.jobs.generation.run_generation_job",
    queue=ARCHITECTURE_GENERATION_QUEUE,
)
def run_generation_job(generation_run_id: str) -> dict[str, str]:
    session = SessionLocal()
    try:
        service = GenerationRunService(session, get_settings())
        run = service.execute_run(generation_run_id)
        return {"generation_run_id": str(run.generation_run_id), "status": run.status.value}
    finally:
        session.close()
