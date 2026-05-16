import { request, type RequestOptions } from './client';
import type { paths, SuccessJson } from '../../generated/openapi';
import { normalizeDocumentMemory, normalizeDocumentSnapshot } from './normalized';

type ActiveKnowledgeVersionResponse = SuccessJson<paths['/knowledge/versions/active']['get']>;
type KnowledgeBasesResponse = SuccessJson<paths['/knowledge/bases']['get']>;
type KnowledgeBaseResponse = SuccessJson<paths['/knowledge/bases/{knowledge_base_id}']['get']>;
type KnowledgeBaseDocumentsResponse = SuccessJson<paths['/knowledge/bases/{knowledge_base_id}/documents']['get']>;
type SourcesResponse = SuccessJson<paths['/knowledge/sources']['get']>;
type SourceResponse = SuccessJson<paths['/knowledge/sources']['post']>;
type KnowledgeDocumentResponse = SuccessJson<paths['/knowledge/documents/{document_id}']['get']>;
type KnowledgeDocumentSnapshotResponse = SuccessJson<paths['/knowledge/documents/{document_id}/snapshot']['get']>;
type KnowledgeDocumentMemoryResponse = SuccessJson<paths['/knowledge/documents/{document_id}/memory']['get']>;
type KnowledgeDocumentRemovalResponse = SuccessJson<paths['/knowledge/documents/{document_id}/remove']['post']>;
type KnowledgeVersionsResponse = SuccessJson<paths['/knowledge/versions']['get']>;
type KnowledgeVersionResponse = SuccessJson<paths['/knowledge/versions/{knowledge_version_id}/activate']['post']>;
type KnowledgeUpdateRunsResponse = SuccessJson<paths['/knowledge/update-runs']['get']>;
type KnowledgeUpdateRunResponse = SuccessJson<paths['/knowledge/update-runs']['post']>;
type KnowledgeUpdateRunStatusResponse = SuccessJson<paths['/knowledge/update-runs/{update_run_id}/status']['get']>;
type ScheduledKnowledgeSyncResponse = SuccessJson<paths['/knowledge/update-runs/scheduled/execute']['post']>;
type KnowledgeNotificationsResponse = SuccessJson<paths['/knowledge/notifications']['get']>;
type KnowledgeUploadResponse = SuccessJson<paths['/knowledge/uploads']['post']>;
type KnowledgeUploadBatchResponse = SuccessJson<paths['/knowledge/uploads/ingest-batch']['post']>;

export function getActiveKnowledgeVersion(options?: RequestOptions) {
  return request<ActiveKnowledgeVersionResponse>('/knowledge/versions/active', options);
}

export function getKnowledgeBases(options?: RequestOptions) {
  return request<KnowledgeBasesResponse>('/knowledge/bases', options);
}

export function createKnowledgeBase(payload: { name: string; description?: string | null }) {
  return request<KnowledgeBaseResponse>('/knowledge/bases', { method: 'POST', body: JSON.stringify(payload) });
}

export function getKnowledgeBase(knowledgeBaseId: string, options?: RequestOptions) {
  return request<KnowledgeBaseResponse>(`/knowledge/bases/${knowledgeBaseId}`, options);
}

export function selectKnowledgeBase(knowledgeBaseId: string, knowledgeVersionId?: string | null) {
  return request<KnowledgeBaseResponse>(`/knowledge/bases/${knowledgeBaseId}/select`, {
    method: 'POST',
    body: JSON.stringify({ knowledge_version_id: knowledgeVersionId ?? null }),
  });
}

export function getKnowledgeBaseDocuments(
  knowledgeBaseId: string,
  options?: { knowledge_version_id?: string | null; include_deleted?: boolean; signal?: AbortSignal },
) {
  return request<KnowledgeBaseDocumentsResponse>(`/knowledge/bases/${knowledgeBaseId}/documents`, { signal: options?.signal }, {
    knowledge_version_id: options?.knowledge_version_id ?? undefined,
    include_deleted: options?.include_deleted == null ? undefined : Number(options.include_deleted),
  });
}

export function getSources(knowledgeBaseId?: string, options?: RequestOptions) {
  return request<SourcesResponse>('/knowledge/sources', options, { knowledge_base_id: knowledgeBaseId });
}

export function createSource(payload: { knowledge_base_id?: string | null; source_type: string; name?: string | null; base_uri?: string | null; criticality: string; refresh_policy?: string | null; sync_mode?: string; source_metadata?: Record<string, unknown> | null }) {
  return request<SourceResponse>('/knowledge/sources', { method: 'POST', body: JSON.stringify(payload) });
}

export function updateSource(sourceId: string, payload: { name?: string | null; base_uri?: string | null; criticality?: string; status?: string; refresh_policy?: string | null; sync_mode?: string; source_metadata?: Record<string, unknown> | null }) {
  return request<SourceResponse>(`/knowledge/sources/${sourceId}`, { method: 'PATCH', body: JSON.stringify(payload) });
}

export function archiveSource(sourceId: string) {
  return request<SourceResponse>(`/knowledge/sources/${sourceId}/archive`, { method: 'POST', body: '{}' });
}

export function disableSource(sourceId: string) {
  return request<SourceResponse>(`/knowledge/sources/${sourceId}/disable`, { method: 'POST', body: '{}' });
}

export function getKnowledgeDocument(documentId: string, options?: RequestOptions) {
  return request<KnowledgeDocumentResponse>(`/knowledge/documents/${documentId}`, options);
}

export async function getKnowledgeDocumentSnapshot(documentId: string, knowledgeVersionId?: string | null, options?: RequestOptions) {
  return normalizeDocumentSnapshot(await request<KnowledgeDocumentSnapshotResponse>(`/knowledge/documents/${documentId}/snapshot`, options, { knowledge_version_id: knowledgeVersionId ?? undefined }));
}

export async function getKnowledgeDocumentMemory(documentId: string, knowledgeVersionId?: string | null, options?: RequestOptions) {
  return normalizeDocumentMemory(await request<KnowledgeDocumentMemoryResponse>(`/knowledge/documents/${documentId}/memory`, options, { knowledge_version_id: knowledgeVersionId ?? undefined }));
}

export function removeKnowledgeDocument(documentId: string, options?: { execute_inline?: boolean; execute_update_inline?: boolean; reason?: string | null }) {
  const executeInline = options?.execute_inline ?? options?.execute_update_inline;
  return request<KnowledgeDocumentRemovalResponse>(`/knowledge/documents/${documentId}/remove`, {
    method: 'POST',
    body: JSON.stringify({
      execute_inline: executeInline ?? null,
      reason: options?.reason ?? null,
    }),
  });
}

export function getKnowledgeVersions(knowledgeBaseId?: string, options?: RequestOptions) {
  return request<KnowledgeVersionsResponse>('/knowledge/versions', options, { knowledge_base_id: knowledgeBaseId });
}

export function activateKnowledgeVersion(versionId: string, reason?: string) {
  return request<KnowledgeVersionResponse>(`/knowledge/versions/${versionId}/activate`, { method: 'POST', body: JSON.stringify({ reason }) });
}

export function getUpdateRuns(limit = 20, options?: { knowledge_base_id?: string | null; status?: string | null; signal?: AbortSignal }) {
  return request<KnowledgeUpdateRunsResponse>('/knowledge/update-runs', { signal: options?.signal }, {
    limit,
    knowledge_base_id: options?.knowledge_base_id ?? undefined,
    status: options?.status ?? undefined,
  });
}

export function getUpdateRunStatus(updateRunId: string, options?: RequestOptions) {
  return request<KnowledgeUpdateRunStatusResponse>(`/knowledge/update-runs/${updateRunId}/status`, options);
}

export function startKnowledgeUpdate(payload: {
  knowledge_base_id?: string | null;
  run_type?: string;
  source_scope?: 'all' | 'selected';
  selected_source_ids?: string[];
  document_ids?: string[];
  removed_document_ids?: string[];
  force_reindex_all_in_scope?: boolean;
  force_reindex_document_ids?: string[];
  target_embedding_profile?: string | null;
  reason?: string;
  requested_by?: string;
  idempotency_key?: string;
  execute_inline?: boolean | null;
  execute_update_inline?: boolean | null;
}) {
  return request<KnowledgeUpdateRunResponse>('/knowledge/update-runs', { method: 'POST', body: JSON.stringify(payload ?? {}) });
}

export function syncKnowledgeBase(knowledgeBaseId: string, options?: { execute_inline?: boolean; reason?: string | null }) {
  return request<KnowledgeUpdateRunResponse>(`/knowledge/bases/${knowledgeBaseId}/sync`, { method: 'POST', body: '{}' }, {
    execute_inline: options?.execute_inline == null ? undefined : Number(options.execute_inline),
    reason: options?.reason ?? undefined,
  });
}

export function executeScheduledKnowledgeSyncs() {
  return request<ScheduledKnowledgeSyncResponse>('/knowledge/update-runs/scheduled/execute', { method: 'POST', body: '{}' });
}

export function getKnowledgeNotifications(limit = 20, knowledgeBaseId?: string | null, options?: RequestOptions) {
  return request<KnowledgeNotificationsResponse>('/knowledge/notifications', options, {
    limit,
    knowledge_base_id: knowledgeBaseId ?? undefined,
  });
}

export async function uploadKnowledgeFile(payload: { file: File; title?: string; knowledge_base_id?: string; refresh_policy?: string | null; source_status?: string | null }) {
  const formData = new FormData();
  formData.append('file', payload.file);
  if (payload.title?.trim()) formData.append('title', payload.title.trim());
  if (payload.knowledge_base_id) formData.append('knowledge_base_id', payload.knowledge_base_id);
  if (payload.refresh_policy?.trim()) formData.append('refresh_policy', payload.refresh_policy.trim());
  if (payload.source_status?.trim()) formData.append('source_status', payload.source_status.trim());
  return request<KnowledgeUploadResponse>('/knowledge/uploads', {
    method: 'POST',
    body: formData,
  });
}

export async function uploadAndIngestKnowledgeFiles(payload: {
  files: File[];
  title?: string;
  knowledge_base_id?: string;
  refresh_policy?: string | null;
  source_status?: string | null;
  execute_update_inline?: boolean | null;
  reason?: string | null;
}) {
  const formData = new FormData();
  payload.files.forEach((file) => formData.append('files', file));
  if (payload.title?.trim()) formData.append('title', payload.title.trim());
  if (payload.knowledge_base_id) formData.append('knowledge_base_id', payload.knowledge_base_id);
  if (payload.refresh_policy?.trim()) formData.append('refresh_policy', payload.refresh_policy.trim());
  if (payload.source_status?.trim()) formData.append('source_status', payload.source_status.trim());
  if (payload.execute_update_inline != null) {
    formData.append('execute_update_inline', String(payload.execute_update_inline));
  }
  if (payload.reason?.trim()) formData.append('reason', payload.reason.trim());
  return request<KnowledgeUploadBatchResponse>('/knowledge/uploads/ingest-batch', {
    method: 'POST',
    body: formData,
  });
}
