from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any, cast

from app.core.config import get_settings

settings = get_settings()

DEFAULT_QUEUE = "default"
KNOWLEDGE_EXTRACTION_QUEUE = "knowledge_extraction"
KNOWLEDGE_VECTORIZATION_QUEUE = "knowledge_vectorization"
KNOWLEDGE_LLM_EXTRACTION_QUEUE = "knowledge_llm_extraction"
ARCHITECTURE_GENERATION_QUEUE = "architecture_generation"
ARCHITECTURE_VERIFICATION_QUEUE = "architecture_verification"


def _scheduled_sync_interval() -> timedelta:
    return timedelta(days=max(1, int(settings.knowledge_auto_sync_interval_days)))


class _FallbackInspect:
    def ping(self) -> dict[str, str]:
        raise RuntimeError("celery dependency is not installed")


class _FallbackControl:
    def inspect(self, timeout: float = 1.0) -> _FallbackInspect:
        del timeout
        return _FallbackInspect()

    def revoke(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs


class _FallbackCeleryConf(dict):
    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - defensive path
            raise AttributeError(item) from exc

    def update(self, *args: Any, **kwargs: Any) -> None:
        super().update(*args, **kwargs)


class _FallbackCelery:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.conf = _FallbackCeleryConf()
        self.control = _FallbackControl()

    def task(self, *args: Any, **kwargs: Any) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            def _delay(*f_args: Any, **f_kwargs: Any) -> Any:
                return func(*f_args, **f_kwargs)

            def _apply_async(
                args: Sequence[Any] | None = None,
                kwargs: dict[str, Any] | None = None,
                **_options: Any,
            ) -> Any:
                return func(*(args or ()), **(kwargs or {}))

            cast(Any, func).delay = _delay
            cast(Any, func).apply_async = _apply_async
            return func

        return decorator


class _FallbackRedisClient:
    def ping(self) -> bool:
        raise RuntimeError("redis dependency is not installed")


try:  # pragma: no cover - exercised via import behavior tests
    from celery import Celery as _CeleryImpl  # type: ignore[import-untyped]
except Exception:  # pragma: no cover - optional dependency
    _CeleryImpl = _FallbackCelery

_RedisImpl: Any

try:  # pragma: no cover - exercised via import behavior tests
    from redis import Redis as _RedisImpl
except Exception:  # pragma: no cover - optional dependency
    _RedisImpl = None


celery_app = _CeleryImpl(
    "it_arch_assistant_backend",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.tasks.jobs.knowledge",
        "app.tasks.jobs.generation",
        "app.tasks.jobs.verification",
    ],
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_default_queue=DEFAULT_QUEUE,
    task_create_missing_queues=True,
    task_routes={
        "app.tasks.jobs.knowledge.run_knowledge_update": {
            "queue": KNOWLEDGE_EXTRACTION_QUEUE,
        },
        "app.tasks.jobs.knowledge.run_scheduled_knowledge_syncs": {
            "queue": KNOWLEDGE_EXTRACTION_QUEUE,
        },
        "app.tasks.jobs.knowledge.extract_document": {
            "queue": KNOWLEDGE_LLM_EXTRACTION_QUEUE,
        },
        "app.tasks.jobs.knowledge.vectorize_document": {
            "queue": KNOWLEDGE_VECTORIZATION_QUEUE,
        },
        "app.tasks.jobs.generation.run_generation_job": {
            "queue": ARCHITECTURE_GENERATION_QUEUE,
        },
        "app.tasks.jobs.verification.run_verification_job": {
            "queue": ARCHITECTURE_VERIFICATION_QUEUE,
        },
    },
    task_track_started=True,
    task_always_eager=settings.celery_task_always_eager,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    beat_schedule={
        "knowledge-scheduled-sync": {
            "task": "app.tasks.jobs.knowledge.run_scheduled_knowledge_syncs",
            "schedule": _scheduled_sync_interval(),
            "options": {"queue": KNOWLEDGE_EXTRACTION_QUEUE},
        },
    },
)

redis_client = (
    _RedisImpl.from_url(settings.redis_url, decode_responses=True)
    if _RedisImpl is not None
    else _FallbackRedisClient()
)
