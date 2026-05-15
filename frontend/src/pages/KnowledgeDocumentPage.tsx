import { type ChangeEvent, useMemo, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { getKnowledgeDocument, getKnowledgeDocumentMemory, getKnowledgeDocumentSnapshot } from '../shared/api/knowledge';
import { queryKeys } from '../shared/api/queryKeys';
import { getApiErrorStatus } from '../shared/api/client';
import { documentTypeLabel, extractedItemTypeLabel, formatDateTime, safeJson, sourceTypeLabel, titleStatus } from '../shared/lib/format';
import { Badge, Banner, Button, Card, CollapsibleCodeBlock, EmptyState, ErrorNotice, ErrorState, LoadingState, PageHeader, Select, StateBox, TabStrip } from '../shared/ui/components';
import type { NormalizedDocumentMemory, NormalizedDocumentSnapshot } from '../shared/api/normalized';
import type { DocumentChunk, ExtractedKnowledgeItem, SourceDocument } from '../types/api';

function useKnowledgeVersionId() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  return params.get('knowledge_version_id') ?? undefined;
}

function isOpenableUri(value?: string | null) {
  if (!value) return false;
  return /^https?:\/\//i.test(value);
}

function resolveChunkTarget(item: ExtractedKnowledgeItem, snapshot: NormalizedDocumentSnapshot | null) {
  if (!snapshot) return null;
  if (item.document_chunk_id) {
    return snapshot.chunks.find((chunk) => chunk.document_chunk_id === item.document_chunk_id) ?? null;
  }
  const sourceLocation = item.source_location?.trim();
  if (!sourceLocation) return null;
  return snapshot.chunks.find((chunk) => chunk.source_location === sourceLocation) ?? null;
}

function jumpToChunk(chunk: DocumentChunk | null, setSelectedChunkId: (value: string) => void) {
  if (!chunk || typeof document === 'undefined') return;
  setSelectedChunkId(chunk.document_chunk_id);
  const element = document.getElementById(`chunk-${chunk.document_chunk_id}`);
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

const UNIFIED_MEMORY_TYPE_ORDER = [
  'mandatory_requirement',
  'integration_requirement',
  'constraint',
  'normative_rule',
  'architectural_principle',
  'technology_standard',
  'entity',
  'entity_relation',
  'term',
  'risk',
  'summary',
];

type DocumentViewMode = 'read' | 'verify' | 'debug';

function cleanKnowledgeText(value?: string | null) {
  return (value ?? '').replace(/\s+/g, ' ').trim();
}

function isLikelyTruncatedKnowledgeText(value?: string | null) {
  const clean = cleanKnowledgeText(value);
  if (clean.endsWith('\u2026')) return true;
  return clean.endsWith('…') || clean.endsWith('...');
}

function sourceSortKey(value?: string | null) {
  const raw = value ?? '';
  const match = raw.match(/(\d+)/);
  return match ? Number(match[1]) : Number.MAX_SAFE_INTEGER;
}

function unifiedTypeOrder(itemType: string) {
  const index = UNIFIED_MEMORY_TYPE_ORDER.indexOf(itemType);
  return index === -1 ? UNIFIED_MEMORY_TYPE_ORDER.length : index;
}

function buildUnifiedMemoryBlocks(memory: NormalizedDocumentMemory) {
  const blocks: Array<{ key: string; title: string; content: string; meta?: string; item?: ExtractedKnowledgeItem }> = [];
  const summary = cleanKnowledgeText(memory.summary);
  if (summary && !isLikelyTruncatedKnowledgeText(summary)) {
    blocks.push({
      key: 'summary',
      title: 'Краткая выжимка',
      content: summary,
      meta: memory.extraction_method ? `Способ извлечения: ${titleStatus(memory.extraction_method) || memory.extraction_method}` : undefined,
    });
  }

  const knowledgeItems = memory.items
    .filter((item) => item.item_type !== 'summary' && cleanKnowledgeText(item.content))
    .sort((left, right) => {
      const byType = unifiedTypeOrder(left.item_type) - unifiedTypeOrder(right.item_type);
      if (byType !== 0) return byType;
      const bySource = sourceSortKey(left.source_location) - sourceSortKey(right.source_location);
      if (bySource !== 0) return bySource;
      return cleanKnowledgeText(left.title).localeCompare(cleanKnowledgeText(right.title));
    });

  knowledgeItems.forEach((item) => {
    const title = cleanKnowledgeText(item.title) || extractedItemTypeLabel(item.item_type);
    const location = item.source_location ? `Источник: ${item.source_location}` : null;
    const confidence = item.confidence_score != null ? `уверенность ${item.confidence_score.toFixed(2)}` : null;
    blocks.push({
      key: item.extracted_item_id,
      title,
      content: cleanKnowledgeText(item.content),
      item,
      meta: [extractedItemTypeLabel(item.item_type), location, confidence].filter(Boolean).join(' · '),
    });
  });

  return blocks;
}

export function KnowledgeDocumentPage() {
  const { documentId = '' } = useParams();
  const knowledgeVersionId = useKnowledgeVersionId();
  const [filterType, setFilterType] = useState('');
  const [filterQuality, setFilterQuality] = useState('');
  const [selectedChunkId, setSelectedChunkId] = useState('');
  const [viewMode, setViewMode] = useState<DocumentViewMode>('read');
  const [expandedEvidenceId, setExpandedEvidenceId] = useState('');

  const documentQuery = useQuery({ queryKey: queryKeys.knowledgeDocument(documentId), queryFn: ({ signal }) => getKnowledgeDocument(documentId, { signal }), enabled: Boolean(documentId) });
  const snapshotQuery = useQuery({ queryKey: queryKeys.knowledgeDocumentSnapshot(documentId, knowledgeVersionId), queryFn: ({ signal }) => getKnowledgeDocumentSnapshot(documentId, knowledgeVersionId, { signal }), enabled: Boolean(documentId) });
  const memoryQuery = useQuery({ queryKey: queryKeys.knowledgeDocumentMemory(documentId, knowledgeVersionId), queryFn: ({ signal }) => getKnowledgeDocumentMemory(documentId, knowledgeVersionId, { signal }), enabled: Boolean(documentId) });

  const snapshotMissing = getApiErrorStatus(snapshotQuery.error) === 404;
  const document = (documentQuery.data ?? null) as SourceDocument | null;
  const snapshot = (snapshotMissing ? null : snapshotQuery.data ?? null) as NormalizedDocumentSnapshot | null;
  const memory = (memoryQuery.data ?? null) as NormalizedDocumentMemory | null;
  const memorySummaryTruncated = isLikelyTruncatedKnowledgeText(memory?.summary);
  const filteredItems = useMemo(
    () => (memory?.items ?? []).filter((item) => (!filterType || item.item_type === filterType) && (!filterQuality || item.quality_status === filterQuality)),
    [filterQuality, filterType, memory?.items],
  );
  const unifiedMemoryBlocks = useMemo(
    () => (memory ? buildUnifiedMemoryBlocks(memory) : []),
    [memory],
  );
  const availableTypes = useMemo(() => Object.keys(memory?.counters ?? {}).sort(), [memory?.counters]);
  const qualityOptions = useMemo(() => Array.from(new Set((memory?.items ?? []).map((item) => item.quality_status))).sort(), [memory?.items]);
  const grouped = useMemo(() => {
    const map = new Map<string, typeof filteredItems>();
    filteredItems.forEach((item) => {
      const key = item.document_chunk_id ?? item.source_location ?? 'document';
      map.set(key, [...(map.get(key) ?? []), item]);
    });
    return map;
  }, [filteredItems]);
  const selectedChunk = useMemo(
    () => (selectedChunkId && snapshot ? snapshot.chunks.find((chunk) => chunk.document_chunk_id === selectedChunkId) ?? null : null),
    [selectedChunkId, snapshot],
  );

  if (documentQuery.isLoading || memoryQuery.isLoading || snapshotQuery.isLoading) {
    return <LoadingState message="Открываю документ и его память…" />;
  }
  if (documentQuery.isError || !document) {
    return <ErrorState message="Не удалось открыть документ." />;
  }
  if (memoryQuery.isError || !memory) {
    return <ErrorState message="Не удалось загрузить память документа." />;
  }
  const resolvedUri = document.resolved_uri ?? document.uri;
  const canOpenResolved = isOpenableUri(resolvedUri);
  const canOpenSource = isOpenableUri(document.uri);
  const showVerificationEvidence = viewMode === 'verify' || viewMode === 'debug';
  const showDebugBlocks = viewMode === 'debug';

  return (
    <div className="stack">
      <PageHeader
        title={document.title}
        subtitle="Просмотр документа, извлечённых знаний и исходных фрагментов, на которые ссылается память документа."
        actions={document.knowledge_base_id ? <Link to={`/knowledge/bases/${document.knowledge_base_id}`} className="button">Назад к базе</Link> : undefined}
      />

      <Card title="Режим просмотра" subtitle="Обычный режим показывает только извлечённые знания; источники и технические данные раскрываются отдельно.">
        <TabStrip>
          <Button type="button" primary={viewMode === 'read'} onClick={() => setViewMode('read')}>Читать</Button>
          <Button type="button" primary={viewMode === 'verify'} onClick={() => setViewMode('verify')}>Проверить источники</Button>
          <Button type="button" primary={viewMode === 'debug'} onClick={() => setViewMode('debug')}>Дебаг</Button>
        </TabStrip>
        <div className="muted small" style={{ marginTop: 8 }}>
          {viewMode === 'read' ? 'Показан единый обзор без фрагментов, JSON и диагностических карточек.' : null}
          {viewMode === 'verify' ? 'Показан обзор вместе с цитатами-основаниями и ссылками на исходные фрагменты.' : null}
          {viewMode === 'debug' ? 'Показаны технические блоки: нормализованный текст, извлечённые элементы, фрагменты и диагностика.' : null}
        </div>
      </Card>

      <div className="grid grid-2">
        <Card title="Карточка документа" subtitle="Откуда взят документ и как он был обработан в базе знаний.">
          <div className="stack compact">
            <div><strong>Тип документа:</strong> {documentTypeLabel(document.document_type)}</div>
            <div><strong>Источник:</strong> {sourceTypeLabel(String(document.source_type ?? document.document_metadata?.source_type ?? '')) || '—'}</div>
            <div><strong>Путь или URL:</strong> <span className="mono">{document.uri}</span></div>
            {document.resolved_uri && document.resolved_uri !== document.uri ? <div><strong>Итоговый путь или URL:</strong> <span className="mono">{document.resolved_uri}</span></div> : null}
            <div><strong>Статус:</strong> <Badge value={document.status} /></div>
            <div><strong>Получен:</strong> {formatDateTime(document.fetched_at ?? document.registered_at)}</div>
            <div><strong>Последняя обработка:</strong> {formatDateTime(document.last_processed_at)}</div>
            <div><strong>Checksum:</strong> <span className="mono">{document.checksum ?? '—'}</span></div>
            <div className="actions">
              {canOpenSource ? <a className="button" href={document.uri} target="_blank" rel="noreferrer">Открыть исходный URL</a> : null}
              {canOpenResolved ? <a className="button" href={resolvedUri ?? undefined} target="_blank" rel="noreferrer">Открыть итоговый URL</a> : null}
            </div>
          </div>
        </Card>

        <Card title="Память документа" subtitle="Что система извлекла из документа и как именно это было получено.">
          <div className="stack compact">
            <div><strong>Сводка:</strong> {memorySummaryTruncated ? 'Сводка сохранена предыдущим извлечением и может быть обрезана; полный поток знаний собран ниже.' : memory.summary ?? '—'}</div>
            <div><strong>Способ извлечения:</strong> {titleStatus(memory.extraction_method) || memory.extraction_method || '—'}</div>
            <div><strong>LLM использовалась:</strong> {memory.llm_attempted ? 'да' : 'нет'} · <strong>резервный режим:</strong> {memory.fallback_applied ? 'да' : 'нет'}</div>
            {memory.fallback_reason ? <div className="muted small">Причина резервного режима: {memory.fallback_reason}</div> : null}
            <div className="actions">
              {availableTypes.map((key) => (
                <span key={key} className="muted small">{extractedItemTypeLabel(key)}: {memory.counters[key]}</span>
              ))}
            </div>
            {showDebugBlocks ? (
              <>
                <div className="grid grid-2">
                  <Select value={filterType} onChange={(event: ChangeEvent<HTMLSelectElement>) => setFilterType(event.target.value)}>
                    <option value="">Все извлечённые элементы</option>
                    {availableTypes.map((key) => (
                      <option key={key} value={key}>{extractedItemTypeLabel(key)} ({memory.counters[key]})</option>
                    ))}
                  </Select>
                  <Select value={filterQuality} onChange={(event: ChangeEvent<HTMLSelectElement>) => setFilterQuality(event.target.value)}>
                    <option value="">Любой статус качества</option>
                    {qualityOptions.map((key) => (
                      <option key={key} value={key}>{titleStatus(key)}</option>
                    ))}
                  </Select>
                </div>
                <div className="muted small">Всего элементов: {memory.items.length}. Сейчас показано: {filteredItems.length}.</div>
              </>
            ) : null}
          </div>
        </Card>
      </div>

      {snapshotMissing ? (
        <Banner tone="warning">
          Для этого документа пока нет сохранённого снимка по выбранной версии знаний. Карточка и извлечённая память доступны, а нормализованный текст и фрагменты появятся после следующей обработки документа.
        </Banner>
      ) : null}

      {snapshotQuery.isError && !snapshotMissing ? (
        <ErrorNotice error={snapshotQuery.error} fallback="Не удалось открыть снимок документа. Карточка документа и извлечённая память остаются доступны." />
      ) : null}

      {memory.fallback_applied ? (
        <Banner tone="warning">
          Для этого документа LLM-извлечение не завершилось штатно, поэтому часть памяти построена в резервном режиме. Подробности видны в диагностике каждого извлечённого элемента.
        </Banner>
      ) : null}

      {selectedChunk ? (
        <Banner tone="info">
          Сейчас выделен фрагмент <strong>{selectedChunk.title ?? `Фрагмент ${selectedChunk.chunk_index}`}</strong> — {selectedChunk.source_location ?? 'позиция не указана'}.
        </Banner>
      ) : null}

      <Card title="Единый обзор знаний" subtitle="Все извлечённые сведения собраны в один читаемый поток, без переходов по типам и ручного поиска по карточкам.">
        {unifiedMemoryBlocks.length === 0 ? (
          <EmptyState title="Пока нет извлечённых знаний" description="После успешного LLM extraction здесь появится единый обзор документа." />
        ) : (
          <div className="stack compact">
            {unifiedMemoryBlocks.map((block) => {
              const chunk = block.item ? resolveChunkTarget(block.item, snapshot) : null;
              const evidenceExpanded = showVerificationEvidence || expandedEvidenceId === block.key;
              return (
                <article className="section-box" key={block.key}>
                  <div className="actions between">
                    <strong>{block.title}</strong>
                    {block.meta ? <span className="muted small">{block.meta}</span> : null}
                  </div>
                  <div className="pre-wrap" style={{ marginTop: 8 }}>{block.content}</div>
                  {block.item && !showVerificationEvidence ? (
                    <div className="actions" style={{ marginTop: 8 }}>
                      <Button type="button" onClick={() => setExpandedEvidenceId(evidenceExpanded ? '' : block.key)}>
                        {evidenceExpanded ? 'Скрыть источник' : 'Показать источник'}
                      </Button>
                    </div>
                  ) : null}
                  {block.item && chunk && showDebugBlocks ? (
                    <div className="actions" style={{ marginTop: 8 }}>
                      <Button type="button" onClick={() => jumpToChunk(chunk, setSelectedChunkId)}>Открыть фрагмент</Button>
                    </div>
                  ) : null}
                  {block.item && evidenceExpanded ? (
                    <StateBox className="with-top-margin-sm">
                      {block.item.evidence_quote ? <div className="pre-wrap">{block.item.evidence_quote}</div> : <div className="muted">Для этого пункта нет отдельной цитаты-основания.</div>}
                      {chunk ? <div className="muted small" style={{ marginTop: 8 }}>Фрагмент: {chunk.title ?? `Фрагмент ${chunk.chunk_index}`} · {chunk.source_location ?? 'позиция не указана'}</div> : null}
                      {chunk ? <div className="pre-wrap muted small" style={{ marginTop: 8 }}>{chunk.content}</div> : null}
                    </StateBox>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </Card>

      {showDebugBlocks ? (
      <>
      <div className="two-col">
        <Card title="Нормализованный текст" subtitle={snapshot ? `Парсер: ${snapshot.parser_name} · формат: ${snapshot.content_format}` : 'Снимок ещё не сформирован'}>
          {snapshot ? (
            <div className="section-box preserve-lines" style={{ maxHeight: 720, overflow: 'auto' }}>
              {snapshot.normalized_text}
            </div>
          ) : (
            <EmptyState title="Снимок пока недоступен" description="После переиндексации или очередного обновления знаний здесь появится нормализованный текст документа." />
          )}
        </Card>

        <Card title="Извлечённые элементы" subtitle="Можно отфильтровать найденные факты и перейти к исходному фрагменту документа.">
          {filteredItems.length === 0 ? <EmptyState title="По выбранным фильтрам ничего не найдено" /> : (
            <div className="stack compact">
              {filteredItems.map((item) => {
                const chunk = resolveChunkTarget(item, snapshot);
                return (
                  <div className="section-box" key={item.extracted_item_id}>
                    <div className="actions between">
                      <strong>{item.title ?? extractedItemTypeLabel(item.item_type)}</strong>
                      <span className="muted small">{titleStatus(item.quality_status)}</span>
                    </div>
                    <div className="muted small">Тип: {extractedItemTypeLabel(item.item_type)} · уверенность: {item.confidence_score != null ? item.confidence_score.toFixed(2) : '—'}</div>
                    <div className="pre-wrap" style={{ marginTop: 8 }}>{item.content}</div>
                    {item.evidence_quote ? <div className="muted small" style={{ marginTop: 8 }}>Цитата-основание: {item.evidence_quote}</div> : null}
                    {item.structured_payload ? <CollapsibleCodeBlock style={{ marginTop: 8 }}>{safeJson(item.structured_payload)}</CollapsibleCodeBlock> : null}
                    {chunk ? <Button type="button" onClick={() => jumpToChunk(chunk, setSelectedChunkId)}>Перейти к фрагменту</Button> : null}
                  </div>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      <Card title="Фрагменты снимка" subtitle={snapshot ? `Всего фрагментов: ${snapshot.chunks.length}` : 'Снимок ещё не сформирован'}>
        {!snapshot ? <EmptyState title="Фрагменты пока не сохранены" description="Когда сервер сформирует снимок, здесь появятся исходные фрагменты документа." /> : (
          snapshot.chunks.length === 0 ? <EmptyState title="Фрагменты ещё не сохранены" /> : (
            <div className="stack compact">
              {snapshot.chunks.map((chunk) => {
                const attachedItems = grouped.get(chunk.document_chunk_id) ?? grouped.get(chunk.source_location ?? '') ?? [];
                const active = selectedChunkId === chunk.document_chunk_id;
                return (
                  <div className={`section-box ${active ? 'chunk-selected' : ''}`.trim()} key={chunk.document_chunk_id} id={`chunk-${chunk.document_chunk_id}`}>
                    <div className="actions between">
                      <strong>{chunk.title ?? `Фрагмент ${chunk.chunk_index}`}</strong>
                      <Button type="button" onClick={() => jumpToChunk(chunk, setSelectedChunkId)}>{active ? 'Выбран' : 'Выделить'}</Button>
                    </div>
                    <div className="muted small">{chunk.source_location ?? 'позиция не указана'} · символы {chunk.start_offset ?? '—'}–{chunk.end_offset ?? '—'}</div>
                    {attachedItems.length ? <div className="muted small">Связанных извлечённых элементов: {attachedItems.length}</div> : null}
                    <div className="pre-wrap preserve-lines" style={{ marginTop: 8 }}>{chunk.content}</div>
                  </div>
                );
              })}
            </div>
          )
        )}
      </Card>
      </>
      ) : null}
    </div>
  );
}
