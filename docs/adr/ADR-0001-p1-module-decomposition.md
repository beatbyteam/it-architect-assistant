# ADR-0001 — P1 module decomposition for oversized backend services

## Status

Accepted

## Context

Перед P1 несколько ключевых модулей стали слишком крупными:

- `llm_gateway.py`
- `mvp_canonical.py`
- `knowledge/update_service.py`
- `verification/rule_engine.py`
- `knowledge/source_service.py`

Это увеличивало риск побочных эффектов и усложняло тестирование.

## Decision

В P1 приняты такие решения:

1. Логика оркестрации проверки осталась в сервисе оркестрации, а исполнители правил вынесены в `verification/rule_executors.py`.
2. Нормализация payload генерации вынесена в `integrations/generation/payload_normalization.py`.
3. Сериализация данных базы знаний вынесена в `knowledge/serializers.py`.
4. Helpers для diff и классификации ошибок при обновлении базы знаний вынесены в `knowledge/update_diffing.py`.
5. Helpers для read-model в canonical read service вынесены в `canonical_read_helpers.py`.
6. Engine получил явный protocol `VerificationRuleExecutor`, чтобы подменять executors в тестах.

## Consequences

Плюсы:

- файлы оркестрации стали короче и понятнее;
- чистые helper-модули проще тестировать отдельно;
- CI теперь может контролировать module guardrails.

Минусы:

- часть бизнес-логики всё ещё остаётся крупной, особенно в `mvp_canonical.py`, `update_service.py` и `payload_normalization.py`;
- на следующем этапе нужен ещё один проход декомпозиции по use-case слоям.