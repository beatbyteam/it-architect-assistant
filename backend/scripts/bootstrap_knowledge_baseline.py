from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.bootstrap.knowledge import (  # noqa: E402
    bootstrap_knowledge_baseline,
    default_demo_knowledge_bundle_manifest_uri,
)
from app.core.config import get_settings  # noqa: E402
from app.db.enums import KnowledgeVersionStatus  # noqa: E402
from app.db.session import session_scope  # noqa: E402


def main() -> None:
    settings = get_settings()
    manifest_uri = default_demo_knowledge_bundle_manifest_uri()
    with session_scope(settings.database_url) as session:
        session.info["settings"] = settings
        result = bootstrap_knowledge_baseline(session, manifest_uri=manifest_uri)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    status = str(result.get("knowledge_version_status") or "").strip().lower()
    active_version_id = result.get("active_knowledge_version_id")
    if status != KnowledgeVersionStatus.ACTIVE.value or not active_version_id:
        raise SystemExit(
            "Knowledge bootstrap did not produce an active baseline. "
            "Check bootstrap logs and ensure the local LLM/embedding stack "
            "(for example `ollama` with the required models) is available."
        )


if __name__ == "__main__":
    main()
