from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID


def _json_default(value: Any):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return getattr(value, "value", str(value))
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, set):
        return list(value)
    return str(value)


def json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=_json_default, ensure_ascii=False))


def freeze_snapshot(
    payload: dict[str, Any], *, snapshot_type: str, schema_version: str = "2026.03"
) -> dict[str, Any]:
    safe_payload = json_safe(payload)
    payload_bytes = json.dumps(
        safe_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    digest = hashlib.sha256(payload_bytes).hexdigest()
    safe_payload["_snapshot"] = {
        "snapshot_type": snapshot_type,
        "schema_version": schema_version,
        "payload_hash": digest,
        "immutable": True,
    }
    return safe_payload
