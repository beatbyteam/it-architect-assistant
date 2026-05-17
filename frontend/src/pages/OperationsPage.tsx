import { type ChangeEvent, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { getAuditEvents, getOperationMetrics, getOperations } from '../shared/api/operations';
import { auditEventTitle, auditMessageText, formatDateTime, operationKindLabel, titleStatus } from '../shared/lib/format';
import { matchesSearch } from '../shared/lib/search';
import { Badge, Banner, Button, Card, EmptyState, ErrorNotice, Input, LoadingState, PageHeader, Select, StatCard } from '../shared/ui/components';
import type { AuditEvent, OperationItem } from '../types/api';

const OPERATIONS_LIMIT_STEP = 100;
const OPERATIONS_LIMIT_MAX = 500;
const AUDIT_LIMIT_STEP = 100;
const AUDIT_LIMIT_MAX = 500;

function countStatus(source: Record<string, number> | undefined, statuses: string[]) {
  return statuses.reduce((sum, status) => sum + (source?.[status] ?? 0), 0);
}

function queryCount(value: number | undefined, hasError: boolean) {
  return hasError ? '—' : String(value ?? 0);
}

function actorLabel(item: OperationItem) {
  return item.actor_label ?? item.initiator_user_id ?? 'Система';
}

function operationSearchParts(item: OperationItem) {
  return [
    item.operation_id,
    item.operation_kind,
    operationKindLabel(item.operation_kind),
    item.status,
    titleStatus(item.status),
    item.actor_label,
    item.initiator_user_id,
    item.error_code,
    item.last_problem_step,
    titleStatus(item.last_problem_step),
    item.current_stage,
    titleStatus(item.current_stage),
    item.correlation_id,
    item.entity_refs,
    item.diagnostics,
  ];
}

function auditSearchParts(item: AuditEvent) {
  return [
    item.event_type,
    auditEventTitle(item.event_type),
    item.message,
    auditMessageText(item.message),
    item.severity,
    titleStatus(item.severity),
    item.target_type,
    item.target_id,
    item.payload,
    item.correlation_id,
  ];
}

export function OperationsPage() {
  const [operationKind, setOperationKind] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [search, setSearch] = useState('');
  const [operationsLimit, setOperationsLimit] = useState(OPERATIONS_LIMIT_STEP);
  const [auditLimit, setAuditLimit] = useState(AUDIT_LIMIT_STEP);
  const filtersAreActive = Boolean(operationKind || statusFilter || search);
  const resetFilters = () => {
    setOperationKind('');
    setStatusFilter('');
    setSearch('');
  };

  const metricsQuery = useQuery({ queryKey: ['operation-metrics-page'], queryFn: ({ signal }) => getOperationMetrics({ signal }), staleTime: 10_000 });
  const operationsQuery = useQuery({
    queryKey: ['operation-journal', operationKind, statusFilter, operationsLimit],
    queryFn: ({ signal }) => getOperations({ limit: operationsLimit, operation_kind: operationKind || undefined, status: statusFilter || undefined }, { signal }),
    staleTime: 5_000,
  });
  const auditQuery = useQuery({ queryKey: ['audit-events', auditLimit], queryFn: ({ signal }) => getAuditEvents(auditLimit, { signal }), staleTime: 5_000 });

  const searchValue = search.trim().toLowerCase();
  const operations = useMemo(() => (operationsQuery.data ?? []).filter((item: OperationItem) => matchesSearch(operationSearchParts(item), searchValue)), [operationsQuery.data, searchValue]);
  const auditEvents = useMemo(() => (auditQuery.data ?? []).filter((item: AuditEvent) => matchesSearch(auditSearchParts(item), searchValue)), [auditQuery.data, searchValue]);

  const canLoadMoreOperations = operationsLimit < OPERATIONS_LIMIT_MAX && (operationsQuery.data?.length ?? 0) >= operationsLimit;
  const canLoadMoreAudit = auditLimit < AUDIT_LIMIT_MAX && (auditQuery.data?.length ?? 0) >= auditLimit;
  const metrics = metricsQuery.data;
  const runningCount = countStatus(metrics?.knowledge_updates.by_status, ['queued', 'pending', 'running'])
    + countStatus(metrics?.generation_runs.by_status, ['queued', 'pending', 'running'])
    + countStatus(metrics?.verification_runs.by_status, ['queued', 'pending', 'running']);
  const failedCount = countStatus(metrics?.knowledge_updates.by_status, ['failed'])
    + countStatus(metrics?.generation_runs.by_status, ['failed'])
    + countStatus(metrics?.verification_runs.by_status, ['failed']);
  const warningCount = countStatus(metrics?.knowledge_updates.by_status, ['completed_with_warnings'])
    + countStatus(metrics?.generation_runs.by_status, ['completed_with_warnings'])
    + countStatus(metrics?.verification_runs.by_status, ['completed_with_warnings']);

  return (
    <div className="stack">
      <PageHeader
        title="Журнал"
        subtitle="Процессы подготовки решений, проверки, обновления баз знаний и системные события."
      />

      <Banner tone="info">Журнал помогает понять, что сейчас выполняется, где возникла ошибка и к какой задаче, базе, решению или проверке относится процесс.</Banner>

      <div className="grid grid-4">
        <StatCard label="В работе" value={queryCount(runningCount, metricsQuery.isError)} hint="Очередь, ожидание или выполнение" />
        <StatCard label="С ошибкой" value={queryCount(failedCount, metricsQuery.isError)} hint="Требуют просмотра деталей" />
        <StatCard label="С замечаниями" value={queryCount(warningCount, metricsQuery.isError)} hint="Завершились не идеально" />
        <StatCard label="Системные события" value={queryCount(metrics?.audit_events.count, metricsQuery.isError)} hint="Записи аудита" />
      </div>
      {metricsQuery.isError ? <ErrorNotice error={metricsQuery.error} fallback="Не удалось загрузить сводку журнала." /> : null}

      <Card
        title="Фильтры"
        subtitle="Тип и статус применяются к процессам. Поиск работает и по процессам, и по системным событиям."
        actions={filtersAreActive ? <Button onClick={resetFilters}>Сбросить фильтры</Button> : null}
      >
        <div className="toolbar-grid toolbar-grid-4">
          <Select value={operationKind} onChange={(event: ChangeEvent<HTMLSelectElement>) => setOperationKind(event.target.value)}>
            <option value="">Все процессы</option>
            <option value="knowledge_update_run">Обновление базы знаний</option>
            <option value="generation_run">Подготовка решения</option>
            <option value="verification_run">Проверка решения</option>
          </Select>
          <Select value={statusFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setStatusFilter(event.target.value)}>
            <option value="">Все статусы</option>
            <option value="queued">В очереди</option>
            <option value="pending">Ожидает запуска</option>
            <option value="running">В работе</option>
            <option value="completed">Завершено</option>
            <option value="completed_with_warnings">Завершено с замечаниями</option>
            <option value="failed">Ошибка</option>
            <option value="canceled">Остановлено</option>
          </Select>
          <Input value={search} onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)} placeholder="Шаг, ошибка, исполнитель, id или код связи" />
        </div>
      </Card>

      <div className="grid grid-2">
        <Card title="Последние процессы" subtitle="Обновления баз знаний, подготовка решений и проверки." actions={<div className="actions"><span className="muted small">Загружено: {operationsQuery.data?.length ?? 0}</span>{canLoadMoreOperations ? <Button onClick={() => setOperationsLimit((current) => Math.min(OPERATIONS_LIMIT_MAX, current + OPERATIONS_LIMIT_STEP))}>Показать ещё</Button> : null}</div>}>
          {operationsQuery.isLoading ? (
            <LoadingState message="Загружаю процессы…" />
          ) : operationsQuery.isError ? (
            <ErrorNotice error={operationsQuery.error} fallback="Не удалось загрузить процессы." />
          ) : operations.length === 0 ? (
            <EmptyState title="Процессов не найдено" description="Проверьте фильтры или увеличьте лимит загрузки." />
          ) : (
            <div className="timeline">
              {operations.map((item: OperationItem) => (
                <div className="timeline-item" key={item.operation_id}>
                  <div className="actions between">
                    <strong>{operationKindLabel(item.operation_kind)}</strong>
                    <Badge value={item.status} />
                  </div>
                  <div className="muted small">Старт: {formatDateTime(item.started_at)} · длительность: {item.duration_sec == null ? '—' : `${item.duration_sec} сек`}</div>
                  <div className="muted small">Шаг: {titleStatus(item.current_stage)} · исполнитель: {actorLabel(item)}</div>
                  {item.last_problem_step ? <div className="muted small">Проблема на шаге: {titleStatus(item.last_problem_step)}</div> : null}
                  {item.error_code ? <div className="muted small">Код ошибки: {item.error_code}</div> : null}
                  {item.correlation_id ? <div className="muted small">Код связи: <span className="mono">{item.correlation_id}</span></div> : null}
                  <div className="actions">
                    <Link className="button" to={`/operations/${item.operation_id}`}>Открыть процесс</Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Последние системные события" subtitle="Короткая история действий и результатов по ключевым объектам." actions={<div className="actions"><span className="muted small">Загружено: {auditQuery.data?.length ?? 0}</span>{canLoadMoreAudit ? <Button onClick={() => setAuditLimit((current) => Math.min(AUDIT_LIMIT_MAX, current + AUDIT_LIMIT_STEP))}>Показать ещё</Button> : null}</div>}>
          {auditQuery.isLoading ? (
            <LoadingState message="Загружаю события…" />
          ) : auditQuery.isError ? (
            <ErrorNotice error={auditQuery.error} fallback="Не удалось загрузить системные события." />
          ) : auditEvents.length === 0 ? (
            <EmptyState title="Событий не найдено" description="Проверьте поиск или увеличьте лимит загрузки." />
          ) : (
            <div className="timeline">
              {auditEvents.map((item: AuditEvent) => {
                const title = auditEventTitle(item.event_type);
                const message = auditMessageText(item.message);
                return (
                  <div className="timeline-item" key={item.audit_event_id}>
                    <div className="actions between">
                      <strong>{title}</strong>
                      <Badge value={item.severity} />
                    </div>
                    {message !== title ? <div>{message}</div> : null}
                    <div className="muted small">{formatDateTime(item.event_time)}</div>
                    {item.correlation_id ? <div className="muted small">Код связи: <span className="mono">{item.correlation_id}</span></div> : null}
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
