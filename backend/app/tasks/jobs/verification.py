from __future__ import annotations

try:
    from celery.utils.log import get_task_logger  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency fallback
    import logging

    def get_task_logger(name: str):
        return logging.getLogger(name)


from app.core.config import get_settings
from app.db.session import SessionLocal
from app.domain.services.verification_core import VerificationRunService
from app.tasks.workers.celery_app import ARCHITECTURE_VERIFICATION_QUEUE, celery_app

logger = get_task_logger(__name__)


@celery_app.task(
    name="app.tasks.jobs.verification.run_verification_job",
    queue=ARCHITECTURE_VERIFICATION_QUEUE,
)
def run_verification_job(verification_run_id: str) -> dict[str, str]:
    session = SessionLocal()
    try:
        service = VerificationRunService(session, get_settings())
        run = service.execute_run(verification_run_id)
        return {"verification_run_id": str(run.verification_run_id), "status": run.status.value}
    finally:
        session.close()
