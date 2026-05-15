import { formatDateTime, formatSeconds, titleStatus } from '../../shared/lib/format';

export type GenerationRunProgressInput = {
  state?: string | null;
  status?: string | null;
  current_stage?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  diagnostics?: Record<string, unknown> | null;
};

const TERMINAL_STATUSES = new Set(['completed', 'completed_with_warnings', 'failed', 'canceled']);
const STAGE_ORDER = ['queued', 'retrieving', 'prompting', 'model_generation', 'validating', 'persisting', 'publishing', 'completed'];

export function isGenerationRunTerminal(status?: string | null) {
  return Boolean(status && TERMINAL_STATUSES.has(status));
}

export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function numberMetric(record: Record<string, unknown>, key: string) {
  const value = record[key];
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return null;
}

export function metricText(record: Record<string, unknown>, key: string) {
  const value = record[key];
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  if (typeof value === 'string' && value.trim()) return value;
  return '—';
}

export function generationRunStage(run?: GenerationRunProgressInput | null) {
  return run?.current_stage || run?.status || run?.state || 'queued';
}

export function generationRunStageProgress(run?: GenerationRunProgressInput | null) {
  const stage = generationRunStage(run);
  if (stage === 'failed' || stage === 'canceled') return titleStatus(stage);
  const index = STAGE_ORDER.indexOf(stage);
  if (index < 0) return titleStatus(stage);
  return `${index + 1}/${STAGE_ORDER.length}`;
}

export function generationRunElapsedSeconds(run?: GenerationRunProgressInput | null, nowMs = Date.now()) {
  if (!run?.started_at) return null;
  const started = new Date(run.started_at).getTime();
  if (Number.isNaN(started)) return null;
  const finished = run.finished_at ? new Date(run.finished_at).getTime() : nowMs;
  const end = Number.isNaN(finished) ? nowMs : finished;
  return Math.max(0, Math.floor((end - started) / 1000));
}

export function generationActiveStage(run?: GenerationRunProgressInput | null) {
  return asRecord(asRecord(run?.diagnostics).active_stage);
}

export function latestStageEvent(run?: GenerationRunProgressInput | null) {
  const stage = generationRunStage(run);
  const history = asRecord(run?.diagnostics).stage_history;
  if (!Array.isArray(history)) return {};
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const item = asRecord(history[index]);
    if (item.stage === stage) return item;
  }
  return asRecord(history[history.length - 1]);
}

export function generationStageElapsedSeconds(run?: GenerationRunProgressInput | null, nowMs = Date.now()) {
  const activeStage = generationActiveStage(run);
  const activeUpdatedAt = typeof activeStage.updated_at === 'string' ? activeStage.updated_at : null;
  const event = latestStageEvent(run);
  const eventTimestamp = typeof event.timestamp === 'string' ? event.timestamp : null;
  const startedAt = activeUpdatedAt || eventTimestamp || run?.started_at;
  if (!startedAt || isGenerationRunTerminal(run?.state ?? run?.status)) return null;
  const started = new Date(startedAt).getTime();
  if (Number.isNaN(started)) return null;
  return Math.max(0, Math.floor((nowMs - started) / 1000));
}

export function generationStageHint(stage?: string | null) {
  switch (stage) {
    case 'queued':
      return 'Запуск создан и ждёт, пока worker возьмёт его из очереди.';
    case 'retrieving':
      return 'Система ищет релевантные фрагменты в зафиксированной версии базы знаний.';
    case 'prompting':
      return 'Собирается grounded prompt: задача, контекст, найденные фрагменты и план разделов.';
    case 'model_generation':
      return 'Запрос уже отправлен в LLM. Долгая пауза обычно означает ожидание ответа модели или загрузку локальной модели в Ollama.';
    case 'validating':
      return 'Ответ модели получен, проверяется JSON-структура, качество разделов и ссылки на источники.';
    case 'persisting':
      return 'Проверенный результат записывается как версия решения.';
    case 'publishing':
      return 'Готовится опубликованная страница решения для просмотра.';
    case 'completed':
    case 'completed_with_warnings':
      return 'Подготовка завершена, решение можно открыть.';
    case 'failed':
      return 'Подготовка остановилась с ошибкой. Подробности видны в проблемном шаге и diagnostics.';
    case 'canceled':
      return 'Подготовка была остановлена до завершения.';
    default:
      return 'Подготовка выполняется. Страница автоматически подтягивает свежие отметки процесса.';
  }
}

export function generationDetailLines(run?: GenerationRunProgressInput | null, nowMs = Date.now()) {
  if (!run) return [];
  const diagnostics = asRecord(run.diagnostics);
  const activeStage = generationActiveStage(run);
  const prompt = asRecord(diagnostics.prompt);
  const tokenBudget = asRecord(activeStage.token_budget ?? prompt.token_budget);
  const llmTelemetry = asRecord(diagnostics.llm_telemetry);
  const lines: string[] = [];
  const message = typeof activeStage.message === 'string' ? activeStage.message.trim() : '';
  if (message) lines.push(message);

  const provider = metricText(activeStage, 'provider_name');
  const model = metricText(activeStage, 'model_id');
  if (model !== '—' || provider !== '—') {
    const timeout = numberMetric(activeStage, 'timeout_sec');
    lines.push([
      model !== '—' ? `модель ${model}` : null,
      provider !== '—' ? `провайдер ${provider}` : null,
      timeout != null ? `таймаут ${formatSeconds(timeout)}` : null,
    ].filter(Boolean).join(' · '));
  }

  const retrieved = numberMetric(activeStage, 'retrieved_fragment_count');
  const included = numberMetric(activeStage, 'included_fragment_count');
  const dropped = numberMetric(activeStage, 'dropped_fragment_count');
  if (retrieved != null || included != null || dropped != null) {
    lines.push([
      retrieved != null ? `найдено фрагментов: ${retrieved}` : null,
      included != null ? `в промпт вошло: ${included}` : null,
      dropped != null ? `отброшено по бюджету: ${dropped}` : null,
    ].filter(Boolean).join(' · '));
  }

  const consumed = numberMetric(tokenBudget, 'consumed_input_tokens');
  const available = numberMetric(tokenBudget, 'available_input_tokens');
  if (consumed != null || available != null) {
    lines.push(`token budget: ${consumed ?? '—'} / ${available ?? '—'}`);
  }

  const latencyMs = numberMetric(llmTelemetry, 'latency_ms');
  if (latencyMs != null) {
    lines.push(`последний ответ LLM занял ${formatSeconds(Math.round(latencyMs / 1000))}`);
  }
  if (llmTelemetry.fallback_used === true) {
    lines.push('LLM fallback был использован для этого запуска.');
  }

  const elapsed = generationStageElapsedSeconds(run, nowMs);
  if (elapsed != null && !isGenerationRunTerminal(run.state ?? run.status)) {
    lines.push(`текущий шаг длится ${formatSeconds(elapsed)}`);
  }
  return lines;
}

export function generationRunProgressLine(run?: GenerationRunProgressInput | null, nowMs = Date.now()) {
  if (!run) return 'Запуск ещё не найден.';
  const elapsed = generationRunElapsedSeconds(run, nowMs);
  const parts = [
    `этап ${titleStatus(generationRunStage(run))}`,
    `прогресс ${generationRunStageProgress(run)}`,
    elapsed == null ? null : `идёт ${formatSeconds(elapsed)}`,
    run.started_at ? `старт ${formatDateTime(run.started_at)}` : null,
  ].filter(Boolean);
  return parts.join(' · ');
}
