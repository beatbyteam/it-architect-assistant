from __future__ import annotations

__all__ = ["Base"]


def __getattr__(name: str):
    if name == "Base":
        from app.db.base import Base

        return Base
    raise AttributeError(name)
