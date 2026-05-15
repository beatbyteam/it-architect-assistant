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

1. `verification/rule_engine.py` оставляет только orchestration, а rule executors вынесены в `verification/rule_executors.py`.
2. generation payload normalization вынесен в `integrations/generation/payload_normalization.py`.
3. knowledge serialization вынесена в `knowledge/serializers.py`.
4. diff/error-classification helpers knowledge update вынесены в `knowledge/update_diffing.py`.
5. read-model helpers canonical read service вынесены в `canonical_read_helpers.py`.
6. engine получает явный `VerificationRuleExecutor` protocol для подмены executors в тестах.

## Consequences

Плюсы:

- orchestration-файлы стали короче и понятнее;
- чистые helper-модули проще тестировать отдельно;
- CI теперь может контролировать module guardrails.

Минусы:

- часть бизнес-логики всё ещё остаётся крупной, особенно в `mvp_canonical.py`, `update_service.py` и `payload_normalization.py`;
- для следующего этапа нужен ещё один проход decomposition по use-case слоям.
