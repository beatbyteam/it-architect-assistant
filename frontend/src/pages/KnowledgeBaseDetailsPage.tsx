import { type ChangeEvent, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  activateKnowledgeVersion,
  archiveSource,
  createSource,
  disableSource,
  getKnowledgeBase,
  getKnowledgeBaseDocuments,
  getKnowledgeNotifications,
  getKnowledgeVersions,
  getSources,
  getUpdateRunStatus,
  getUpdateRuns,
  removeKnowledgeDocument,
  selectKnowledgeBase,
  syncKnowledgeBase,
  updateSource,
  uploadAndIngestKnowledgeFiles,
} from '../shared/api/knowledge';
import { getTasks } from '../shared/api/tasks';
import { formatDateTime, formatSeconds, knowledgeBaseKindLabel, refreshPolicyLabel, sourceTypeLabel, titleStatus } from '../shared/lib/format';
import { GENERATION_SELECTION_LOCK_REASON, hasRunningGeneration } from '../entities/knowledge/generationSelectionLock';
import { KNOWLEDGE_REFRESH_POLICY_OPTIONS, allowedSourceStatuses, selectableKnowledgeVersions } from '../entities/knowledge/policies';
import {
  activeStageOf,
  isKnowledgeRunTerminal,
  knowledgeRunElapsedSeconds,
  knowledgeRunStage,
  knowledgeRunStageHint,
  knowledgeRunStageProgress,
  metricText,
  qualitySummaryOf,
  runProgressLine,
  stageElapsedSeconds,
} from '../entities/knowledge/updateRunProgress';
import { Badge, Banner, Button, Card, EmptyState, ErrorNotice, FormRow, Input, LoadingState, MetricCard, PageHeader, Select } from '../shared/ui/components';
import type { KnowledgeBase, KnowledgeBaseDocument, KnowledgeNotification, KnowledgeUpdateRun, KnowledgeVersion, Source } from '../types/api';

type SourceDraft = { refresh_policy: string; status: string };
type KnowledgeBaseDocumentWithProcessing = KnowledgeBaseDocument & {
  processing_status?: string | null;
  processing_error_code?: string | null;
  processing_error_message?: string | null;
};

const DASHBOARD_KNOWLEDGE_BASES_KEY = ['dashboard-knowledge-bases'] as const;
const FINAL_DOCUMENT_PROCESSING_STATUSES = new Set(['extracted', 'reused', 'skipped']);
const DEFAULT_UPLOAD_SOURCE_DRAFT: SourceDraft = { refresh_policy: 'manual', status: 'active' };
const ACTIVE_STAGE_OPERATION_LABELS: Record<string, string> = {
  chunking_prepared: 'Подготовка чанков',
  embedding: 'Расчёт эмбеддингов',
  document_memory_start: 'Подготовка извлечения памяти',
  document_memory_llm: 'LLM-извлечение памяти',
  user_cancel: 'Остановлено пользователем',
};

function isKnowledgeRunInProgress(run?: KnowledgeUpdateRun | null) {
  return Boolean(run && !isKnowledgeRunTerminal(run.status));
}

function toSourceDraft(source: Source): SourceDraft {
  return {
    refresh_policy: source.refresh_policy ?? 'monthly',
    status: source.status ?? 'draft',
  };
}

function documentLifecycleStatus(document: KnowledgeBaseDocumentWithProcessing) {
  if (document.present_in_version === false || document.delta_kind === 'deleted') return 'deleted';
  if (document.document_status === 'archived') return 'deleted';
  const processingStatus = document.processing_status ?? null;
  if (document.processing_error_code === 'CANCELED_BY_USER') return 'canceled';
  if (processingStatus === 'failed') return 'failed';
  if (processingStatus && !FINAL_DOCUMENT_PROCESSING_STATUSES.has(processingStatus)) return 'running';
  if (processingStatus === 'extracted' || processingStatus === 'reused') return 'parsed';
  return document.document_status ?? null;
}

function isRemovedFromKnowledgeBase(document: KnowledgeBaseDocument) {
  return (
    document.present_in_version === false
    || document.delta_kind === 'deleted'
    || document.document_status === 'archived'
  );
}

function progressDetail(record: Record<string, unknown>, completedKey: string, totalKey: string, label: string) {
  const completed = metricText(record, completedKey);
  const total = metricText(record, totalKey);
  return completed !== '—' && total !== '—' ? `${label} ${completed}/${total}` : null;
}

function runActiveStageDetails(run?: KnowledgeUpdateRun | null, nowMs = Date.now()) {
  if (!run) return [];
  const activeStage = activeStageOf(run);
  const currentStage = knowledgeRunStage(run);
  const activeStageName = String(activeStage.stage ?? '').trim();
  const operation = String(activeStage.operation ?? '').trim();
  const documentTitle = String(activeStage.document_title ?? activeStage.document_name ?? '').trim();
  const updatedAt = typeof activeStage.updated_at === 'string' ? activeStage.updated_at : null;
  const lines: string[] = [];

  if (documentTitle) lines.push(`Документ: ${documentTitle}`);
  if (operation) lines.push(`Операция: ${ACTIVE_STAGE_OPERATION_LABELS[operation] ?? operation}`);
  if (activeStageName && activeStageName !== currentStage) {
    lines.push(`Последняя подробная отметка: ${titleStatus(activeStageName)}`);
  }

  const embeddingProgress = progressDetail(activeStage, 'embedding_batches_completed', 'embedding_batches_total', 'embedding batch');
  if (embeddingProgress) lines.push(embeddingProgress);
  const llmProgress = progressDetail(activeStage, 'llm_batches_completed', 'llm_batches_total', 'LLM batch');
  if (llmProgress) lines.push(llmProgress);

  const chunks = metricText(activeStage, 'current_document_chunk_count');
  if (chunks !== '—') lines.push(`Чанков в документе: ${chunks}`);
  const embeddingCount = metricText(activeStage, 'embedding_count');
  if (embeddingCount !== '—') lines.push(`Эмбеддингов готово: ${embeddingCount}`);

  const elapsed = stageElapsedSeconds(updatedAt, nowMs);
  if (elapsed != null && !isKnowledgeRunTerminal(run.status)) {
    lines.push(`Детальная отметка обновлена ${formatSeconds(elapsed)} назад`);
  }
  if (!lines.length && currentStage === 'extracting' && !isKnowledgeRunTerminal(run.status)) {
    lines.push('LLM извлекает память документа; на локальной модели это может занимать минуты.');
  }
  return lines.slice(0, 6);
}

export function KnowledgeBaseDetailsPage() {
  const { knowledgeBaseId = '' } = useParams();
  const queryClient = useQueryClient();
  const [generationVersionId, setGenerationVersionId] = useState('');
  const [generationVersionDirty, setGenerationVersionDirty] = useState(false);
  const [documentViewVersionId, setDocumentViewVersionId] = useState('');
  const [newSourceName, setNewSourceName] = useState('');
  const [newSourceUri, setNewSourceUri] = useState('');
  const newSourceType = 'url';
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, SourceDraft>>({});
  const [dirtySourceIds, setDirtySourceIds] = useState<Record<string, boolean>>({});
  const [uploadTitle, setUploadTitle] = useState('');
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [uploadSourceDefaults, setUploadSourceDefaults] = useState<SourceDraft>(DEFAULT_UPLOAD_SOURCE_DRAFT);
  const [uploadRunId, setUploadRunId] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const baseQuery = useQuery({
    queryKey: ['knowledge-base', knowledgeBaseId],
    queryFn: ({ signal }) => getKnowledgeBase(knowledgeBaseId, { signal }),
    enabled: Boolean(knowledgeBaseId),
    refetchInterval: 5_000,
  });
  const versionsQuery = useQuery({
    queryKey: ['knowledge-base-versions', knowledgeBaseId],
    queryFn: ({ signal }) => getKnowledgeVersions(knowledgeBaseId, { signal }),
    enabled: Boolean(knowledgeBaseId),
    staleTime: 10_000,
    refetchInterval: 5_000,
  });
  const sourcesQuery = useQuery({
    queryKey: ['knowledge-base-sources', knowledgeBaseId],
    queryFn: ({ signal }) => getSources(knowledgeBaseId, { signal }),
    enabled: Boolean(knowledgeBaseId),
    staleTime: 10_000,
  });
  const runsQuery = useQuery({
    queryKey: ['knowledge-base-runs', knowledgeBaseId],
    queryFn: ({ signal }) => getUpdateRuns(20, { knowledge_base_id: knowledgeBaseId, signal }),
    enabled: Boolean(knowledgeBaseId),
    staleTime: 0,
    refetchInterval: 2_000,
  });
  const uploadStatusQuery = useQuery({
    queryKey: ['knowledge-base-run-status', uploadRunId],
    queryFn: ({ signal }) => getUpdateRunStatus(uploadRunId as string, { signal }),
    enabled: Boolean(uploadRunId),
    staleTime: 0,
    refetchInterval: (query: { state: { data: KnowledgeUpdateRun | undefined } }) => {
      const data = query.state.data;
      return data && isKnowledgeRunTerminal(data.status) ? false : 2_000;
    },
  });
  const notificationsQuery = useQuery({
    queryKey: ['knowledge-base-notifications', knowledgeBaseId],
    queryFn: ({ signal }) => getKnowledgeNotifications(10, knowledgeBaseId, { signal }),
    enabled: Boolean(knowledgeBaseId),
    staleTime: 5_000,
    refetchInterval: 5_000,
  });
  const documentsQuery = useQuery({
    queryKey: ['knowledge-base-documents', knowledgeBaseId, documentViewVersionId],
    queryFn: ({ signal }) => getKnowledgeBaseDocuments(knowledgeBaseId, { knowledge_version_id: documentViewVersionId || undefined, include_deleted: true, signal }),
    enabled: Boolean(knowledgeBaseId),
    staleTime: 5_000,
    refetchInterval: 5_000,
  });
  const generationLockQuery = useQuery({
    queryKey: ['knowledge-selection-generation-lock'],
    queryFn: ({ signal }) => getTasks({ limit: 100 }, { signal }),
    staleTime: 2_000,
    refetchInterval: 5_000,
  });

  const base = baseQuery.data as KnowledgeBase | undefined;
  const generationSelectionLocked = hasRunningGeneration(generationLockQuery.data);
  const versions = versionsQuery.data ?? [];
  const selectableVersions = useMemo(() => selectableKnowledgeVersions(versions), [versions]);
  const persistedGenerationVersionId = base?.selected_knowledge_version_id ?? '';
  const selectedGenerationVersionId = generationVersionDirty ? generationVersionId : persistedGenerationVersionId;
  const effectiveGenerationVersionId = selectedGenerationVersionId || base?.active_knowledge_version_id || '';
  const activeDocumentsVersionId = documentViewVersionId || base?.active_knowledge_version_id || '';
  const uploadSource = useMemo(
    () => (sourcesQuery.data ?? []).find((source: Source) => source.source_type === 'manual_upload') as Source | undefined,
    [sourcesQuery.data],
  );
  const uploadSourceDraft = uploadSource ? (sourceDrafts[uploadSource.source_id] ?? toSourceDraft(uploadSource)) : uploadSourceDefaults;
  const uploadSourceDirty = uploadSource ? Boolean(dirtySourceIds[uploadSource.source_id]) : false;
  const uploadSourceStatusOptions = uploadSource ? allowedSourceStatuses(uploadSourceDraft.status) : ['active', 'disabled'];
  const uploadSourceReady = uploadSourceDraft.status === 'active';

  useEffect(() => {
    const hasActiveRun = Boolean(
      (runsQuery.data ?? []).some((run: KnowledgeUpdateRun) => isKnowledgeRunInProgress(run))
      || (uploadStatusQuery.data && !isKnowledgeRunTerminal(uploadStatusQuery.data.status)),
    );
    if (!hasActiveRun) return undefined;
    const intervalId = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(intervalId);
  }, [runsQuery.data, uploadStatusQuery.data?.status]);

  useEffect(() => {
    setGenerationVersionId(base?.selected_knowledge_version_id ?? '');
    setGenerationVersionDirty(false);
  }, [base?.knowledge_base_id, base?.selected_knowledge_version_id]);

  useEffect(() => {
    setSourceDrafts((current) => {
      const nextDrafts: Record<string, SourceDraft> = { ...current };
      const sourceIds = new Set<string>();
      let changed = false;

      for (const source of (sourcesQuery.data ?? [])) {
        sourceIds.add(source.source_id);
        if (dirtySourceIds[source.source_id]) {
          if (!nextDrafts[source.source_id]) {
            nextDrafts[source.source_id] = toSourceDraft(source);
            changed = true;
          }
          continue;
        }
        const serverDraft = toSourceDraft(source);
        const currentDraft = current[source.source_id];
        if (!currentDraft || currentDraft.refresh_policy !== serverDraft.refresh_policy || currentDraft.status !== serverDraft.status) {
          nextDrafts[source.source_id] = serverDraft;
          changed = true;
        }
      }

      for (const sourceId of Object.keys(nextDrafts)) {
        if (!sourceIds.has(sourceId)) {
          delete nextDrafts[sourceId];
          changed = true;
        }
      }

      return changed ? nextDrafts : current;
    });
    setDirtySourceIds((current) => {
      const sourceIds = new Set((sourcesQuery.data ?? []).map((source: Source) => source.source_id));
      const filtered = Object.fromEntries(Object.entries(current).filter(([sourceId]) => sourceIds.has(sourceId)));
      return Object.keys(filtered).length === Object.keys(current).length ? current : filtered;
    });
  }, [dirtySourceIds, sourcesQuery.data]);

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-bases-selector'] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-versions-selector'] });
    queryClient.invalidateQueries({ queryKey: DASHBOARD_KNOWLEDGE_BASES_KEY });
    queryClient.invalidateQueries({ queryKey: ['dashboard-active-version'] });
    queryClient.invalidateQueries({ queryKey: ['new-task-active-version'] });
    queryClient.invalidateQueries({ queryKey: ['task-active-version'] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-base', knowledgeBaseId] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-base-versions', knowledgeBaseId] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-base-documents', knowledgeBaseId] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-base-sources', knowledgeBaseId] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-base-runs', knowledgeBaseId] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-base-notifications', knowledgeBaseId] });
    queryClient.invalidateQueries({ queryKey: ['knowledge-notifications'] });
  };

  const syncMutation = useMutation({
    mutationFn: () => syncKnowledgeBase(knowledgeBaseId, { execute_inline: false, reason: `manual_sync:${knowledgeBaseId}` }),
    onSuccess: invalidate,
  });

  const selectMutation = useMutation({
    mutationFn: (knowledgeVersionId?: string | null) => selectKnowledgeBase(knowledgeBaseId, knowledgeVersionId ?? null),
    onSuccess: () => {
      setGenerationVersionDirty(false);
      invalidate();
    },
  });

  const activateMutation = useMutation({
    mutationFn: (versionId: string) => activateKnowledgeVersion(versionId, 'Ручной выбор версии из карточки базы знаний'),
    onSuccess: invalidate,
  });

  const sourceMutation = useMutation({
    mutationFn: () => createSource({ knowledge_base_id: knowledgeBaseId, source_type: newSourceType, name: newSourceName.trim(), base_uri: newSourceUri.trim(), criticality: 'optional' }),
    onSuccess: () => {
      setNewSourceName('');
      setNewSourceUri('');
      invalidate();
    },
  });

  const sourceSettingsMutation = useMutation({
    mutationFn: async ({ sourceId, refresh_policy, status }: { sourceId: string; refresh_policy: string; status?: string }) => {
      if (status === 'archived') {
        await updateSource(sourceId, { refresh_policy });
        return archiveSource(sourceId);
      }
      if (status === 'disabled') {
        await updateSource(sourceId, { refresh_policy });
        return disableSource(sourceId);
      }
      return updateSource(sourceId, { refresh_policy, status });
    },
    onSuccess: (_data, variables) => {
      setDirtySourceIds((current) => ({ ...current, [variables.sourceId]: false }));
      invalidate();
    },
  });

  const updateUploadSourceDraft = (patch: Partial<SourceDraft>) => {
    const nextDraft = { ...uploadSourceDraft, ...patch };
    if (uploadSource) {
      setSourceDrafts((current) => ({ ...current, [uploadSource.source_id]: nextDraft }));
      setDirtySourceIds((current) => ({ ...current, [uploadSource.source_id]: true }));
    } else {
      setUploadSourceDefaults(nextDraft);
    }
  };

  const uploadMutation = useMutation({
    mutationFn: async () => {
      return uploadAndIngestKnowledgeFiles({
        files: uploadFiles,
        title: uploadTitle,
        knowledge_base_id: knowledgeBaseId,
        refresh_policy: uploadSourceDraft.refresh_policy,
        source_status: uploadSourceDraft.status,
        execute_update_inline: false,
        reason: `batch_upload:${knowledgeBaseId}`,
      });
    },
    onSuccess: (data) => {
      setUploadTitle('');
      setUploadFiles([]);
      setUploadRunId(data.update_run?.update_run_id ?? null);
      invalidate();
    },
  });

  const removeMutation = useMutation({
    mutationFn: (documentId: string) => removeKnowledgeDocument(documentId, { reason: 'removed_from_knowledge_base' }),
    onSuccess: invalidate,
  });

  const latestRun = (runsQuery.data ?? [])[0] as KnowledgeUpdateRun | undefined;
  const syncStartedRun = syncMutation.data as KnowledgeUpdateRun | undefined;
  const updateCardRun = latestRun ?? syncStartedRun;
  const updateRunLinkId = updateCardRun?.update_run_id ?? base?.latest_sync_run_id ?? null;
  const updateCardRunDetails = runActiveStageDetails(updateCardRun, nowMs);
  const trackedUploadRun = uploadStatusQuery.data ?? (uploadRunId ? (runsQuery.data ?? []).find((run: KnowledgeUpdateRun) => run.update_run_id === uploadRunId) : undefined);
  const uploadLearningInProgress = isKnowledgeRunInProgress(trackedUploadRun);
  const trackedUploadStage = knowledgeRunStage(trackedUploadRun);
  const trackedUploadQuality = qualitySummaryOf(trackedUploadRun);
  const trackedUploadRunDetails = runActiveStageDetails(trackedUploadRun, nowMs);
  const latestValidationReport = (latestRun?.validation_report ?? {}) as Record<string, unknown>;
  const latestErrors = (latestRun?.problem_sources ?? []) as Record<string, unknown>[];
  const latestFailureItems = latestErrors.length > 0 ? latestErrors : (latestRun?.status === 'failed' ? [{
    source_name: 'Синхронизация',
    error_message: String(
      latestValidationReport.reason
      ?? (latestRun?.quality_summary as Record<string, unknown> | undefined)?.error
      ?? 'Синхронизация завершилась ошибкой без детализированной processing error записи',
    ),
    stage: String(latestRun?.current_stage ?? 'failed'),
    error_code: String(
      ((latestRun?.quality_summary as Record<string, unknown> | undefined)?.error_code)
      ?? (latestRun?.diagnostics as Record<string, unknown> | undefined)?.error_code
      ?? 'KNOWLEDGE_UPDATE_FAILED',
    ),
  }] : []);
  const isSystemBase = base?.kind === 'system_mandatory';
  const selectedGenerationVersion = useMemo(
    () => selectableVersions.find((item: KnowledgeVersion) => item.knowledge_version_id === effectiveGenerationVersionId) ?? null,
    [effectiveGenerationVersionId, selectableVersions],
  );
  const hasGenerationVersion = Boolean(effectiveGenerationVersionId);
  const viewedDocumentsVersion = useMemo(
    () => versions.find((item: KnowledgeVersion) => item.knowledge_version_id === activeDocumentsVersionId) ?? null,
    [activeDocumentsVersionId, versions],
  );
  const isViewingActiveDocumentsVersion = !documentViewVersionId || documentViewVersionId === (base?.active_knowledge_version_id ?? '');

  if (baseQuery.isLoading) {
    return <LoadingState message="Открываю карточку базы знаний…" />;
  }
  if (baseQuery.isError || !base) {
    return <EmptyState title="Не удалось загрузить карточку базы знаний" />;
  }

  return (
    <div className="stack">
      <PageHeader
        title={base.name}
        subtitle="Настройки источников, версии, состав документов, история синхронизаций и ошибки последнего обновления."
        actions={<Link to="/knowledge" className="button">Назад в реестр</Link>}
      />

      <div className="grid grid-4">
        <Card title="Тип"><strong>{knowledgeBaseKindLabel(base.kind)}</strong></Card>
        <Card title="Источники"><strong>{String(base.source_count ?? 0)}</strong></Card>
        <Card title="Документы"><strong>{String(base.document_count ?? 0)}</strong></Card>
        <Card title="Длительность обновления"><strong>{formatSeconds(base.last_sync_duration_sec)}</strong></Card>
      </div>

      {base.selected_for_generation ? (
        <Banner tone="info">Эта база сейчас выбрана для подготовки решений. Другие базы не подмешиваются автоматически.</Banner>
      ) : (
        <Banner tone="warning">Эта база не выбрана для подготовки решений. Её можно выбрать ниже.</Banner>
      )}
      {!hasGenerationVersion ? (
        <Banner tone="warning">У выбранной базы пока нет активной версии знаний. Подготовка решений станет доступна после активации проверенной версии.</Banner>
      ) : null}
      {isSystemBase ? <Banner tone="info">Это системная baseline-база. Она всегда доступна в перечне баз знаний, защищена от пользовательских изменений состава документов.</Banner> : null}

      <div className="grid grid-2">
        <Card title="Выбор базы для подготовки решений" subtitle="Можно выбрать базу и зафиксировать конкретную версию для следующих запусков подготовки решения.">
          <div className="stack compact">
            {generationSelectionLocked ? <Banner tone="warning">{GENERATION_SELECTION_LOCK_REASON}</Banner> : null}
            <FormRow label="Версия для генерации">
              <Select value={selectedGenerationVersionId} onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                setGenerationVersionId(event.target.value);
                setGenerationVersionDirty(true);
              }} disabled={isSystemBase || generationSelectionLocked || selectMutation.isPending}>
                <option value="">Активная версия базы</option>
                {selectableVersions.map((version: KnowledgeVersion) => (
                  <option key={version.knowledge_version_id} value={version.knowledge_version_id}>{version.version_no} · {formatDateTime(version.created_at)}</option>
                ))}
              </Select>
            </FormRow>
            {selectedGenerationVersion ? <div className="muted small">Для подготовки решений будет использоваться версия {selectedGenerationVersion.version_no} · статус {titleStatus(selectedGenerationVersion.status)}.</div> : null}
            {selectMutation.isError ? <ErrorNotice error={selectMutation.error} fallback="Не удалось выбрать базу для подготовки решений." /> : null}
            <div className="actions">
              <Button primary onClick={() => selectMutation.mutate(isSystemBase ? null : selectedGenerationVersionId || null)} disabled={selectMutation.isPending || generationSelectionLocked}>
                {selectMutation.isPending ? 'Сохраняю…' : 'Выбрать для подготовки решений'}
              </Button>
            </div>
          </div>
        </Card>

        <Card title="Обновление базы" subtitle="Ручной запуск обработки источников и подготовки новой версии знаний.">
          <div className="stack compact">
            <div><strong>Последний запуск:</strong> {formatDateTime(base.latest_sync_at)}</div>
            <div><strong>Статус:</strong> {titleStatus(base.latest_sync_status)}</div>
            <div><strong>Длительность:</strong> {formatSeconds(base.last_sync_duration_sec)}</div>
            {updateCardRun && isKnowledgeRunInProgress(updateCardRun) ? (
              <Banner tone="info">
                <strong>Сейчас выполняется: {titleStatus(knowledgeRunStage(updateCardRun))}</strong>
                <div>{knowledgeRunStageHint(knowledgeRunStage(updateCardRun))}</div>
                <div className="muted small">{runProgressLine(updateCardRun, nowMs)}</div>
                {updateCardRunDetails.map((line) => <div className="muted small" key={line}>{line}</div>)}
              </Banner>
            ) : null}
            {syncMutation.isError ? <ErrorNotice error={syncMutation.error} fallback="Не удалось запустить синхронизацию." /> : null}
            <div className="actions">
              <Button primary onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>{syncMutation.isPending ? 'Запускаю…' : 'Обновить сейчас'}</Button>
              {updateRunLinkId ? <Link className="button" to={`/operations/${updateRunLinkId}`}>Ход событий</Link> : null}
            </div>
          </div>
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Источники" subtitle="URL-страницы и загруженные файлы, из которых база получает материалы.">
          {sourcesQuery.isLoading ? <LoadingState message="Загружаю источники…" /> : sourcesQuery.isError ? <ErrorNotice error={sourcesQuery.error} fallback="Не удалось загрузить источники." /> : sourcesQuery.data?.length ? (
            <div className="timeline">
              {sourcesQuery.data.map((source: Source) => {
                const draft = sourceDrafts[source.source_id] ?? toSourceDraft(source);
                return (
                  <div className="timeline-item" key={source.source_id}>
                    <div className="actions between">
                      <strong>{source.name}</strong>
                      <div className="actions">
                        <Badge value={source.status} />
                        <Badge value={source.refresh_policy ?? 'monthly'} />
                      </div>
                    </div>
                    <div className="muted small">{sourceTypeLabel(source.source_type)} · {source.base_uri ?? 'Адрес источника не задан'}</div>
                    <div className="actions" style={{ marginTop: 8 }}>
                      {source.base_uri && /^https?:\/\//i.test(source.base_uri) ? <a className="button" href={source.base_uri} target="_blank" rel="noreferrer">Открыть источник</a> : null}
                      {!isSystemBase && source.status !== 'archived' ? (
                        <Button
                          onClick={() => {
                            if (window.confirm(`Архивировать источник «${source.name}»? Он будет исключен из следующих версий базы знаний.`)) {
                              sourceSettingsMutation.mutate({
                                sourceId: source.source_id,
                                refresh_policy: draft.refresh_policy,
                                status: 'archived',
                              });
                            }
                          }}
                          disabled={sourceSettingsMutation.isPending}
                        >
                          Архивировать
                        </Button>
                      ) : null}
                    </div>
                    <div className="muted small">Документов: {source.document_count ?? 0} · обнаружено: {formatDateTime(source.last_discovered_at)} · последнее обновление: {formatDateTime(source.last_sync_time)}</div>
                    <div className="muted small">Следующее обновление: {formatDateTime(source.next_sync_time)} · политика: {refreshPolicyLabel(source.refresh_policy)}</div>
                    {source.last_error_message ? <div className="muted small">Последняя ошибка: {source.last_error_message}</div> : null}
                    {!isSystemBase ? (
                      <div className="grid grid-2" style={{ marginTop: 12 }}>
                        <FormRow label="Политика обновления">
                          <Select value={draft.refresh_policy} onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                            const next = event.target.value;
                            setSourceDrafts((current) => ({ ...current, [source.source_id]: { ...draft, refresh_policy: next } }));
                            setDirtySourceIds((current) => ({ ...current, [source.source_id]: true }));
                          }}>
                            {KNOWLEDGE_REFRESH_POLICY_OPTIONS.map((option) => (
                              <option key={option.value} value={option.value}>{option.label}</option>
                            ))}
                          </Select>
                        </FormRow>
                        <FormRow label="Статус источника">
                          <Select value={draft.status} onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                            const next = event.target.value;
                            setSourceDrafts((current) => ({ ...current, [source.source_id]: { ...draft, status: next } }));
                            setDirtySourceIds((current) => ({ ...current, [source.source_id]: true }));
                          }}>
                            {allowedSourceStatuses(draft.status).map((statusValue) => (
                              <option key={statusValue} value={statusValue} disabled={statusValue === 'unavailable' && source.status !== 'unavailable'}>
                                {titleStatus(statusValue)}
                              </option>
                            ))}
                          </Select>
                        </FormRow>
                        <div className="actions">
                          <Button
                            onClick={() => sourceSettingsMutation.mutate({
                              sourceId: source.source_id,
                              refresh_policy: draft.refresh_policy,
                              status: draft.status === source.status || draft.status === 'unavailable' ? undefined : draft.status,
                            })}
                            disabled={sourceSettingsMutation.isPending || !dirtySourceIds[source.source_id]}
                          >
                            {sourceSettingsMutation.isPending ? 'Сохраняю…' : 'Сохранить настройки'}
                          </Button>
                        </div>
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          ) : <EmptyState title="Источников пока нет" />}
          {sourceSettingsMutation.isError ? <ErrorNotice error={sourceSettingsMutation.error} fallback="Не удалось сохранить настройки источника." /> : null}

          {!isSystemBase ? (
            <div className="stack compact" style={{ marginTop: 16 }}>
              <FormRow label="Новый источник">
                <Input value={newSourceName} onChange={(event: ChangeEvent<HTMLInputElement>) => setNewSourceName(event.target.value)} placeholder="Можно оставить пустым" />
              </FormRow>
              <FormRow label="URL-страница">
                <Input value={newSourceUri} onChange={(event: ChangeEvent<HTMLInputElement>) => setNewSourceUri(event.target.value)} placeholder="https://docs.example.com/architecture/" />
              </FormRow>
              <div className="muted small">Вставьте адрес web-страницы. Если название пустое, система заполнит его по URL.</div>
              {sourceMutation.isError ? <ErrorNotice error={sourceMutation.error} fallback="Не удалось добавить источник." /> : null}
              <div className="actions">
                <Button primary onClick={() => sourceMutation.mutate()} disabled={sourceMutation.isPending || !newSourceUri.trim()}>
                  {sourceMutation.isPending ? 'Добавляю…' : 'Добавить источник'}
                </Button>
              </div>
            </div>
          ) : null}
        </Card>

        <Card title="Дозагрузка документа" subtitle="Добавляет документ в базу и запускает его обработку в новой версии знаний.">
          {isSystemBase ? <EmptyState title="Для системной базы дозагрузка через UI запрещена" /> : (
            <div className="stack compact">
              <FormRow label="Название в системе">
                <Input value={uploadTitle} onChange={(event: ChangeEvent<HTMLInputElement>) => setUploadTitle(event.target.value)} placeholder="Можно оставить пустым" />
              </FormRow>
              <FormRow label="Файл">
                <Input type="file" multiple onChange={(event: ChangeEvent<HTMLInputElement>) => setUploadFiles(Array.from(event.target.files ?? []))} />
              </FormRow>
              <div className="grid grid-2">
                <FormRow label="Политика обновления">
                  <Select value={uploadSourceDraft.refresh_policy} onChange={(event: ChangeEvent<HTMLSelectElement>) => updateUploadSourceDraft({ refresh_policy: event.target.value })}>
                    {KNOWLEDGE_REFRESH_POLICY_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </Select>
                </FormRow>
                <FormRow label="Статус источника">
                  <Select value={uploadSourceDraft.status} onChange={(event: ChangeEvent<HTMLSelectElement>) => updateUploadSourceDraft({ status: event.target.value })}>
                    {uploadSourceStatusOptions.map((statusValue) => (
                      <option key={statusValue} value={statusValue} disabled={statusValue === 'unavailable' && uploadSource?.status !== 'unavailable'}>
                        {titleStatus(statusValue)}
                      </option>
                    ))}
                  </Select>
                </FormRow>
                {uploadSource ? (
                  <div className="actions">
                    <Button
                      onClick={() => sourceSettingsMutation.mutate({
                        sourceId: uploadSource.source_id,
                        refresh_policy: uploadSourceDraft.refresh_policy,
                        status: uploadSourceDraft.status === uploadSource.status || uploadSourceDraft.status === 'unavailable' ? undefined : uploadSourceDraft.status,
                      })}
                      disabled={sourceSettingsMutation.isPending || !uploadSourceDirty}
                    >
                      {sourceSettingsMutation.isPending ? 'Сохраняю…' : 'Сохранить настройки'}
                    </Button>
                  </div>
                ) : null}
              </div>
              {trackedUploadRun ? (
                <Banner tone={trackedUploadRun.status === 'failed' ? 'danger' : 'info'}>
                  <strong>Документ принят. {titleStatus(trackedUploadStage)}</strong>
                  <div>{knowledgeRunStageHint(trackedUploadStage)}</div>
                  <div className="muted small">{runProgressLine(trackedUploadRun, nowMs)} · процесс {trackedUploadRun.update_run_id}</div>
                  {trackedUploadRunDetails.map((line) => <div className="muted small" key={line}>{line}</div>)}
                  <div className="grid grid-4" style={{ marginTop: 12 }}>
                    <MetricCard label="Получено файлов" value={metricText(trackedUploadQuality, 'fetched_documents')} />
                    <MetricCard label="Обработано документов" value={metricText(trackedUploadQuality, 'processed_documents')} />
                    <MetricCard label="Чанков" value={metricText(trackedUploadQuality, 'chunk_count')} />
                    <MetricCard label="Эмбеддингов" value={metricText(trackedUploadQuality, 'embeddings_calculated')} />
                  </div>
                </Banner>
              ) : null}
              {uploadMutation.isError ? <ErrorNotice error={uploadMutation.error} fallback="Не удалось загрузить документ." /> : null}
              <div className="actions">
                <Button primary onClick={() => uploadMutation.mutate()} disabled={uploadMutation.isPending || uploadLearningInProgress || uploadFiles.length === 0 || !uploadSourceReady}>
                  {uploadMutation.isPending ? 'Загружаю файл…' : uploadLearningInProgress ? 'База изучает документ…' : 'Дозагрузить и запустить обучение'}
                </Button>
              </div>
            </div>
          )}
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Версии базы знаний" subtitle="Активировать можно только проверенную или архивную версию.">
          {versionsQuery.isLoading ? <LoadingState message="Загружаю версии…" /> : versionsQuery.isError ? <ErrorNotice error={versionsQuery.error} fallback="Не удалось загрузить версии базы знаний." /> : versions.length === 0 ? <EmptyState title="Версий пока нет" /> : (
            <div className="timeline">
              {versions.map((version: KnowledgeVersion) => {
                const canActivate = version.status === 'validated' || version.status === 'archived';
                const isActiveVersion = version.knowledge_version_id === base.active_knowledge_version_id;
                const selectedVersionId = base.selected_knowledge_version_id ?? base.active_knowledge_version_id;
                const isSelectedForGeneration = base.selected_for_generation && version.knowledge_version_id === selectedVersionId;
                return (
                  <div className="timeline-item" key={version.knowledge_version_id}>
                    <div className="actions between">
                      <strong>{version.version_no}</strong>
                      <div className="actions">
                        {isActiveVersion ? <Badge value="active" /> : <Badge value={version.status} />}
                        {isSelectedForGeneration ? <Badge value="selected_for_generation" /> : null}
                      </div>
                    </div>
                    <div className="muted small">Создана: {formatDateTime(version.created_at)} · тип обновления: {titleStatus(version.run_type)}</div>
                    <div className="muted small">Причина: {version.run_reason ?? '—'} · документов: {version.document_count ?? '—'} · ошибок: {version.processing_error_count ?? 0}</div>
                    <div className="muted small">SLA: {version.sla && typeof version.sla.actual_sec === 'number' ? formatSeconds(Number(version.sla.actual_sec)) : '—'}</div>
                    <div className="actions">
                      <Button onClick={() => setDocumentViewVersionId(version.knowledge_version_id)}>Показать состав</Button>
                      <Button onClick={() => {
                        if (window.confirm(`Активировать версию ${version.version_no}?`)) activateMutation.mutate(version.knowledge_version_id);
                      }} disabled={!canActivate || activateMutation.isPending || generationSelectionLocked}>Активировать</Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>

        <Card title="История обновлений" subtitle="Этапы, длительность, ошибки и итоговые версии.">
          {runsQuery.isLoading ? <LoadingState message="Загружаю историю обновлений…" /> : runsQuery.isError ? <ErrorNotice error={runsQuery.error} fallback="Не удалось загрузить историю обновлений." /> : (runsQuery.data ?? []).length === 0 ? <EmptyState title="Запусков пока нет" /> : (
            <div className="timeline">
              {(runsQuery.data ?? []).map((run: KnowledgeUpdateRun) => {
                const quality = qualitySummaryOf(run);
                const elapsedSec = knowledgeRunElapsedSeconds(run, nowMs);
                const detailLines = runActiveStageDetails(run, nowMs);
                return (
                  <div className={`timeline-item timeline-item-${run.status}`} key={run.update_run_id}>
                    <div className="actions between">
                      <strong>{titleStatus(run.run_type)}</strong>
                      <Badge value={run.status} />
                    </div>
                    <div className="muted small">Старт: {formatDateTime(run.started_at)} · финиш: {formatDateTime(run.finished_at)} · длительность: {formatSeconds(run.duration_sec ?? elapsedSec)}</div>
                    <div className="muted small">Этап: {titleStatus(knowledgeRunStage(run))} · прогресс: {knowledgeRunStageProgress(run)} · кандидат: {run.candidate_knowledge_version_id ?? '—'}</div>
                    <div>{knowledgeRunStageHint(knowledgeRunStage(run))}</div>
                    {detailLines.map((line) => <div className="muted small" key={line}>{line}</div>)}
                    <div className="muted small">
                      Файлов: {metricText(quality, 'fetched_documents')} · документов: {Number(quality.processed_documents ?? 0) + Number(quality.reused_documents ?? 0)} · чанков: {metricText(quality, 'chunk_count')} · эмбеддингов: {metricText(quality, 'embeddings_calculated')} · ошибок: {metricText(quality, 'processing_error_count')}
                    </div>
                    <div className="actions">
                      <Link className="button" to={`/operations/${run.update_run_id}`}>Ход обновления</Link>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      <Card title="Состав выбранной версии" subtitle="Документы активной или явно выбранной версии. Удалённые материалы остаются в списке только как история изменений и помечаются отдельно.">
        {removeMutation.isError ? <ErrorNotice error={removeMutation.error} fallback="Не удалось удалить документ из базы знаний." /> : null}
        {removeMutation.isSuccess && removeMutation.data?.update_run ? (
          <Banner tone="info">
            <strong>Документ помечен удалённым.</strong>
            <div>Запущено обновление базы; после подготовки новой версии он будет исключён из актуального состава.</div>
          </Banner>
        ) : null}
        <div className="actions between" style={{ marginBottom: 12 }}>
          <div className="muted small">Сейчас показана версия: {viewedDocumentsVersion?.version_no ?? base.active_version_no ?? '—'}</div>
          <Select value={documentViewVersionId} onChange={(event: ChangeEvent<HTMLSelectElement>) => setDocumentViewVersionId(event.target.value)}>
            <option value="">Активная версия</option>
            {versions.map((version: KnowledgeVersion) => <option key={version.knowledge_version_id} value={version.knowledge_version_id}>{version.version_no}</option>)}
          </Select>
        </div>
        {documentsQuery.isLoading ? <LoadingState message="Загружаю состав версии…" /> : documentsQuery.isError ? <ErrorNotice error={documentsQuery.error} fallback="Не удалось загрузить состав версии." /> : (documentsQuery.data ?? []).length === 0 ? <EmptyState title="В выбранной версии нет документов" /> : (
          <div className="timeline">
            {(documentsQuery.data ?? []).map((document: KnowledgeBaseDocument) => {
              const documentWithProcessing = document as KnowledgeBaseDocumentWithProcessing;
              const lifecycleStatus = documentLifecycleStatus(documentWithProcessing);
              const removedFromKnowledgeBase = isRemovedFromKnowledgeBase(document);
              const canRemoveDocument = !isSystemBase
                && isViewingActiveDocumentsVersion
                && Boolean(document.document_id)
                && Boolean(document.present_in_version)
                && !removedFromKnowledgeBase;
              return (
                <div className="timeline-item" key={`${document.document_id ?? document.uri}:${document.delta_kind ?? 'present'}`}>
                  <div className="actions between">
                    <strong>{document.title}</strong>
                    <div className="actions">
                      {document.delta_kind ? <Badge value={document.delta_kind} /> : null}
                      {lifecycleStatus ? <Badge value={lifecycleStatus} /> : null}
                    </div>
                  </div>
                  <div className="muted small">Источник: {document.source_name ?? '—'} · тип: {document.document_type ?? '—'} · роль: {document.role_code ?? 'reference_only'}</div>
                  <div className="muted small">Путь или URL: {document.uri ?? '—'}</div>
                  {documentWithProcessing.processing_error_message ? (
                    <div className="muted small">Ошибка обработки: {documentWithProcessing.processing_error_message}</div>
                  ) : null}
                  <div className="actions">
                    {document.document_id ? <Link className="button" to={`/knowledge/documents/${document.document_id}?knowledge_version_id=${encodeURIComponent(document.knowledge_version_id)}`}>Открыть документ</Link> : null}
                    {canRemoveDocument ? (
                      <Button onClick={() => {
                        if (window.confirm(`Удалить документ «${document.title}» из состава базы?`)) removeMutation.mutate(document.document_id as string);
                      }} disabled={removeMutation.isPending}>Удалить из базы</Button>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <div className="grid grid-2">
        <Card title="Уведомления">
          {notificationsQuery.isLoading ? <LoadingState message="Загружаю уведомления…" /> : notificationsQuery.isError ? <ErrorNotice error={notificationsQuery.error} fallback="Не удалось загрузить уведомления." /> : (notificationsQuery.data ?? []).length === 0 ? <EmptyState title="Уведомлений пока нет" /> : (
            <div className="timeline">
              {(notificationsQuery.data ?? []).map((item: KnowledgeNotification) => (
                <div className="timeline-item" key={item.notification_id}>
                  <div className="actions between">
                    <strong>{item.title}</strong>
                    <Badge value={item.status} />
                  </div>
                  <div>{item.message}</div>
                  <div className="muted small">{formatDateTime(item.created_at)}</div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Ошибки последнего обновления">
          {runsQuery.isError ? <ErrorNotice error={runsQuery.error} fallback="Не удалось загрузить ошибки последнего обновления." /> : latestFailureItems.length === 0 ? <EmptyState title="Критичных ошибок последнего обновления не найдено" /> : (
            <div className="timeline">
              {latestFailureItems.map((item: Record<string, unknown>, index: number) => (
                <div className="timeline-item" key={`${String(item.document_id ?? item.source_id)}:${index}`}>
                  <div className="actions between">
                    <strong>{String(item.document_title ?? item.source_name ?? 'Источник')}</strong>
                    <Badge value="failed" />
                  </div>
                  <div>{String(item.error_message ?? 'Ошибка обработки')}</div>
                  <div className="muted small">Этап: {titleStatus(String(item.stage ?? 'failed'))} · код: {String(item.error_code ?? '—')}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
