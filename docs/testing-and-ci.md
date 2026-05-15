# Testing and CI

## Backend

Основные проверки backend в CI:

- `ruff check backend/app backend/scripts`
- `mypy` для refactored-модулей и общих contracts
- `pytest` для backend test suite
- `python backend/scripts/check_config_surface.py`
- `python backend/scripts/check_module_guardrails.py`
- `docker compose config` для единственного compose-файла
- `alembic upgrade head` на чистой pgvector-backed PostgreSQL

## Frontend

Frontend тестируется без внешней browser-specific test stack:

- `npm run lint` — zero-dependency source checks
- `npm run typecheck`
- `npm run test:unit` — route + API integration smoke tests через SSR и seeded React Query cache
- `npm run test:e2e` — app-flow smoke test на полном router tree
- `npm run build`

Такой стек не заменяет полноценный browser E2E, но даёт воспроизводимую автоматическую защиту без тяжёлых зависимостей.
