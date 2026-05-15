from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import SessionDep, SettingsDep
from app.domain.services.health import HealthService
from app.schemas.health import DependenciesResponse, LiveResponse, ReadyResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LiveResponse)
def live(session: SessionDep, settings: SettingsDep) -> LiveResponse:
    return HealthService(session=session, settings=settings).live()


@router.get("/ready", response_model=ReadyResponse)
def ready(session: SessionDep, settings: SettingsDep, response: Response) -> ReadyResponse:
    payload = HealthService(session=session, settings=settings).ready()
    if payload.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return payload


@router.get("/dependencies", response_model=DependenciesResponse)
def dependencies(session: SessionDep, settings: SettingsDep) -> DependenciesResponse:
    return HealthService(session=session, settings=settings).dependencies()
