import { formatSeconds, titleStatus } from '../../shared/lib/format';

export type KnowledgeRunProgressInput = {
  status?: string | null;
  current_stage?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  duration_sec?: number | null;
  quality_summary?: Record<string, unknown> | null;
  diagnostics?: Record<string, unknown> | null;
};

const TERMINAL_STATUSES = new Set(['completed', 'completed_with_warnings', 'failed', 'canceled']);
const STAGE_ORDER = ['queued', 'loading', 'parsing', 'indexing', 'extracting', 'validating', 'active', 'completed'];

export function isKnowledgeRunTerminal(status?: string | null) {
  return Boolean(status && TERMINAL_STATUSES.has(status));
}

export function knowledgeRunStage(run?: KnowledgeRunProgressInput | null) {
  return run?.current_stage || run?.status || 'queued';
}

export function knowledgeRunStageProgress(run?: KnowledgeRunProgressInput | null) {
  const stage = knowledgeRunStage(run);
  if (stage === 'failed' || stage === 'canceled') return titleStatus(stage);
  const index = STAGE_ORDER.indexOf(stage);
  if (index < 0) return titleStatus(stage);
  return `${index + 1}/${STAGE_ORDER.length}`;
}

export function knowledgeRunStageHint(stage?: string | null) {
  switch (stage) {
    case 'queued':
    case 'created':
      return 'Задача создана и ждёт, пока worker возьмёт её из очереди.';
    case 'loading':
      return 'Система проверяет источники, регистрирует файлы и готовит список документов для обработки.';
    case 'parsing':
      return 'Документ разбирается парсером: PDF, DOCX, XLSX и другие форматы переводятся в нормальный текст.';
    case 'indexing':
      return 'Идёт нарезка на чанки и расчёт эмбеддингов. Для больших Excel это обычно самый долгий этап.';
    case 'extracting':
      return 'Система извлекает память документа: сущности, термины, правила и краткие выжимки.';
    case 'validating':
      return 'Кандидатная версия проверяется: есть ли документы, фрагменты, ошибки обработки и обязательные пакеты.';
    case 'active':
    case 'finalizing':
      return 'Новая версия знаний готовится к активации.';
    case 'completed':
    case 'completed_with_warnings':
      return 'Обновление завершилось, можно смотреть новую версию и отчёт.';
    case 'failed':
      return 'Обновление остановилось с ошибкой. Ниже должны быть этап, код и источник проблемы.';
    case 'canceled':
      return 'Обновление было остановлено до завершения.';
    default:
      return 'Обновление выполняется. Страница автоматически подтягивает новые отметки выполнения.';
  }
}

export function asRecord(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

export function qualitySummaryOf(run?: KnowledgeRunProgressInput | null) {
  return asRecord(run?.quality_summary);
}

export function activeStageOf(run?: KnowledgeRunProgressInput | null) {
  if (isKnowledgeRunTerminal(run?.status)) return {};
  return asRecord(qualitySummaryOf(run).active_stage);
}

export function telemetryOf(run?: KnowledgeRunProgressInput | null) {
  return asRecord(qualitySummaryOf(run).telemetry);
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

export function knowledgeRunElapsedSeconds(run?: KnowledgeRunProgressInput | null, nowMs = Date.now()) {
  if (!run) return null;
  if (typeof run.duration_sec === 'number' && Number.isFinite(run.duration_sec)) return run.duration_sec;
  if (isKnowledgeRunTerminal(run.status) || !run.started_at) return null;
  const started = new Date(run.started_at).getTime();
  if (Number.isNaN(started)) return null;
  return Math.max(0, Math.floor((nowMs - started) / 1000));
}

export function stageElapsedSeconds(startedAt?: string | null, nowMs = Date.now()) {
  if (!startedAt) return null;
  const started = new Date(startedAt).getTime();
  if (Number.isNaN(started)) return null;
  return Math.max(0, Math.floor((nowMs - started) / 1000));
}

export function runProgressLine(run?: KnowledgeRunProgressInput | null, nowMs = Date.now()) {
  if (!run) return 'Запуск ещё не найден в журнале.';
  const stage = knowledgeRunStage(run);
  const elapsed = knowledgeRunElapsedSeconds(run, nowMs);
  const parts = [
    `этап ${titleStatus(stage)}`,
    `прогресс ${knowledgeRunStageProgress(run)}`,
    elapsed == null ? null : `идёт ${formatSeconds(elapsed)}`,
  ].filter(Boolean);
  return parts.join(' · ');
}
