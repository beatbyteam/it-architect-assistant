from __future__ import annotations

from pathlib import Path

TARGETS = {
    "backend/app/integrations/generation/llm_gateway.py": 650,
    "backend/app/domain/services/mvp_canonical.py": 1000,
    "backend/app/domain/services/knowledge/update_service.py": 2106,
    "backend/app/domain/services/knowledge/source_service.py": 1151,
    "backend/app/domain/services/verification/rule_engine.py": 120,
}


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    violations: list[str] = []
    for relative_path, limit in TARGETS.items():
        file_path = root / relative_path
        line_count = sum(1 for _ in file_path.open("r", encoding="utf-8"))
        if line_count > limit:
            violations.append(f"{relative_path}: {line_count} lines > allowed {limit}")
    if violations:
        print("Module guardrails failed:")
        print("\n".join(violations))
        return 1
    print("Module guardrails passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
