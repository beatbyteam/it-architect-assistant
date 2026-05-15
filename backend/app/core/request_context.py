from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="")
correlation_id_ctx_var: ContextVar[str] = ContextVar("correlation_id", default="")
operation_kind_ctx_var: ContextVar[str] = ContextVar("operation_kind", default="")
operation_id_ctx_var: ContextVar[str] = ContextVar("operation_id", default="")
business_task_id_ctx_var: ContextVar[str] = ContextVar("business_task_id", default="")
generation_run_id_ctx_var: ContextVar[str] = ContextVar("generation_run_id", default="")
verification_run_id_ctx_var: ContextVar[str] = ContextVar("verification_run_id", default="")
knowledge_update_run_id_ctx_var: ContextVar[str] = ContextVar("knowledge_update_run_id", default="")
knowledge_version_id_ctx_var: ContextVar[str] = ContextVar("knowledge_version_id", default="")
solution_version_id_ctx_var: ContextVar[str] = ContextVar("solution_version_id", default="")
verification_protocol_id_ctx_var: ContextVar[str] = ContextVar(
    "verification_protocol_id", default=""
)

LOG_CONTEXT_VARS: dict[str, ContextVar[str]] = {
    "request_id": request_id_ctx_var,
    "correlation_id": correlation_id_ctx_var,
    "operation_kind": operation_kind_ctx_var,
    "operation_id": operation_id_ctx_var,
    "business_task_id": business_task_id_ctx_var,
    "generation_run_id": generation_run_id_ctx_var,
    "verification_run_id": verification_run_id_ctx_var,
    "knowledge_update_run_id": knowledge_update_run_id_ctx_var,
    "knowledge_version_id": knowledge_version_id_ctx_var,
    "solution_version_id": solution_version_id_ctx_var,
    "verification_protocol_id": verification_protocol_id_ctx_var,
}


def get_log_context() -> dict[str, str]:
    return {key: value for key, ctx in LOG_CONTEXT_VARS.items() if (value := ctx.get())}


@contextmanager
def bind_log_context(**values: str | None) -> Iterator[None]:
    tokens: list[tuple[ContextVar[str], Token]] = []
    try:
        for key, value in values.items():
            ctx = LOG_CONTEXT_VARS.get(key)
            if ctx is None or value is None:
                continue
            tokens.append((ctx, ctx.set(str(value))))
        yield
    finally:
        for ctx, token in reversed(tokens):
            ctx.reset(token)
