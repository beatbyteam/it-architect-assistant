from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.tasks.workers.celery_app import celery_app, redis_client  # noqa: E402


def main() -> int:
    try:
        redis_client.ping()
    except Exception:
        return 1
    try:
        reply = celery_app.control.inspect(timeout=1.0).ping() or {}
    except Exception:
        return 1
    return 0 if reply else 1


if __name__ == "__main__":
    raise SystemExit(main())
