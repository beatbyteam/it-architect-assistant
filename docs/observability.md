# Observability and correlation context

- Структурированные JSON-логи теперь содержат идентификаторы заявки/корреляции и идентификаторы сущностей операции.
- Запуски генерации, верификации и обновления базы знаний передают метрики длительности по каждому этапу.
- Дашборд операционных метрик агрегирует наблюдаемость pipeline для процессов генерации, верификации и обновления базы знаний.

Ключевые точки полезной нагрузки:
- Генерация решения -> diagnostics.pipeline_telemetry / diagnostics.stage_metrics
- Верификация базы знаний -> diagnostics.pipeline_telemetry / diagnostics.stage_metrics
- Обновление базы знаний-> summary.quality_summary.pipeline_telemetry / stage_metrics
