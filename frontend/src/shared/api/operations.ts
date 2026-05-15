import { request, type RequestOptions } from './client';
import type { paths, SuccessJson } from '../../generated/openapi';
import { normalizeOperationDetail } from './normalized';

type OperationMetricsResponse = SuccessJson<paths['/operations/metrics']['get']>;
type OperationsResponse = SuccessJson<paths['/operations']['get']>;
type OperationDetailResponse = SuccessJson<paths['/operations/{operation_id}']['get']>;
type AuditEventsResponse = SuccessJson<paths['/audit-events']['get']>;

export function getOperationMetrics(options?: RequestOptions) {
  return request<OperationMetricsResponse>('/operations/metrics', options);
}

export function getOperations(filters?: {
  limit?: number;
  operation_kind?: string;
  status?: string;
  correlation_id?: string;
  solution_version_id?: string;
  verification_protocol_id?: string;
  knowledge_version_id?: string;
}, options?: RequestOptions) {
  return request<OperationsResponse>('/operations', options, filters);
}

export async function getOperationDetail(operationId: string, options?: RequestOptions) {
  return normalizeOperationDetail(await request<OperationDetailResponse>(`/operations/${operationId}`, options));
}

export function getAuditEvents(limit = 50, options?: RequestOptions) {
  return request<AuditEventsResponse>('/audit-events', options, { limit });
}
