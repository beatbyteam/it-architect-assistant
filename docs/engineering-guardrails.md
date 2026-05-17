# Engineering guardrails

P1 вводит минимальные ограничения для модулей, которые уже однажды разрослись до уровня, опасного для сопровождения.

## Целевые ограничения

- `backend/app/integrations/generation/llm_gateway.py` — не больше 650 строк
- `backend/app/domain/services/mvp_canonical.py` — не больше 1000 строк
- `backend/app/domain/services/knowledge/update_service.py` — не больше 1100 строк
- `backend/app/domain/services/knowledge/source_service.py` — не больше 700 строк
- `backend/app/domain/services/verification/rule_engine.py` — не больше 120 строк

Проверка запускается скриптом `python backend/scripts/check_module_guardrails.py` и входит в CI.

## Правила для новых изменений

- логика оркестрации и чистые преобразования должны жить в разных модулях;
- сериализация read-model и snapshot-summary не должна оставаться внутри оркестрации сервиса;
- крупные процедуры нормализации выносятся в отдельные вспомогательные модули;
- исполнители правил не должны жить в одном файле с движком оркестрации.
