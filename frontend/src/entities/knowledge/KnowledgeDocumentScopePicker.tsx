import { useEffect, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';

import { getKnowledgeBaseDocuments, getKnowledgeBases } from '../../shared/api/knowledge';
import { Badge, Banner, Button, EmptyState, ErrorNotice, LoadingState } from '../../shared/ui/components';
import type { KnowledgeBase, KnowledgeBaseDocument } from '../../types/api';

export type KnowledgeDocumentScopeMode = 'full' | 'selected';

interface KnowledgeDocumentScopePickerProps {
  mode: KnowledgeDocumentScopeMode;
  selectedDocumentIds: string[];
  onModeChange: (mode: KnowledgeDocumentScopeMode) => void;
  onSelectedDocumentIdsChange: (documentIds: string[]) => void;
  disabled?: boolean;
}

function selectedBaseFromList(bases: KnowledgeBase[]) {
  const selectedUserBase = bases.find((item) => item.selected_for_generation && item.kind === 'user_managed') ?? null;
  const selectedMandatoryBase = bases.find((item) => item.selected_for_generation && item.kind === 'system_mandatory') ?? null;
  return selectedUserBase ?? selectedMandatoryBase;
}

function selectedVersionId(base: KnowledgeBase | null) {
  return base?.selected_knowledge_version_id ?? base?.active_knowledge_version_id ?? '';
}

export function KnowledgeDocumentScopePicker({
  mode,
  selectedDocumentIds,
  onModeChange,
  onSelectedDocumentIdsChange,
  disabled,
}: KnowledgeDocumentScopePickerProps) {
  const basesQuery = useQuery({
    queryKey: ['verification-knowledge-bases'],
    queryFn: ({ signal }) => getKnowledgeBases({ signal }),
    staleTime: 15_000,
  });

  const selectedBase = useMemo(
    () => selectedBaseFromList((basesQuery.data ?? []) as KnowledgeBase[]),
    [basesQuery.data],
  );
  const knowledgeVersionId = selectedVersionId(selectedBase);

  const documentsQuery = useQuery({
    queryKey: ['verification-knowledge-documents', selectedBase?.knowledge_base_id ?? null, knowledgeVersionId],
    queryFn: ({ signal }) => getKnowledgeBaseDocuments(selectedBase?.knowledge_base_id ?? '', {
      knowledge_version_id: knowledgeVersionId || undefined,
      include_deleted: false,
      signal,
    }),
    enabled: Boolean(selectedBase?.knowledge_base_id && knowledgeVersionId),
    staleTime: 10_000,
  });

  const documents = useMemo(
    () => ((documentsQuery.data ?? []) as KnowledgeBaseDocument[])
      .filter((item) => item.document_id && item.present_in_version !== false),
    [documentsQuery.data],
  );

  useEffect(() => {
    if (mode !== 'selected') return;
    const availableIds = new Set(documents.map((item) => item.document_id).filter(Boolean) as string[]);
    const nextIds = selectedDocumentIds.filter((documentId) => availableIds.has(documentId));
    if (nextIds.length !== selectedDocumentIds.length) {
      onSelectedDocumentIdsChange(nextIds);
    }
  }, [documents, mode, onSelectedDocumentIdsChange, selectedDocumentIds]);

  const selectedCount = selectedDocumentIds.length;
  const versionLabel = selectedBase?.selected_knowledge_version_no ?? selectedBase?.active_version_no ?? 'активная версия';

  function toggleDocument(documentId: string) {
    if (selectedDocumentIds.includes(documentId)) {
      onSelectedDocumentIdsChange(selectedDocumentIds.filter((item) => item !== documentId));
      return;
    }
    onSelectedDocumentIdsChange([...selectedDocumentIds, documentId]);
  }

  if (basesQuery.isLoading) {
    return <LoadingState message="Загружаю базы знаний..." />;
  }

  if (basesQuery.isError) {
    return <ErrorNotice error={basesQuery.error} fallback="Не удалось загрузить базы знаний." />;
  }

  if (!selectedBase) {
    return <Banner tone="warning">Для проверки сначала выберите базу знаний для генерации.</Banner>;
  }

  return (
    <div className="stack compact">
      <div className="actions">
        <Button type="button" primary={mode === 'full'} onClick={() => onModeChange('full')} disabled={disabled}>
          Вся база знаний
        </Button>
        <Button type="button" primary={mode === 'selected'} onClick={() => onModeChange('selected')} disabled={disabled || documents.length === 0}>
          Выбранные документы
        </Button>
      </div>

      <div className="muted small">
        База: {selectedBase.name} · версия: {versionLabel} · документов: {documents.length}
      </div>

      {mode === 'full' ? (
        <Banner tone="info">Проверка будет выполнена по всей выбранной базе знаний.</Banner>
      ) : null}

      {mode === 'selected' ? (
        <div className="stack compact">
          <div className="actions between">
            <div className="muted small">Выбрано документов: {selectedCount}</div>
            <div className="actions">
              <Button type="button" onClick={() => onSelectedDocumentIdsChange(documents.map((item) => item.document_id as string))} disabled={disabled || documents.length === 0}>
                Выбрать все
              </Button>
              <Button type="button" onClick={() => onSelectedDocumentIdsChange([])} disabled={disabled || selectedCount === 0}>
                Очистить
              </Button>
            </div>
          </div>
          {documentsQuery.isLoading ? <LoadingState message="Загружаю документы..." /> : null}
          {documentsQuery.isError ? <ErrorNotice error={documentsQuery.error} fallback="Не удалось загрузить документы базы знаний." /> : null}
          {!documentsQuery.isLoading && !documentsQuery.isError && documents.length === 0 ? (
            <EmptyState title="В выбранной базе нет документов" />
          ) : null}
          {!documentsQuery.isLoading && !documentsQuery.isError && documents.length > 0 ? (
            <div className="timeline">
              {documents.map((document) => {
                const documentId = document.document_id as string;
                const checked = selectedDocumentIds.includes(documentId);
                return (
                  <label className={`timeline-item ${checked ? 'timeline-item-selected' : ''}`} key={documentId}>
                    <div className="actions between">
                      <span className="checkbox-row">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={disabled}
                          onChange={() => toggleDocument(documentId)}
                        />
                        <strong>{document.title}</strong>
                      </span>
                      <div className="actions">
                        {document.role_code ? <Badge value={document.role_code} /> : null}
                        {document.document_type ? <Badge value={String(document.document_type)} /> : null}
                      </div>
                    </div>
                    <div className="muted small">
                      Источник: {document.source_name ?? '—'} · путь или URL: {document.uri ?? '—'}
                    </div>
                  </label>
                );
              })}
            </div>
          ) : null}
          {selectedCount === 0 ? (
            <Banner tone="warning">Выберите хотя бы один документ или переключитесь на проверку по всей базе знаний.</Banner>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
