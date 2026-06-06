import { type ChangeEvent, type FormEvent, useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import {
  checkExternalArchitecture,
  getVerificationProtocol,
  type ExternalArchitectureCheckResult,
} from '../shared/api/verification';
import { createTask, getTask, importTaskInputFile, updateTask } from '../shared/api/tasks';
import { queryKeys } from '../shared/api/queryKeys';
import {
  KnowledgeDocumentScopePicker,
  type KnowledgeDocumentScopeMode,
} from '../entities/knowledge/KnowledgeDocumentScopePicker';
import {
  Badge,
  Banner,
  Button,
  Card,
  EmptyState,
  ErrorNotice,
  FormRow,
  Input,
  LoadingState,
  PageHeader,
  StatCard,
  StateBox,
  Textarea,
} from '../shared/ui/components';
import { cleanEvidenceRef, formatDateTime, titleStatus, truncate, verificationFindingImpact, verificationRuleGroupLabel } from '../shared/lib/format';
import type { VerificationFinding } from '../types/api';

const EXTERNAL_ARCHITECTURE_DRAFT_TITLE = 'Черновик проверки архитектуры';

function nonPassedFindings(findings: VerificationFinding[]) {
  return findings.filter((item) => item.status === 'failed' || item.status === 'warning' || item.status === 'not_determined');
}

function buildCorrelationId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `external-architecture:${crypto.randomUUID()}`;
  }
  return `external-architecture:${Date.now()}`;
}

export function ExternalArchitectureCheckPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const draftTaskId = searchParams.get('draft_task_id');
  const [title, setTitle] = useState('');
  const [architectureText, setArchitectureText] = useState('');
  const [draftSavedAt, setDraftSavedAt] = useState<string | null>(null);
  const [draftStatus, setDraftStatus] = useState<'restored' | 'saved' | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [hydratedDraftId, setHydratedDraftId] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<ExternalArchitectureCheckResult | null>(null);
  const [knowledgeDocumentScopeMode, setKnowledgeDocumentScopeMode] = useState<KnowledgeDocumentScopeMode>('full');
  const [knowledgeDocumentIds, setKnowledgeDocumentIds] = useState<string[]>([]);

  const draftTaskQuery = useQuery({
    queryKey: draftTaskId ? ['external-architecture-draft', draftTaskId] : ['external-architecture-draft', null],
    queryFn: ({ signal }) => getTask(draftTaskId as string, { signal }),
    enabled: Boolean(draftTaskId),
  });

  useEffect(() => {
    const draft = draftTaskQuery.data;
    if (!draft || hydratedDraftId === draft.task_id) return;
    const metadata = draft.metadata ?? {};
    if (metadata.source !== 'external_architecture' || metadata.verification_only !== true) {
      setDraftError('Этот черновик не относится к проверке архитектуры.');
      return;
    }
    setTitle(draft.title ?? '');
    setArchitectureText(draft.raw_text ?? '');
    setKnowledgeDocumentScopeMode(metadata.knowledge_document_scope_mode === 'selected' ? 'selected' : 'full');
    setKnowledgeDocumentIds(
      Array.isArray(metadata.knowledge_document_ids)
        ? metadata.knowledge_document_ids.filter((item): item is string => typeof item === 'string')
        : [],
    );
    setDraftSavedAt(draft.updated_at);
    setDraftStatus('restored');
    setDraftError(null);
    setHydratedDraftId(draft.task_id);
  }, [draftTaskQuery.data, hydratedDraftId]);

  function buildDraftPayload() {
    return {
      title: title.trim() || EXTERNAL_ARCHITECTURE_DRAFT_TITLE,
      raw_text: architectureText,
      metadata: {
        source: 'external_architecture',
        verification_only: true,
        knowledge_document_scope_mode: knowledgeDocumentScopeMode,
        knowledge_document_ids: knowledgeDocumentScopeMode === 'selected' ? knowledgeDocumentIds : [],
      },
      save_as_draft: true,
    };
  }

  const saveDraftMutation = useMutation({
    mutationFn: () => {
      const payload = buildDraftPayload();
      return draftTaskId ? updateTask(draftTaskId, payload) : createTask(payload);
    },
    onSuccess: async (task) => {
      setDraftSavedAt(task.updated_at);
      setDraftStatus('saved');
      setDraftError(null);
      setHydratedDraftId(task.task_id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard-tasks'] }),
        queryClient.invalidateQueries({ queryKey: ['external-architecture-draft', task.task_id] }),
      ]);
      if (!draftTaskId) {
        navigate(`/external-check?draft_task_id=${encodeURIComponent(task.task_id)}`, { replace: true });
      }
    },
  });
  const fileImportMutation = useMutation({
    mutationFn: importTaskInputFile,
    onSuccess: (preview) => {
      setArchitectureText(preview.text);
      if (!title.trim()) setTitle(preview.title);
      markDraftChanged();
    },
  });

  const mutation = useMutation({
    mutationFn: () => checkExternalArchitecture({
      title: title.trim(),
      architecture_text: architectureText,
      source_ref: null,
      draft_task_id: draftTaskId,
      knowledge_document_ids: knowledgeDocumentScopeMode === 'selected' ? knowledgeDocumentIds : [],
      correlation_id: buildCorrelationId(),
    }),
    onSuccess: async (result) => {
      setLastResult(result);
      setDraftSavedAt(null);
      setDraftStatus(null);
      setDraftError(null);
      setHydratedDraftId(null);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['registry-solutions'] }),
        queryClient.invalidateQueries({ queryKey: ['registry-protocols'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-solutions'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-protocols'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-tasks'] }),
      ]);
      if (draftTaskId) {
        navigate('/external-check', { replace: true });
      }
    },
  });

  const protocolId = lastResult?.protocol_id ?? null;
  const protocolQuery = useQuery({
    queryKey: protocolId ? queryKeys.protocol(protocolId) : ['external-architecture-protocol', null],
    queryFn: ({ signal }) => getVerificationProtocol(protocolId ?? '', { signal }),
    enabled: Boolean(protocolId),
  });

  const protocol = protocolQuery.data;
  const findings = useMemo(() => nonPassedFindings(protocol?.findings ?? []), [protocol?.findings]);
  const totals = protocol?.totals_by_status ?? {};
  const canSubmit = title.trim().length > 0
    && architectureText.trim().length > 0
    && (knowledgeDocumentScopeMode === 'full' || knowledgeDocumentIds.length > 0)
    && !mutation.isPending
    && !saveDraftMutation.isPending;

  function markDraftChanged() {
    setDraftStatus(null);
    setDraftError(null);
  }

  function handleSaveDraft() {
    if (!architectureText.trim()) {
      setDraftError('Чтобы сохранить черновик, заполните текст архитектуры.');
      return;
    }
    saveDraftMutation.mutate();
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) return;
    mutation.mutate();
  }

  function handleFileImport(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) {
      fileImportMutation.mutate(file);
    }
    event.target.value = '';
  }

  return (
    <div className="stack">
      <PageHeader
        title="Проверка существующей архитектуры"
        subtitle="Вставьте готовое описание или документ по архитектуре. Проверка пройдет по тем же правилам и документам, что и протоколы для подготовленных решений."
        actions={<Link to="/registry" className="button">Реестр проверок</Link>}
      />

      <Banner tone="info">
        Недостающие TOGAF-разделы не будут дозаполнены автоматически: если в исходном документе их нет, проверка отметит это в протоколе.
      </Banner>

      {draftTaskQuery.isLoading ? <LoadingState message="Открываю черновик проверки..." /> : null}
      {draftTaskQuery.isError ? <ErrorNotice error={draftTaskQuery.error} fallback="Не удалось открыть черновик проверки." /> : null}

      <Card
        title="Архитектура для проверки"
        subtitle="Лучше вставлять текст с заголовками разделов: General information, Business architecture, Data architecture, Application architecture, Technology architecture."
      >
        <form className="stack" onSubmit={handleSubmit}>
          <FormRow label="Название">
            <Input
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                markDraftChanged();
              }}
              placeholder="Например, Целевая архитектура клиентского профиля"
              maxLength={300}
              required
            />
          </FormRow>
          <FormRow label="Импорт из файла" hint="PDF, DOCX, ODT, XLSX, ArchiMate, HTML, Markdown, TXT, JSON и изображения будут разобраны в текст архитектуры.">
            <Input
              type="file"
              accept=".pdf,.docx,.odt,.xlsx,.archimate,.html,.htm,.md,.markdown,.txt,.text,.json,.png,.jpg,.jpeg,.webp"
              onChange={handleFileImport}
              disabled={mutation.isPending || saveDraftMutation.isPending || fileImportMutation.isPending}
            />
          </FormRow>
          {fileImportMutation.isPending ? <Banner tone="info">Извлекаю текст из файла…</Banner> : null}
          {fileImportMutation.isSuccess ? <Banner tone="success">Текст файла перенесён в поле архитектуры. Проверьте его перед запуском.</Banner> : null}
          {fileImportMutation.isError ? <ErrorNotice error={fileImportMutation.error} fallback="Не удалось извлечь текст из файла." /> : null}
          <FormRow label="Текст архитектуры">
            <Textarea
              value={architectureText}
              onChange={(event) => {
                setArchitectureText(event.target.value);
                markDraftChanged();
              }}
              placeholder="Вставьте описание архитектуры, разделы TOGAF, перечень компонентов, интеграции, риски и ограничения."
              required
              style={{ minHeight: 360 }}
            />
          </FormRow>
          <div className="stack compact">
            <strong>Область проверки по базе знаний</strong>
            <KnowledgeDocumentScopePicker
              mode={knowledgeDocumentScopeMode}
              selectedDocumentIds={knowledgeDocumentIds}
              onModeChange={setKnowledgeDocumentScopeMode}
              onSelectedDocumentIdsChange={setKnowledgeDocumentIds}
              disabled={mutation.isPending || saveDraftMutation.isPending}
            />
          </div>
          {draftStatus && draftSavedAt ? (
            <Banner tone="info">
              {draftStatus === 'saved' ? 'Черновик сохранён' : 'Восстановлен сохранённый черновик'}: {formatDateTime(draftSavedAt)}.
            </Banner>
          ) : null}
          {draftError ? <Banner tone="warning">{draftError}</Banner> : null}
          <div className="actions">
            <Button type="button" onClick={handleSaveDraft} disabled={mutation.isPending || saveDraftMutation.isPending}>
              {saveDraftMutation.isPending ? 'Сохраняю черновик...' : 'Сохранить черновик'}
            </Button>
            <Button primary type="submit" disabled={!canSubmit}>
              {mutation.isPending ? 'Проверяю...' : 'Запустить проверку'}
            </Button>
            <span className="muted small">{architectureText.trim().length} символов</span>
          </div>
        </form>
      </Card>

      {mutation.isError ? (
        <ErrorNotice error={mutation.error} fallback="Не удалось запустить проверку существующей архитектуры." />
      ) : null}
      {saveDraftMutation.isError ? (
        <ErrorNotice error={saveDraftMutation.error} fallback="Не удалось сохранить черновик проверки." />
      ) : null}

      {lastResult ? (
        <Card title="Запуск проверки">
          <div className="stack compact">
            <div className="actions">
              <Badge value={lastResult.verification_state} />
              {lastResult.summary_status ? <Badge value={lastResult.summary_status} /> : null}
              <span className="muted small">База знаний: <span className="mono">{truncate(lastResult.knowledge_version_id, 24)}</span></span>
            </div>
            <div className="actions">
              <Link className="button" to={`/solutions/${lastResult.solution_version_id}`}>Открыть архитектуру</Link>
              {lastResult.protocol_id ? <Link className="button button-primary" to={`/protocols/${lastResult.protocol_id}`}>Открыть протокол</Link> : null}
              <Link className="button" to={`/operations/${lastResult.verification_run_id}`}>Операция проверки</Link>
            </div>
          </div>
        </Card>
      ) : null}

      {protocolQuery.isLoading ? <LoadingState message="Загружаю статистику протокола..." /> : null}
      {protocolQuery.isError ? <ErrorNotice error={protocolQuery.error} fallback="Проверка создана, но статистику протокола загрузить не удалось." /> : null}

      {protocol ? (
        <>
          <div className="grid grid-4">
            <StatCard label="Итог" value={titleStatus(protocol.summary_status)} />
            <StatCard label="Пройдено" value={String(totals.passed ?? 0)} />
            <StatCard label="Предупреждения" value={String(totals.warning ?? 0)} />
            <StatCard label="Несоответствия" value={String((totals.failed ?? 0) + (totals.not_determined ?? 0))} />
          </div>

          <Card title="Объяснение результата">
            <StateBox>{protocol.summary_text}</StateBox>
          </Card>

          <Card title="Несоответствия и замечания">
            {findings.length === 0 ? (
              <EmptyState title="Замечаний по протоколу нет" />
            ) : (
              <div className="timeline">
                {findings.map((finding) => {
                  const evidence = cleanEvidenceRef(finding.evidence);
                  return (
                    <div className="timeline-item" key={finding.check_result_id}>
                      <div className="actions between">
                        <strong>{finding.rule_name ?? finding.rule_id ?? 'Проверка'}</strong>
                        <span className="muted small">
                          {verificationRuleGroupLabel(finding.rule_group ?? 'other')} · {titleStatus(finding.status)} · {verificationFindingImpact(finding.status, finding.severity).label}
                        </span>
                      </div>
                      <div>{finding.finding_text ?? 'Требуется ручной просмотр результата.'}</div>
                      {finding.related_section_ref ? <div className="muted small">Раздел: {finding.related_section_ref}</div> : null}
                      {evidence ? <div className="muted small">Основание: {evidence}</div> : null}
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </>
      ) : null}
    </div>
  );
}
