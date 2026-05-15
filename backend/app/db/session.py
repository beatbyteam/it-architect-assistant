from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


@lru_cache(maxsize=8)
def _get_engine(database_url: str) -> Engine:
    return create_engine(database_url, pool_pre_ping=True)


@lru_cache(maxsize=8)
def _get_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(
        bind=_get_engine(database_url), autoflush=False, autocommit=False, expire_on_commit=False
    )


def get_engine(database_url: str | None = None) -> Engine:
    resolved_database_url = database_url or get_settings().database_url
    return _get_engine(resolved_database_url)


def SessionLocal(database_url: str | None = None) -> Session:
    resolved_database_url = database_url or get_settings().database_url
    return _get_session_factory(resolved_database_url)()


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def session_scope(database_url: str | None = None) -> Generator[Session, None, None]:
    session = SessionLocal(database_url)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
