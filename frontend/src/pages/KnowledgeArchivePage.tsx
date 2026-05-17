import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getKnowledgeBaseDocuments, getKnowledgeBases, restoreKnowledgeBase, restoreKnowledgeDocument, restoreSource } from '../shared/api/knowledge';
import { cleanDisplayFileName, formatDateTime, knowledgeBaseKindLabel, titleStatus } from '../shared/lib/format';
import { Badge, Banner, Button, Card, EmptyState, ErrorNotice, LoadingState, PageHeader } from '../shared/ui/components';
import type { KnowledgeBase, KnowledgeBaseDocument } from '../types/api';

type ArchivedKnowledgeBaseDocument = KnowledgeBaseDocument & {
  source_status?: string | null;
};

function documentDisplayTitle(document: KnowledgeBaseDocument) {
  return cleanDisplayFileName(document.title) ?? cleanDisplayFileName(document.uri) ?? 'Документ';
}

function isArchivedDocument(document: ArchivedKnowledgeBaseDocument) {
  const documentArchived = document.document_status === 'archived';
  const sourceArchived = document.source_status === 'archived';
  const removedWithoutLiveDocumentStatus = (
    document.present_in_version === false
    || document.delta_kind === 'deleted'
  ) && !document.document_status;
  return (
    documentArchived
    || sourceArchived
    || removedWithoutLiveDocumentStatus
  );
}

function ArchivedDocumentsForBase({ base }: { base: KnowledgeBase }) {
  const queryClient = useQueryClient();
  const [restoreNotice, setRestoreNotice] = useState<string | null>(null);
  const documentsQuery = useQuery({
    queryKey: ['knowledge-archive-documents', base.knowledge_base_id, base.active_knowledge_version_id ?? null],
    queryFn: ({ signal }) => getKnowledgeBaseDocuments(base.knowledge_base_id, {
      knowledge_version_id: base.active_knowledge_version_id || undefined,
      include_deleted: true,
      include_archived_base: true,
      signal,
    }),
    enabled: Boolean(base.knowledge_base_id),
    staleTime: 5_000,
  });

  const restoreDocumentMutation = useMutation({
    mutationFn: async (document: ArchivedKnowledgeBaseDocument) => {
      if (base.status === 'archived') {
        await restoreKnowledgeBase(base.knowledge_base_id);
      }
      if (document.source_id) {
        await restoreSource(document.source_id);
      }
      return restoreKnowledgeDocument(document.document_id as string, { reason: 'restore_from_archive_page' });
    },
    onSuccess: (_, document) => {
      setRestoreNotice(`Документ «${documentDisplayTitle(document)}» возвращён из архива. Запустите обновление базы, чтобы включить его в новую версию знаний.`);
      queryClient.invalidateQueries({ queryKey: ['knowledge-archive-documents'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases-archive'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases-selector'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-versions-selector'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-base', base.knowledge_base_id] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-base-documents', base.knowledge_base_id] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-base-sources', base.knowledge_base_id] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-document'] });
    },
  });

  const archivedDocuments = ((documentsQuery.data ?? []) as ArchivedKnowledgeBaseDocument[]).filter(isArchivedDocument);

  return (
    <div className="timeline-item">
      <div className="actions between">
        <div>
          <strong>{base.name}</strong>
          <div className="muted small">{knowledgeBaseKindLabel(base.kind)} · активная версия: {base.active_version_no ?? '—'} · статус: {titleStatus(base.status)}</div>
        </div>
        <div className="actions">
          <Badge value={base.status} />
          <Link className="button" to={`/knowledge/bases/${base.knowledge_base_id}`}>Открыть базу</Link>
        </div>
      </div>

      {documentsQuery.isLoading ? <LoadingState message="Загружаю архив документов…" /> : null}
      {documentsQuery.isError ? <ErrorNotice error={documentsQuery.error} fallback="Не удалось загрузить архивные документы базы." /> : null}
      {restoreDocumentMutation.isError ? <ErrorNotice error={restoreDocumentMutation.error} fallback="Не удалось разархивировать документ." /> : null}
      {restoreNotice ? <Banner tone="warning">{restoreNotice}</Banner> : null}
      {!documentsQuery.isLoading && !documentsQuery.isError && archivedDocuments.length === 0 ? (
        <div className="muted small">Архивных документов в активной истории этой базы не найдено.</div>
      ) : null}
      {archivedDocuments.length > 0 ? (
        <div className="timeline" style={{ marginTop: 12 }}>
          {archivedDocuments.map((document) => {
            const title = documentDisplayTitle(document);
            const canRestore = Boolean(document.document_id);
            return (
              <div className="timeline-item" key={`${document.document_id ?? document.uri}:${document.delta_kind ?? 'archive'}`}>
                <div className="actions between">
                  <strong>{title}</strong>
                  <div className="actions">
                    {document.delta_kind ? <Badge value={document.delta_kind} /> : null}
                    {document.document_status ? <Badge value={document.document_status} /> : null}
                  </div>
                </div>
                <div className="muted small">Источник: {document.source_name ?? '—'} · тип: {document.document_type ?? '—'} · зарегистрирован: {formatDateTime(document.registered_at)}</div>
                <div className="actions">
                  {document.document_id ? <Link className="button" to={`/knowledge/documents/${document.document_id}?knowledge_version_id=${encodeURIComponent(document.knowledge_version_id)}`}>Открыть документ</Link> : null}
                  {canRestore ? (
                    <Button
                      onClick={() => {
                        const message = base.status === 'archived'
                          ? `Разархивировать базу «${base.name}» и документ «${title}»? После этого нужно обновить базу знаний.`
                          : `Разархивировать документ «${title}»? После этого нужно обновить базу знаний.`;
                        if (window.confirm(message)) {
                          setRestoreNotice(null);
                          restoreDocumentMutation.mutate(document);
                        }
                      }}
                      disabled={restoreDocumentMutation.isPending}
                    >
                      {restoreDocumentMutation.isPending
                        ? 'Возвращаю…'
                        : base.status === 'archived' ? 'Разархивировать базу и документ' : 'Разархивировать'}
                    </Button>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function KnowledgeArchivePage() {
  const queryClient = useQueryClient();
  const basesQuery = useQuery({
    queryKey: ['knowledge-bases-archive'],
    queryFn: ({ signal }) => getKnowledgeBases({ signal, include_archived: true }),
    staleTime: 10_000,
  });

  const restoreBaseMutation = useMutation({
    mutationFn: (knowledgeBaseId: string) => restoreKnowledgeBase(knowledgeBaseId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases-archive'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases-selector'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-knowledge-bases'] });
    },
  });

  const bases = (basesQuery.data ?? []) as KnowledgeBase[];
  const archivedBases = bases.filter((base) => base.status === 'archived');
  const userBases = bases.filter((base) => base.kind === 'user_managed');

  return (
    <div className="stack">
      <PageHeader
        title="Архив базы знаний"
        subtitle="Здесь остаются архивированные базы и документы, исключённые из активного состава. Их можно вернуть без повторной загрузки файла."
        actions={<Link to="/knowledge" className="button">Назад к базам</Link>}
      />

      {basesQuery.isLoading ? <LoadingState message="Загружаю архив…" /> : null}
      {basesQuery.isError ? <ErrorNotice error={basesQuery.error} fallback="Не удалось загрузить архив базы знаний." /> : null}
      {restoreBaseMutation.isError ? <ErrorNotice error={restoreBaseMutation.error} fallback="Не удалось разархивировать базу знаний." /> : null}
      {restoreBaseMutation.isSuccess ? <Banner tone="warning">База возвращена из архива. Если нужно снова использовать её в генерации, выберите её на странице базы.</Banner> : null}

      <Card title="Архивированные базы" subtitle="Архивная база скрыта из рабочих списков и не используется в генерации решений.">
        {archivedBases.length === 0 && !basesQuery.isLoading ? <EmptyState title="Архивированных баз пока нет" /> : null}
        {archivedBases.length > 0 ? (
          <div className="timeline">
            {archivedBases.map((base) => (
              <div className="timeline-item" key={base.knowledge_base_id}>
                <div className="actions between">
                  <div>
                    <strong>{base.name}</strong>
                    <div className="muted small">{knowledgeBaseKindLabel(base.kind)} · документов: {base.document_count ?? 0} · последнее обновление: {formatDateTime(base.latest_sync_at)}</div>
                  </div>
                  <Badge value={base.status} />
                </div>
                {base.description ? <div>{base.description}</div> : null}
                <div className="actions">
                  <Link className="button" to={`/knowledge/bases/${base.knowledge_base_id}`}>Открыть базу</Link>
                  <Button primary onClick={() => restoreBaseMutation.mutate(base.knowledge_base_id)} disabled={restoreBaseMutation.isPending}>
                    {restoreBaseMutation.isPending ? 'Возвращаю…' : 'Разархивировать базу'}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </Card>

      <Card title="Архив документов" subtitle="Документы остаются привязанными к своей базе. После разархивации нужно запустить обновление базы, чтобы новая версия снова включила документ.">
        {userBases.length === 0 && !basesQuery.isLoading ? <EmptyState title="Пользовательских баз пока нет" /> : null}
        {userBases.length > 0 ? (
          <div className="timeline">
            {userBases.map((base) => <ArchivedDocumentsForBase key={base.knowledge_base_id} base={base} />)}
          </div>
        ) : null}
      </Card>
    </div>
  );
}
