from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.deps import get_current_principal, get_settings, require_roles, require_write_access
from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.session import get_session


class _DummySession:
    pass


def _session_override() -> Generator[_DummySession, None, None]:
    yield _DummySession()


def build_auth_test_app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_session] = _session_override

    @app.exception_handler(AppError)
    async def handle_app_error(_, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status, content={"code": exc.error_code, "message": exc.message}
        )

    @app.get("/whoami")
    def whoami(principal=Depends(get_current_principal)):
        return {"login": principal.login, "roles": principal.role_codes}

    @app.post("/write")
    def write(_principal=Depends(require_write_access)):
        return {"status": "ok"}

    @app.get("/admin")
    def admin(_principal=Depends(require_roles("ADMIN"))):
        return {"status": "ok"}

    return app


def test_local_noauth_allows_requests_without_headers() -> None:
    app = build_auth_test_app(
        Settings(APP_ENV="local", AUTH_MODE="local_noauth", LOCAL_USER_ROLES="USER")
    )
    client = TestClient(app)

    response = client.get("/whoami")
    assert response.status_code == 200
    assert response.json()["login"] == "local.user"

    write_response = client.post("/write")
    assert write_response.status_code == 200


def test_trusted_headers_require_login_header() -> None:
    app = build_auth_test_app(Settings(APP_ENV="dev", AUTH_MODE="trusted_headers"))
    client = TestClient(app)

    response = client.get("/whoami")
    assert response.status_code == 401
    assert response.json()["code"] == "AUTHENTICATION_REQUIRED"


def test_trusted_headers_enforce_roles() -> None:
    app = build_auth_test_app(Settings(APP_ENV="dev", AUTH_MODE="trusted_headers"))
    client = TestClient(app)

    denied = client.get("/admin", headers={"X-Auth-Login": "alice", "X-Auth-Roles": "USER"})
    assert denied.status_code == 403
    assert denied.json()["code"] == "ACCESS_DENIED"

    allowed = client.get("/admin", headers={"X-Auth-Login": "alice", "X-Auth-Roles": "ADMIN"})
    assert allowed.status_code == 200
