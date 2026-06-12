import type { KnowledgeVersion } from '../../types/api';

const GENERATION_SELECTABLE_VERSION_STATUSES = new Set(['active', 'validated']);

const ALLOWED_SOURCE_STATUS_TRANSITIONS: Record<string, string[]> = {
  draft: ['draft', 'active', 'disabled'],
  active: ['active', 'disabled'],
  unavailable: ['unavailable', 'active', 'disabled'],
  disabled: ['disabled', 'active'],
  archived: ['archived'],
};

export const KNOWLEDGE_REFRESH_POLICY_OPTIONS = [
  { value: 'monthly', label: 'Авто: раз в месяц' },
  { value: 'weekly', label: 'Авто: раз в неделю' },
  { value: 'manual', label: 'Только вручную' },
] as const;

function isGenerationSelectableVersion(version: Pick<KnowledgeVersion, 'status'>): boolean {
  return GENERATION_SELECTABLE_VERSION_STATUSES.has(version.status);
}

export function selectableKnowledgeVersions(versions: KnowledgeVersion[]): KnowledgeVersion[] {
  return versions.filter(isGenerationSelectableVersion);
}

export function allowedSourceStatuses(status?: string | null): string[] {
  return ALLOWED_SOURCE_STATUS_TRANSITIONS[status ?? 'draft'] ?? ['draft'];
}
