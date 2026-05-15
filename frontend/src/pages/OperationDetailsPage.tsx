import { useEffect, useState, type ReactNode } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { getOperationDetail } from '../shared/api/operations';
import { queryKeys } from '../shared/api/queryKeys';
import { auditEventTitle, auditMessageText, entityLabel, formatDateTime, formatSeconds, operationKindLabel, safeJson, titleStatus } from '../shared/lib/format';
import {
  activeStageOf,
  asRecord,
  knowledgeRunElapsedSeconds,
  knowledgeRunStageHint,
  metricText,
  qualitySummaryOf,
  stageElapsedSeconds,
  telemetryOf,
} from '../entities/knowledge/updateRunProgress';
import {
  generationDetailLines,
  generationRunElapsedSeconds,
  generationRunProgressLine,
  generationRunStageProgress,
  generationStageElapsedSeconds,
  generationStageHint as generationRunStageHint,
  metricText as generationMetricText,
  numberMetric as generationNumberMetric,
} from '../entities/knowledge/generationRunProgress';
import { Badge, Banner, Button, Card, CollapsibleCodeBlock, EmptyState, ErrorState, KeyValueTable, LoadingState, MetricCard, PageHeader, StateBox, TabStrip, Timeline, TimelineItem } from '../shared/ui/components';
import type { NormalizedOperationDetail, NormalizedOperationStep } from '../shared/api/normalized';
import type { AuditEvent } from '../types/api';

type OperationViewMode = 'read' | 'verify' | 'debug';

const TERMINAL_OPERATION_STATUSES = new Set(['completed', 'completed_with_warnings', 'failed', 'canceled']);

function isOperationTerminal(status?: string | null) {
  return Boolean(status && TERMINAL_OPERATION_STATUSES.has(status));
}

function renderEntityRef(key: string, value: string | null | undefined): ReactNode {
  if (!value) return '—';
  if (key === 'business_task_id') return <Link className="button" to={`/tasks/${value}`}>Открыть задачу</Link>;
  if (key === 'solution_version_id') return <Link className="button" to={`/solutions/${value}`}>Открыть решение</Link>;
  if (key === 'verification_protocol_id') return <Link className="button" to={`/protocols/${value}`}>Открыть протокол</Link>;
  return <span className="mono">{value}</span>;
}

function problemBanner(operation: NormalizedOperationDetail) {
  if (operation.status === 'failed') {
    return `Процесс завершился ошибкой${operation.last_problem_step ? ` на шаге «${titleStatus(operation.last_problem_step)}»` : ''}${operation.error_code ? `, код ${operation.error_code}` : ''}.`;
  }
  if (operation.status === 'completed_with_warnings') {
    return 'Процесс завершился с замечаниями. Проверь шаги выполнения и системные события ниже.';
  }
  return null;
}

function stepTime(step: NormalizedOperationStep) {
  if (!step.started_at && !step.finished_at) return null;
  return [
    step.started_at ? `старт: ${formatDateTime(step.started_at)}` : null,
    step.finished_at ? `завершение: ${formatDateTime(step.finished_at)}` : null,
  ].filter(Boolean).join(' · ');
}

function stepDurationSeconds(step: NormalizedOperationStep, nowMs: number) {
  if (!step.started_at) return null;
  const started = new Date(step.started_at).getTime();
  if (Number.isNaN(started)) return null;
  const finished = step.finished_at ? new Date(step.finished_at).getTime() : null;
  if ((finished == null || Number.isNaN(finished)) && step.status !== 'running') return null;
  const end = finished != null && !Number.isNaN(finished) ? finished : nowMs;
  return Math.max(0, Math.floor((end - started) / 1000));
}

function generationStepInsightLines(step: NormalizedOperationStep) {
  const payload = asRecord(step.payload);
  const lines: string[] = [];
  if (step.code === 'retrieving') {
    const coverage = asRecord(payload.coverage_summary);
    const selectedFragments = generationNumberMetric(payload, 'selected_fragment_count');
    const selectedDocuments = generationNumberMetric(payload, 'selected_document_count');
    if (selectedFragments != null || selectedDocuments != null) {
      lines.push(`подобрано фрагментов: ${selectedFragments ?? '—'} · документов: ${selectedDocuments ?? '—'}`);
    }
    if (coverage.required_roles || coverage.required_role_coverage != null) {
      lines.push(`покрытие обязательных ролей: ${generationMetricText(coverage, 'required_role_coverage')}`);
    }
  }
  if (step.code === 'prompting' || step.code === 'model_generation') {
    const tokenBudget = asRecord(payload.token_budget);
    const model = generationMetricText(payload, 'model_id');
    const provider = generationMetricText(payload, 'provider_name');
    const timeoutSec = generationNumberMetric(payload, 'timeout_sec');
    if (model !== '—' || provider !== '—') {
      lines.push([
        model !== '—' ? `модель ${model}` : null,
        provider !== '—' ? `провайдер ${provider}` : null,
        timeoutSec != null ? `таймаут ${formatSeconds(timeoutSec)}` : null,
      ].filter(Boolean).join(' · '));
    }
    const retrieved = generationNumberMetric(payload, 'retrieved_fragment_count');
    const included = generationNumberMetric(payload, 'included_fragment_count');
    const dropped = generationNumberMetric(payload, 'dropped_fragment_count');
    if (retrieved != null || included != null || dropped != null) {
      lines.push(`контекст: найдено ${retrieved ?? '—'} · вошло ${included ?? '—'} · отброшено ${dropped ?? '—'}`);
    }
    const consumed = generationNumberMetric(tokenBudget, 'consumed_input_tokens');
    const available = generationNumberMetric(tokenBudget, 'available_input_tokens');
    if (consumed != null || available != null) lines.push(`token budget: ${consumed ?? '—'} / ${available ?? '—'}`);
  }
  if (step.code === 'validating' || step.code === 'persisting' || step.code === 'publishing') {
    const quality = asRecord(payload.quality_outcomes);
    const source = Object.keys(quality).length ? quality : payload;
    const groundedness = generationNumberMetric(source, 'groundedness_score');
    const citationCoverage = generationNumberMetric(source, 'citation_coverage');
    if (groundedness != null || citationCoverage != null) {
      lines.push(`качество: groundedness ${groundedness ?? '—'} · citation coverage ${citationCoverage ?? '—'}`);
    }
  }
  return lines;
}

function operationStageHint(operation: NormalizedOperationDetail, step?: NormalizedOperationStep | null) {
  if (operation.operation_kind === 'knowledge_update_run') {
    return knowledgeRunStageHint(operation.current_stage || step?.code || operation.status);
  }
  if (operation.operation_kind === 'generation_run') {
    return generationRunStageHint(operation.current_stage || step?.code || operation.status);
  }
  return 'Процесс выполняется. Эта страница обновляется автоматически, пока операция не завершится.';
}

export function OperationDetailsPage() {
  const { operationId = '' } = useParams();
  const [viewMode, setViewMode] = useState<OperationViewMode>('read');
  const [nowMs, setNowMs] = useState(() => Date.now());
  const operationQuery = useQuery({
    queryKey: queryKeys.operationDetail(operationId),
    queryFn: ({ signal }) => getOperationDetail(operationId, { signal }),
    enabled: Boolean(operationId),
    refetchInterval: (query: { state: { data: NormalizedOperationDetail | undefined } }) => {
      const data = query.state.data;
      return data && isOperationTerminal(data.status) ? false : 2_000;
    },
  });

  useEffect(() => {
    const intervalId = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(intervalId);
  }, []);

  if (operationQuery.isLoading) return <LoadingState message="Открываю процесс…" />;
  if (operationQuery.isError || !operationQuery.data) return <ErrorState message="Не удалось загрузить процесс." />;

  const operation: NormalizedOperationDetail = operationQuery.data;
  const entityRows = Object.entries(operation.entity_refs ?? {}).map(([key, value]) => [entityLabel(key), renderEntityRef(key, typeof value === 'string' || value == null ? value : String(value))] as [string, ReactNode]);
  const showDebugBlocks = viewMode === 'debug';
  const showSystemEvents = viewMode === 'verify' || viewMode === 'debug';
  const diagnostics = asRecord(operation.diagnostics);
  const qualitySummary = asRecord(diagnostics.quality_summary);
  const knowledgeProgress = operation.operation_kind === 'knowledge_update_run' ? {
    status: operation.status,
    current_stage: operation.current_stage,
    started_at: operation.started_at,
    finished_at: operation.finished_at,
    duration_sec: operation.duration_sec,
    quality_summary: qualitySummary,
    diagnostics,
  } : null;
  const generationProgress = operation.operation_kind === 'generation_run' ? {
    state: operation.status,
    current_stage: operation.current_stage,
    started_at: operation.started_at,
    finished_at: operation.finished_at,
    diagnostics,
  } : null;
  const liveQualitySummary = knowledgeProgress ? qualitySummaryOf(knowledgeProgress) : qualitySummary;
  const activeStage = knowledgeProgress ? activeStageOf(knowledgeProgress) : {};
  const telemetry = knowledgeProgress ? telemetryOf(knowledgeProgress) : {};
  const activeDocument = String(activeStage.document_title ?? activeStage.document_name ?? '').trim();
  const runningElapsedSec = operation.duration_sec
    ?? (knowledgeProgress ? knowledgeRunElapsedSeconds(knowledgeProgress, nowMs) : null)
    ?? (generationProgress ? generationRunElapsedSeconds(generationProgress, nowMs) : null);
  const sla = asRecord(qualitySummary.sla);
  const alert = problemBanner(operation);
  const runningStep = operation.steps.find((step) => step.status === 'running') ?? null;
  const runningStepElapsedSec = !isOperationTerminal(operation.status)
    ? (generationProgress ? generationStageElapsedSeconds(generationProgress, nowMs) : stageElapsedSeconds(runningStep?.started_at, nowMs))
    : null;
  const waitingForModel = runningStep?.code === 'model_generation' || operation.current_stage === 'model_generation';
  const generationDetails = generationProgress ? generationDetailLines(generationProgress, nowMs) : [];

  return (
    <div className="stack">
      <PageHeader
        title={operationKindLabel(operation.operation_kind)}
        subtitle="Карточка процесса: статус, шаги выполнения, связанные объекты, системные события и техническая диагностика."
        actions={<Link to="/operations" className="button">Назад к журналу</Link>}
      />

      <Card title="Режим просмотра" subtitle="Технические payload и diagnostics скрыты, пока не включён дебаг.">
        <TabStrip>
          <Button type="button" primary={viewMode === 'read'} onClick={() => setViewMode('read')}>Читать</Button>
          <Button type="button" primary={viewMode === 'verify'} onClick={() => setViewMode('verify')}>Проверить ход</Button>
          <Button type="button" primary={viewMode === 'debug'} onClick={() => setViewMode('debug')}>Дебаг</Button>
        </TabStrip>
        <div className="muted small" style={{ marginTop: 8 }}>
          {viewMode === 'read' ? 'Показаны статус, длительность, связанные объекты и понятные шаги выполнения.' : null}
          {viewMode === 'verify' ? 'Добавлены системные события, чтобы проверить, что именно записала система.' : null}
          {viewMode === 'debug' ? 'Добавлены технические payload каждого шага, метрики этапов и полный diagnostics JSON.' : null}
        </div>
      </Card>

      {alert ? <Banner tone={operation.status === 'failed' ? 'danger' : 'warning'}>{alert}</Banner> : null}
      {!isOperationTerminal(operation.status) ? (
        <Banner tone="info">
          <strong>Процесс в работе: {titleStatus(operation.current_stage)}</strong>
          <div>{operationStageHint(operation, runningStep)}</div>
          {runningStepElapsedSec != null ? <div className="muted small">Текущий этап длится: {formatSeconds(runningStepElapsedSec)}</div> : null}
          {generationProgress ? <div className="muted small">{generationRunProgressLine(generationProgress, nowMs)}</div> : null}
          {generationDetails.length ? (
            <div className="muted small" style={{ marginTop: 8 }}>
              {generationDetails.map((line) => <div key={line}>{line}</div>)}
            </div>
          ) : null}
          <div className="muted small">
            Страница обновляется автоматически каждые 2 секунды. Последнее обновление данных: {formatDateTime(new Date(operationQuery.dataUpdatedAt).toISOString())}.
          </div>
          {waitingForModel ? (
            <div className="muted small">
              Если этот шаг длится долго, чаще всего система ждёт внешний LLM API или fallback-модель, а не простаивает внутри интерфейса.
            </div>
          ) : null}
        </Banner>
      ) : null}

      <div className="grid grid-2">
        <Card title="Общая информация">
          <KeyValueTable rows={[
            ['Статус', <Badge value={operation.status} />],
            ['Текущий шаг', titleStatus(operation.current_stage)],
            ['Старт', formatDateTime(operation.started_at)],
            ['Завершение', formatDateTime(operation.finished_at)],
            ['Длительность', formatSeconds(runningElapsedSec)],
            ['Текущий шаг идёт', formatSeconds(runningStepElapsedSec)],
            ['Исполнитель', operation.actor_label ?? operation.initiator_user_id ?? 'Система'],
            ['Код связи', operation.correlation_id ? <span className="mono">{operation.correlation_id}</span> : '—'],
            ['Код ошибки', operation.error_code ? <span className="mono">{operation.error_code}</span> : '—'],
            ['Проблема на шаге', titleStatus(operation.last_problem_step)],
          ]} />
          {operation.summary_text ? <StateBox className="with-top-margin">{operation.summary_text}</StateBox> : null}
        </Card>

        <Card title="Связанные объекты">
          {entityRows.length === 0 ? <EmptyState title="Связанных объектов нет" /> : <KeyValueTable rows={entityRows} />}
        </Card>
      </div>

      {generationProgress ? (
        <Card title="Метрики подготовки решения" subtitle="Живой прогресс генерации: где сейчас находится запуск и сколько длится текущий шаг.">
          <div className="grid grid-4">
            <MetricCard label="Всего прошло" value={formatSeconds(runningElapsedSec)} />
            <MetricCard label="Текущий шаг идёт" value={formatSeconds(runningStepElapsedSec)} />
            <MetricCard label="Прогресс этапов" value={generationRunStageProgress(generationProgress)} />
            <MetricCard label="Старт" value={formatDateTime(operation.started_at)} />
          </div>
          <StateBox className="with-top-margin" tone={operation.status === 'failed' ? 'danger' : 'info'}>
            <strong>Сейчас выполняется: {titleStatus(operation.current_stage)}</strong>
            <div>{generationRunStageHint(operation.current_stage)}</div>
            <div className="muted small">{generationRunProgressLine(generationProgress, nowMs)}</div>
            {generationDetails.length ? (
              <div className="muted small" style={{ marginTop: 8 }}>
                {generationDetails.map((line) => <div key={line}>{line}</div>)}
              </div>
            ) : null}
          </StateBox>
        </Card>
      ) : null}

      <Card title="Шаги выполнения">
        {operation.steps.length === 0 ? <EmptyState title="Шаги не записаны" /> : (
          <Timeline>
            {operation.steps.map((step: NormalizedOperationStep) => {
              const durationSec = stepDurationSeconds(step, nowMs);
              const insightLines = operation.operation_kind === 'generation_run'
                ? generationStepInsightLines(step)
                : [];
              return (
                <TimelineItem key={step.code} className={`timeline-item-${step.status}`}>
                  <div className="actions between">
                    <strong>{step.title}</strong>
                    <Badge value={step.status} />
                  </div>
                  {step.detail ? <div>{auditMessageText(step.detail)}</div> : null}
                  {step.error_code ? <div className="muted small">Код ошибки: <span className="mono">{step.error_code}</span></div> : null}
                  {stepTime(step) ? <div className="muted small">{stepTime(step)}</div> : null}
                  {durationSec != null ? <div className="muted small">длительность шага: {formatSeconds(durationSec)}</div> : null}
                  {insightLines.length ? (
                    <div className="muted small" style={{ marginTop: 6 }}>
                      {insightLines.map((line) => <div key={line}>{line}</div>)}
                    </div>
                  ) : null}
                  {showDebugBlocks && step.payload ? <CollapsibleCodeBlock style={{ marginTop: 8 }}>{safeJson(step.payload)}</CollapsibleCodeBlock> : null}
                </TimelineItem>
              );
            })}
          </Timeline>
        )}
      </Card>

      {operation.operation_kind === 'knowledge_update_run' ? (
        <Card title="Метрики обновления базы" subtitle="Живой прогресс обработки документов, чанков и эмбеддингов.">
          <div className="grid grid-4">
            <MetricCard label="Получено файлов" value={metricText(liveQualitySummary, 'fetched_documents')} />
            <MetricCard label="Обработано документов" value={metricText(liveQualitySummary, 'processed_documents')} />
            <MetricCard label="Чанков" value={metricText(liveQualitySummary, 'chunk_count')} />
            <MetricCard label="Эмбеддингов" value={metricText(liveQualitySummary, 'embeddings_calculated')} />
          </div>
          <div className="grid grid-4" style={{ marginTop: 12 }}>
            <MetricCard label="Переиспользовано" value={metricText(liveQualitySummary, 'reused_documents')} />
            <MetricCard label="Ошибок обработки" value={metricText(liveQualitySummary, 'processing_error_count')} />
            <MetricCard label="Профиль эмбеддингов" value={String(liveQualitySummary.requested_embedding_profile ?? telemetry.embedding_profile ?? '—')} />
            <MetricCard label="Фактическая длительность" value={formatSeconds(typeof sla.actual_sec === 'number' ? sla.actual_sec : runningElapsedSec)} />
          </div>
          {Object.keys(activeStage).length > 0 ? (
            <StateBox className="with-top-margin">
              <strong>Текущий внутренний шаг: {titleStatus(String(activeStage.stage ?? operation.current_stage ?? 'running'))}</strong>
              {activeDocument ? <div>Документ: {activeDocument}</div> : null}
              {activeStage.operation ? <div>Операция: {String(activeStage.operation)}</div> : null}
              {activeStage.embedding_batches_completed || activeStage.embedding_batches_total ? (
                <div className="muted small">Embedding batch: {metricText(activeStage, 'embedding_batches_completed')}/{metricText(activeStage, 'embedding_batches_total')}</div>
              ) : null}
            </StateBox>
          ) : null}
          {showDebugBlocks && liveQualitySummary.stage_metrics ? (
            <CollapsibleCodeBlock style={{ marginTop: 12 }}>{safeJson(liveQualitySummary.stage_metrics)}</CollapsibleCodeBlock>
          ) : null}
        </Card>
      ) : null}

      {showSystemEvents ? (
        <Card title="Системные события">
          {operation.audit_events.length === 0 ? <EmptyState title="Событий для этого процесса не найдено" /> : (
            <Timeline>
              {operation.audit_events.map((item: AuditEvent) => {
                const title = auditEventTitle(item.event_type);
                const message = auditMessageText(item.message);
                return (
                  <TimelineItem key={item.audit_event_id}>
                    <div className="actions between">
                      <strong>{title}</strong>
                      <Badge value={item.severity} />
                    </div>
                    {message !== title ? <div>{message}</div> : null}
                    <div className="muted small">{formatDateTime(item.event_time)}</div>
                  </TimelineItem>
                );
              })}
            </Timeline>
          )}
        </Card>
      ) : null}

      {showDebugBlocks ? (
        <Card title="Технические данные">
          <CollapsibleCodeBlock>{safeJson(operation.diagnostics ?? {})}</CollapsibleCodeBlock>
        </Card>
      ) : null}
    </div>
  );
}
