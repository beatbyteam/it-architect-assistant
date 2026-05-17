import { type ChangeEvent, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { archiveKnowledgeBase, createKnowledgeBase, executeScheduledKnowledgeSyncs, getKnowledgeBases, getKnowledgeNotifications, getSources } from '../shared/api/knowledge';
import { getOperationMetrics } from '../shared/api/operations';
import { formatDateTime, formatSeconds, knowledgeBaseKindLabel, sourceTypeLabel, titleStatus } from '../shared/lib/format';
import { Badge, Banner, Button, Card, EmptyState, ErrorNotice, FormRow, Input, LoadingState, PageHeader, StatCard } from '../shared/ui/components';
import type { KnowledgeBase, KnowledgeNotification, OperationMetrics, Source } from '../types/api';

function summarizeSources(sources: Source[]) {
  if (!sources.length) return 'Источники ещё не добавлены';
  return sources
    .slice(0, 3)
    .map((source) => `${source.name} (${sourceTypeLabel(source.source_type)})`)
    .join(' · ');
}

function formatOptionalStatus(value?: string | null) {
  return value ? titleStatus(value) : '—';
}

function queryValue(value: number | undefined, hasError: boolean) {
  return hasError ? '—' : String(value ?? 0);
}

const KNOWLEDGE_UPDATE_TERMINAL_STATUSES = new Set(['completed', 'completed_with_warnings', 'failed', 'canceled']);

function isKnowledgeBaseDraft(base: KnowledgeBase) {
  return !base.active_knowledge_version_id && !base.active_version_no;
}

function isKnowledgeBaseUpdating(base: KnowledgeBase) {
  return Boolean(base.latest_sync_status && !KNOWLEDGE_UPDATE_TERMINAL_STATUSES.has(base.latest_sync_status));
}

export function KnowledgePage() {
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  const basesQuery = useQuery({ queryKey: ['knowledge-bases'], queryFn: ({ signal }) => getKnowledgeBases({ signal }), staleTime: 10_000 });
  const sourcesQuery = useQuery({ queryKey: ['knowledge-sources-registry'], queryFn: ({ signal }) => getSources(undefined, { signal }), staleTime: 10_000 });
  const notificationsQuery = useQuery({ queryKey: ['knowledge-notifications'], queryFn: ({ signal }) => getKnowledgeNotifications(12, undefined, { signal }), staleTime: 5_000 });
  const metricsQuery = useQuery({ queryKey: ['operation-metrics'], queryFn: ({ signal }) => getOperationMetrics({ signal }), staleTime: 10_000 });

  const createMutation = useMutation({
    mutationFn: () => createKnowledgeBase({ name: name.trim(), description: description.trim() || null }),
    onSuccess: () => {
      setName('');
      setDescription('');
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-knowledge-bases'] });
    },
  });

  const scheduledMutation = useMutation({
    mutationFn: executeScheduledKnowledgeSyncs,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-notifications'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-sources-registry'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-knowledge-bases'] });
    },
  });

  const archiveBaseMutation = useMutation({
    mutationFn: (knowledgeBaseId: string) => archiveKnowledgeBase(knowledgeBaseId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases-selector'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-knowledge-bases'] });
    },
  });

  const sourcesByBase = useMemo(() => {
    const map = new Map<string, Source[]>();
    for (const source of (sourcesQuery.data ?? [])) {
      const list = map.get(source.knowledge_base_id) ?? [];
      list.push(source as Source);
      map.set(source.knowledge_base_id, list);
    }
    return map;
  }, [sourcesQuery.data]);

  const bases = basesQuery.data ?? [];
  const notifications = notificationsQuery.data ?? [];
  const metrics = metricsQuery.data as OperationMetrics | undefined;
  const selectedBase = bases.find((item: KnowledgeBase) => item.selected_for_generation) ?? null;
  const userBases = bases.filter((item: KnowledgeBase) => item.kind === 'user_managed');
  const updateCount = metrics?.knowledge_updates?.count ?? 0;
  const warningNotifications = notifications.filter((item: KnowledgeNotification) => item.status === 'failed' || item.status === 'completed_with_warnings').length;

  return (
    <div className="stack">
      <PageHeader
        title="Базы знаний"
        subtitle="Управление optional baseline, пользовательскими базами, источниками, версиями и ходом обновлений."
        actions={(
          <>
            <Link to="/knowledge/archive" className="button">Архив</Link>
            <Link to="/operations" className="button">Открыть журнал</Link>
          </>
        )}
      />

      {basesQuery.isLoading ? <LoadingState message="Загружаю базы знаний…" /> : null}

      {selectedBase ? (
        <Banner tone="info">
          Для подготовки решений выбрана база <strong>{selectedBase.name}</strong>.
        </Banner>
      ) : basesQuery.isError ? null : (
        <Banner tone="warning">
          База знаний для подготовки решений не выбрана. Создай пользовательскую базу с активной версией или явно выбери optional baseline.
        </Banner>
      )}

      <div className="grid grid-4">
        <StatCard label="Всего баз" value={queryValue(bases.length, basesQuery.isError)} />
        <StatCard label="Пользовательские базы" value={queryValue(userBases.length, basesQuery.isError)} />
        <StatCard label="Обновлений" value={queryValue(updateCount, metricsQuery.isError)} hint="По журналу процессов" />
        <StatCard label="Требуют внимания" value={queryValue(warningNotifications, notificationsQuery.isError)} hint="Среди последних уведомлений" />
      </div>

      <div className="grid grid-2">
        <Card title="Создать пользовательскую базу" subtitle="Для проектных, корпоративных или доменных материалов, которые должны использоваться как самостоятельная база знаний.">
          <div className="stack compact">
            <FormRow label="Название">
              <Input value={name} onChange={(event: ChangeEvent<HTMLInputElement>) => setName(event.target.value)} placeholder="Например: Материалы ERP программы" />
            </FormRow>
            <FormRow label="Описание">
              <Input value={description} onChange={(event: ChangeEvent<HTMLInputElement>) => setDescription(event.target.value)} placeholder="Что входит в базу и для каких задач она нужна" />
            </FormRow>
            {createMutation.isError ? <ErrorNotice error={createMutation.error} fallback="Не удалось создать базу знаний." /> : null}
            <div className="actions">
              <Button primary disabled={createMutation.isPending || !name.trim()} onClick={() => createMutation.mutate()}>
                {createMutation.isPending ? 'Создаю…' : 'Создать базу'}
              </Button>
            </div>
          </div>
        </Card>

        <Card title="Плановые обновления" subtitle="Запускает обновление для баз, у которых наступил срок по политике источников.">
          <div className="stack compact">
            <div>Это ручной запуск того же сценария, который выполняется планировщиком: проверка источников, обработка материалов и подготовка новой версии знаний.</div>
            {scheduledMutation.isSuccess ? (
              <Banner tone="info">Запущено: {(scheduledMutation.data?.started_knowledge_base_ids ?? []).length}, пропущено: {(scheduledMutation.data?.skipped_knowledge_base_ids ?? []).length}.</Banner>
            ) : null}
            {scheduledMutation.isError ? <ErrorNotice error={scheduledMutation.error} fallback="Не удалось запустить плановые обновления." /> : null}
            <div className="actions">
              <Button primary onClick={() => scheduledMutation.mutate()} disabled={scheduledMutation.isPending}>
                {scheduledMutation.isPending ? 'Запускаю…' : 'Запустить плановые обновления'}
              </Button>
            </div>
          </div>
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Реестр баз знаний" subtitle="Тип, выбранная версия, источники, документы и последний результат обновления.">
          {basesQuery.isError ? (
            <ErrorNotice error={basesQuery.error} fallback="Не удалось загрузить реестр баз знаний." />
          ) : bases.length === 0 && !basesQuery.isLoading ? (
            <EmptyState title="Баз знаний пока нет" />
          ) : (
            <div className="timeline">
              {bases.map((base: KnowledgeBase) => {
                const sources = sourcesByBase.get(base.knowledge_base_id) ?? [];
                const sourceSummary = sourcesQuery.isError ? 'Не удалось загрузить источники' : summarizeSources(sources);
                const hiddenSources = Math.max(0, sources.length - 3);
                return (
                  <div className="timeline-item" key={base.knowledge_base_id}>
                    <div className="actions between">
                      <strong>{base.name}</strong>
                      <div className="actions">
                        {isKnowledgeBaseDraft(base) ? <Badge value="draft" /> : null}
                        {isKnowledgeBaseUpdating(base) ? <Badge value="updating" /> : null}
                        {base.kind === 'system_mandatory' ? <Badge value="Системная" /> : null}
                        {base.kind === 'system_mandatory' ? <Badge value="Защищена" /> : null}
                        <Badge value={base.status} />
                        {base.selected_for_generation ? <Badge value="selected_for_generation" /> : null}
                      </div>
                    </div>
                    <div className="muted small">{knowledgeBaseKindLabel(base.kind)} · активная версия: {base.active_version_no ?? '—'} · версия для генерации: {base.selected_knowledge_version_no ?? 'активная'}</div>
                    {base.description ? <div>{base.description}</div> : null}
                    <div className="muted small">Источники: {sourceSummary}{hiddenSources > 0 ? ` · ещё ${hiddenSources}` : ''}</div>
                    <div className="muted small">Последнее обновление: {formatDateTime(base.latest_sync_at)} · статус: {formatOptionalStatus(base.latest_sync_status)} · ошибок: {base.last_sync_error_count ?? 0}</div>
                    <div className="muted small">Документов: {base.document_count ?? 0} · активных источников: {base.active_source_count ?? 0} · длительность: {formatSeconds(base.last_sync_duration_sec)}</div>
                    <div className="actions">
                      <Link className="button" to={`/knowledge/bases/${base.knowledge_base_id}`}>Открыть базу</Link>
                      {base.latest_sync_run_id ? <Link className="button" to={`/operations/${base.latest_sync_run_id}`}>Ход обновления</Link> : null}
                      {base.kind === 'user_managed' ? (
                        <Button
                          onClick={() => {
                            if (window.confirm(`Архивировать базу «${base.name}»? Она будет перенесена в архив и скрыта из рабочих списков.`)) {
                              archiveBaseMutation.mutate(base.knowledge_base_id);
                            }
                          }}
                          disabled={archiveBaseMutation.isPending || isKnowledgeBaseUpdating(base)}
                        >
                          Архивировать
                        </Button>
                      ) : null}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
          {archiveBaseMutation.isError ? <ErrorNotice error={archiveBaseMutation.error} fallback="Не удалось архивировать базу знаний." /> : null}
          {sourcesQuery.isError ? <ErrorNotice error={sourcesQuery.error} fallback="Не удалось загрузить источники баз знаний." /> : null}
        </Card>

        <Card title="Последние уведомления об обновлениях">
          {notificationsQuery.isLoading ? (
            <LoadingState message="Загружаю уведомления…" />
          ) : notificationsQuery.isError ? (
            <ErrorNotice error={notificationsQuery.error} fallback="Не удалось загрузить уведомления по базам знаний." />
          ) : notifications.length === 0 ? (
            <EmptyState title="Уведомлений пока нет" />
          ) : (
            <div className="timeline">
              {notifications.map((item: KnowledgeNotification) => (
                <div className="timeline-item" key={item.notification_id}>
                  <div className="actions between">
                    <strong>{item.title}</strong>
                    <Badge value={item.status} />
                  </div>
                  <div>{item.message}</div>
                  <div className="muted small">{item.knowledge_base_name} · {formatDateTime(item.created_at)}</div>
                  <div className="actions">
                    <Link className="button" to={`/knowledge/bases/${item.knowledge_base_id}`}>Открыть базу</Link>
                    <Link className="button" to={`/operations/${item.update_run_id}`}>Ход обновления</Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {metricsQuery.isError ? <ErrorNotice error={metricsQuery.error} fallback="Не удалось загрузить сводку процессов." /> : null}
    </div>
  );
}
