from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient

from app.api.deps import get_settings
from app.core.config import Settings
from app.db.session import get_session
from app.main import create_app


class _DummySession:
    pass


def _session_override() -> Generator[_DummySession, None, None]:
    yield _DummySession()


def test_request_validation_errors_expose_field_level_details() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: Settings(
        APP_ENV="local",
        AUTH_MODE="local_noauth",
        LOCAL_USER_ROLES="USER",
    )
    app.dependency_overrides[get_session] = _session_override
    client = TestClient(app)

    response = client.post("/api/v1/tasks", json={})

    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "REQUEST_VALIDATION_ERROR"
    assert payload["user_message"] == "Request validation failed"
    assert payload["details"]["errors"]
    first_error = payload["details"]["errors"][0]
    assert first_error["loc"] == ["body", "raw_text"]
    assert first_error["msg"] == "Field required"
