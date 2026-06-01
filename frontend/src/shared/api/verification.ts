import { apiUrl, request, type RequestOptions } from './client';
import type { paths, SuccessJson } from '../../generated/openapi';
import { normalizeVerificationProtocol, normalizeVerificationRun } from './normalized';

type VerificationRunResponse = SuccessJson<paths['/solutions/{solution_version_id}/verification-runs']['post']>;
type VerificationRunStatusResponse = SuccessJson<paths['/verification-runs/{verification_run_id}']['get']>;
type VerificationProtocolResponse = SuccessJson<paths['/verification-protocols/{protocol_id}']['get']>;
type VerificationProtocolRenderedResponse = SuccessJson<paths['/verification-protocols/{protocol_id}/rendered']['get']>;
type VerificationProtocolsRegistryResponse = SuccessJson<paths['/verification-protocols']['get']>;
type VerificationProtocolViolationsResponse = SuccessJson<paths['/verification-protocols/{protocol_id}/violations']['get']>;

export interface ExternalArchitectureCheckPayload {
  title: string;
  architecture_text: string;
  source_ref?: string | null;
  draft_task_id?: string | null;
  knowledge_document_ids?: string[];
  idempotency_key?: string | null;
  correlation_id?: string | null;
}

export interface ExternalArchitectureCheckResult {
  task_id: string;
  solution_version_id: string;
  generation_run_id: string;
  publication_artifact_id?: string | null;
  verification_run_id: string;
  protocol_id?: string | null;
  verification_state: string;
  summary_status?: string | null;
  knowledge_version_id: string;
}

export async function startVerificationRun(solutionVersionId: string, payload?: { idempotency_key?: string; correlation_id?: string; knowledge_document_ids?: string[] }) {
  return normalizeVerificationRun(await request<VerificationRunResponse>(`/solutions/${solutionVersionId}/verification-runs`, {
    method: 'POST',
    body: JSON.stringify(payload ?? {}),
  }));
}

export function checkExternalArchitecture(payload: ExternalArchitectureCheckPayload) {
  return request<ExternalArchitectureCheckResult>('/external-architectures/check', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function getVerificationRun(verificationRunId: string, options?: RequestOptions) {
  return normalizeVerificationRun(await request<VerificationRunStatusResponse>(`/verification-runs/${verificationRunId}`, options));
}

export async function cancelVerificationRun(verificationRunId: string) {
  return normalizeVerificationRun(await request<VerificationRunStatusResponse>(`/verification-runs/${verificationRunId}/cancel`, {
    method: 'POST',
  }));
}

export async function getVerificationProtocol(protocolId: string, options?: RequestOptions) {
  return normalizeVerificationProtocol(await request<VerificationProtocolResponse>(`/verification-protocols/${protocolId}`, options));
}

export function getVerificationProtocolRendered(protocolId: string, options?: RequestOptions) {
  return request<VerificationProtocolRenderedResponse>(`/verification-protocols/${protocolId}/rendered`, options);
}

export function getVerificationProtocolsRegistry(filters?: { solution_version_id?: string; summary_status?: string; knowledge_version_id?: string; limit?: number }, options?: RequestOptions) {
  return request<VerificationProtocolsRegistryResponse>('/verification-protocols', options, filters);
}

export async function getVerificationProtocolViolations(protocolId: string, options?: RequestOptions) {
  const response = await request<VerificationProtocolViolationsResponse>(`/verification-protocols/${protocolId}/violations`, options);
  return {
    ...response,
    violations: Array.isArray(response.violations) ? response.violations : [],
  } as VerificationProtocolViolationsResponse;
}

export function verificationProtocolExportUrl(protocolId: string, format: 'pdf' | 'docx' | 'odt' | 'archimate') {
  return apiUrl(`/verification-protocols/${protocolId}/export/${format}`);
}
