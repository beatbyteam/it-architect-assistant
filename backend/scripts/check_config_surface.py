from __future__ import annotations

import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import Settings  # noqa: E402

ENV_EXAMPLE = ROOT / ".env.example"
COMPOSE_FILES = [ROOT / "compose.yml"]
SETTINGS_ENV_NAMES = {field.alias or name for name, field in Settings.model_fields.items()}
NON_BACKEND_ENV_NAMES = {
    "COMPOSE_PROJECT_NAME",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "VITE_API_BASE_URL",
}


def parse_env_file(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def collect_env_from_compose(value) -> set[str]:
    if not value:
        return set()
    if isinstance(value, dict):
        return {str(key) for key in value}
    if isinstance(value, list):
        keys: set[str] = set()
        for item in value:
            if isinstance(item, str) and "=" in item:
                keys.add(item.split("=", 1)[0].strip())
        return keys
    return set()


def validate_env_example() -> list[str]:
    errors: list[str] = []
    parsed = parse_env_file(ENV_EXAMPLE)
    missing = sorted(SETTINGS_ENV_NAMES - set(parsed.keys()))
    if missing:
        errors.append(
            f"{ENV_EXAMPLE.relative_to(ROOT)} is missing settings variables: {', '.join(missing)}"
        )
    unknown = sorted(set(parsed) - SETTINGS_ENV_NAMES - NON_BACKEND_ENV_NAMES)
    if unknown:
        errors.append(
            f"{ENV_EXAMPLE.relative_to(ROOT)} has unknown variables: {', '.join(unknown)}"
        )
    return errors


def validate_compose_files() -> list[str]:
    errors: list[str] = []
    allowed_backend = SETTINGS_ENV_NAMES | NON_BACKEND_ENV_NAMES
    for path in COMPOSE_FILES:
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            errors.append(f"{path.relative_to(ROOT)} did not parse into a mapping")
            continue
        services = data.get("services", {})
        if not isinstance(services, dict):
            errors.append(f"{path.relative_to(ROOT)} services section is invalid")
            continue
        for service_name, service_def in services.items():
            env_keys = collect_env_from_compose((service_def or {}).get("environment"))
            if service_name in {"api", "worker", "knowledge-bootstrap"}:
                unknown = sorted(env_keys - allowed_backend)
                if unknown:
                    errors.append(
                        f"{path.relative_to(ROOT)} service {service_name} has unknown env vars: {', '.join(unknown)}"
                    )
    return errors


def main() -> int:
    errors = []
    errors.extend(validate_env_example())
    errors.extend(validate_compose_files())
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("config surface check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
