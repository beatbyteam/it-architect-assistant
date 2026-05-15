export function isTerminal(state?: string | null) {
  return ['completed', 'failed', 'canceled'].includes(state ?? '');
}

export function diagnosticsOperationId(diagnostics?: Record<string, unknown> | null) {
  const value = diagnostics?.operation_id ?? diagnostics?.run_operation_id ?? diagnostics?.operation_ref;
  return typeof value === 'string' ? value : null;
}

export function sectionScorePercent(value?: number | null) {
  if (typeof value !== 'number' || Number.isNaN(value)) return '—';
  return `${Math.round(value * 100)}%`;
}

export function normalizeArray<T>(value: T[] | null | undefined) {
  return Array.isArray(value) ? value : [];
}
