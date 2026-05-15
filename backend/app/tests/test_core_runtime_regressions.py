from __future__ import annotations

import logging
import sys
import types
from datetime import timedelta

import pytest

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ValidationError
from app.core.logging import configure_logging
from app.core.security import parse_account_type


class _FakeCeleryConf(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)


class _FakeCelery:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.conf = _FakeCeleryConf()

    def task(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator


class _FakeRedis:
    @classmethod
    def from_url(cls, *args, **kwargs):
        return {"url": args[0], "decode_responses": kwargs.get("decode_responses")}


sys.modules.setdefault("celery", types.SimpleNamespace(Celery=_FakeCelery))
sys.modules.setdefault("redis", types.SimpleNamespace(Redis=_FakeRedis))

from app.tasks.workers.celery_app import _scheduled_sync_interval, celery_app  # noqa: E402


def test_settings_accept_csv_lists() -> None:
    settings = Settings(
        ALLOWED_CORS_ORIGINS="http://localhost:3000,http://localhost:5173",
        LOCAL_USER_ROLES="USER,ADMIN",
    )

    assert settings.allowed_cors_origins == ["http://localhost:3000", "http://localhost:5173"]
    assert settings.local_user_roles == ["USER", "ADMIN"]


def test_settings_reject_unsupported_auth_mode() -> None:
    with pytest.raises(ValidationError, match="local_noauth, trusted_headers"):
        Settings(AUTH_MODE="legacy_dev_mode")


def test_invalid_account_type_is_mapped_to_authentication_error() -> None:
    with pytest.raises(AuthenticationError, match="Invalid authentication headers"):
        parse_account_type("robot")


def test_logging_reconfiguration_updates_root_level() -> None:
    configure_logging(Settings(LOG_LEVEL="INFO"))
    assert logging.getLogger().level == logging.INFO

    configure_logging(Settings(LOG_LEVEL="DEBUG"))
    assert logging.getLogger().level == logging.DEBUG


def test_celery_schedule_tracks_knowledge_interval_setting() -> None:
    assert _scheduled_sync_interval() == timedelta(days=30)
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.task_reject_on_worker_lost is True
