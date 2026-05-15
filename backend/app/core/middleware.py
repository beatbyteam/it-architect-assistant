from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from fastapi import Request, Response

from app.core.config import Settings
from app.core.request_context import request_id_ctx_var


async def request_context_middleware(request: Request, call_next) -> Response:
    settings: Settings = request.app.state.settings
    request_id = request.headers.get(settings.request_id_header, str(uuid4()))
    token = request_id_ctx_var.set(request_id)
    started = perf_counter()
    try:
        response = await call_next(request)
    finally:
        request_id_ctx_var.reset(token)
    response.headers[settings.request_id_header] = request_id
    response.headers["X-Process-Time-Ms"] = f"{(perf_counter() - started) * 1000:.2f}"
    return response
