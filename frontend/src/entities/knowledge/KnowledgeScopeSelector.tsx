import { type ChangeEvent, useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getKnowledgeBases, getKnowledgeVersions, selectKnowledgeBase } from '../../shared/api/knowledge';
import { getTasks } from '../../shared/api/tasks';
import { GENERATION_SELECTION_LOCK_REASON, hasRunningGeneration } from './generationSelectionLock';
import { selectableKnowledgeVersions } from './policies';
import { formatKnowledgeVersionLabel, knowledgeBaseKindLabel } from '../../shared/lib/format';
import { Badge, Banner, Button, ErrorNotice, FormRow, LoadingState, Select } from '../../shared/ui/components';
import type { KnowledgeBase, KnowledgeVersion } from '../../types/api';

export function KnowledgeScopeSelector(props: {
  title?: string;
  description?: string;
  compact?: boolean;
  disabled?: boolean;
  disabledReason?: string;
  onApplied?: (payload: { baseId: string; versionId?: string | null }) => void;
}) {
  const queryClient = useQueryClient();
  const basesQuery = useQuery({ queryKey: ['knowledge-bases-selector'], queryFn: ({ signal }) => getKnowledgeBases({ signal }), staleTime: 15_000 });
  const generationLockQuery = useQuery({
    queryKey: ['knowledge-selection-generation-lock'],
    queryFn: ({ signal }) => getTasks({ limit: 100 }, { signal }),
    staleTime: 2_000,
    refetchInterval: 5_000,
  });
  const [selectedBaseId, setSelectedBaseId] = useState('');
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [versionDirty, setVersionDirty] = useState(false);

  const selectedBase = useMemo(
    () => (basesQuery.data ?? []).find((item: KnowledgeBase) => item.knowledge_base_id === selectedBaseId) ?? null,
    [basesQuery.data, selectedBaseId],
  );

  const versionsQuery = useQuery({
    queryKey: ['knowledge-versions-selector', selectedBaseId],
    queryFn: ({ signal }) => getKnowledgeVersions(selectedBaseId, { signal }),
    enabled: Boolean(selectedBaseId) && selectedBase?.kind === 'user_managed',
    staleTime: 15_000,
  });

  useEffect(() => {
    const selectedUserBase = (basesQuery.data ?? []).find((item: KnowledgeBase) => item.selected_for_generation && item.kind === 'user_managed') ?? null;
    const mandatoryOnlyBase = (basesQuery.data ?? []).find((item: KnowledgeBase) => item.selected_for_generation && item.kind === 'system_mandatory') ?? null;
    const selected = selectedUserBase ?? mandatoryOnlyBase;
    if (selected) {
      setSelectedBaseId((current: string) => current || selected.knowledge_base_id);
      setSelectedVersionId((current: string) => current || (selected.kind === 'user_managed' ? selected.selected_knowledge_version_id || '' : ''));
      return;
    }
    const firstUserBase = (basesQuery.data ?? []).find((item: KnowledgeBase) => item.kind === 'user_managed') ?? null;
    if (firstUserBase && !selectedBaseId) {
      setSelectedBaseId(firstUserBase.knowledge_base_id);
      setSelectedVersionId(firstUserBase.selected_knowledge_version_id ?? '');
    }
  }, [basesQuery.data, selectedBaseId]);

  useEffect(() => {
    if (!selectedBase) return;
    if (selectedBase.kind !== 'user_managed') {
      if (selectedVersionId) setSelectedVersionId('');
      setVersionDirty(false);
      return;
    }
    const available = selectableKnowledgeVersions(versionsQuery.data ?? []);
    if (!available.length) {
      setSelectedVersionId('');
      setVersionDirty(false);
      return;
    }
    if (selectedVersionId && !available.some((item: KnowledgeVersion) => item.knowledge_version_id === selectedVersionId)) {
      setSelectedVersionId(selectedBase.selected_knowledge_version_id || '');
      setVersionDirty(false);
    }
  }, [selectedBase?.knowledge_base_id, selectedBase?.selected_knowledge_version_id, versionsQuery.data, selectedVersionId]);

  const applyMutation = useMutation({
    mutationFn: async () => {
      if (!selectedBaseId) throw new Error('Выбери режим базы знаний.');
      return selectKnowledgeBase(
        selectedBaseId,
        selectedBase?.kind === 'user_managed' ? selectedVersionId || null : null,
      );
    },
    onSuccess: (base: KnowledgeBase) => {
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-bases-selector'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-versions-selector'] });
      queryClient.invalidateQueries({ queryKey: ['knowledge-base', base.knowledge_base_id] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-knowledge-bases'] });
      queryClient.invalidateQueries({ queryKey: ['dashboard-active-version'] });
      queryClient.invalidateQueries({ queryKey: ['new-task-active-version'] });
      queryClient.invalidateQueries({ queryKey: ['task-active-version'] });
      setVersionDirty(false);
      props.onApplied?.({
        baseId: selectedBaseId,
        versionId: selectedBase?.kind === 'user_managed' ? selectedVersionId || null : null,
      });
    },
  });

  const persistedSelectedUserBase = (basesQuery.data ?? []).find((item: KnowledgeBase) => item.selected_for_generation && item.kind === 'user_managed') ?? null;
  const persistedMandatoryBase = (basesQuery.data ?? []).find((item: KnowledgeBase) => item.selected_for_generation && item.kind === 'system_mandatory') ?? null;
  const persistedSelectedBaseId = (persistedSelectedUserBase ?? persistedMandatoryBase)?.knowledge_base_id ?? null;
  const persistedSelectedVersionId = selectedBase?.kind === 'user_managed' && selectedBase?.selected_for_generation ? (selectedBase.selected_knowledge_version_id ?? null) : null;
  const isDirty = Boolean(
    selectedBase && (
      selectedBase.knowledge_base_id !== persistedSelectedBaseId
      || (selectedBase.kind === 'user_managed' && (versionDirty ? (selectedVersionId || null) : (selectedVersionId || null)) !== persistedSelectedVersionId)
    ),
  );

  if (basesQuery.isLoading) return <LoadingState message="Загружаю базы знаний…" />;

  const generationSelectionLocked = hasRunningGeneration(generationLockQuery.data);
  const effectiveDisabled = Boolean(props.disabled || generationSelectionLocked);
  const effectiveDisabledReason = props.disabledReason ?? (generationSelectionLocked ? GENERATION_SELECTION_LOCK_REASON : undefined);
  const userBases = (basesQuery.data ?? []).filter((item: KnowledgeBase) => item.kind === 'user_managed');
  const mandatoryBase = (basesQuery.data ?? []).find((item: KnowledgeBase) => item.kind === 'system_mandatory') ?? null;
  const selectableBases = [
    ...(mandatoryBase ? [mandatoryBase] : []),
    ...userBases,
  ];
  const availableVersions = selectableKnowledgeVersions(versionsQuery.data ?? []);
  const effectiveSelectedVersionId = selectedVersionId || selectedBase?.active_knowledge_version_id || '';
  const selectedVersion = availableVersions.find((item: KnowledgeVersion) => item.knowledge_version_id === effectiveSelectedVersionId) ?? null;
  const selectedBaseNeedsVersion = Boolean(selectedBaseId && selectedBase && !effectiveSelectedVersionId);

  return (
    <div className="stack compact">
      {!props.compact ? <div>
        <strong>{props.title ?? 'База знаний для генерации'}</strong>
        <div className="muted small">{props.description ?? 'Выбери пользовательскую базу или optional baseline для следующих запусков подготовки решения.'}</div>
      </div> : null}

      {userBases.length === 0 ? (
        <Banner tone="warning">
          Пользовательских баз знаний пока нет. Создай базу и загрузи документы либо выбери optional baseline, если у него есть активная версия.
        </Banner>
      ) : null}
      {effectiveDisabled && effectiveDisabledReason ? <Banner tone="warning">{effectiveDisabledReason}</Banner> : null}

      <FormRow label="Режим базы знаний">
        <Select value={selectedBaseId} onChange={(event: ChangeEvent<HTMLSelectElement>) => {
          const nextBaseId = event.target.value;
          const nextBase = (basesQuery.data ?? []).find((item: KnowledgeBase) => item.knowledge_base_id === nextBaseId) ?? null;
          setSelectedBaseId(nextBaseId);
          setSelectedVersionId(nextBase?.kind === 'user_managed' ? nextBase.selected_knowledge_version_id ?? '' : '');
          setVersionDirty(false);
        }} disabled={effectiveDisabled}>
          <option value="">Выбери режим</option>
          {selectableBases.map((item: KnowledgeBase) => (
            <option key={item.knowledge_base_id} value={item.knowledge_base_id}>
              {item.kind === 'system_mandatory' ? `Optional baseline - ${item.name}` : item.name}
            </option>
          ))}
        </Select>
      </FormRow>

      {selectedBase ? (
        <div className="actions between">
          <div className="muted small">
            {knowledgeBaseKindLabel(selectedBase.kind)} · источников: {selectedBase.source_count ?? 0} · документов: {selectedBase.document_count ?? 0}
          </div>
          {selectedBase.selected_for_generation ? <Badge value="selected_for_generation" /> : null}
        </div>
      ) : null}

      <FormRow label="Версия базы знаний">
        <Select value={selectedVersionId} onChange={(event: ChangeEvent<HTMLSelectElement>) => {
          setSelectedVersionId(event.target.value);
          setVersionDirty(true);
        }} disabled={effectiveDisabled || !selectedBaseId || selectedBase?.kind !== 'user_managed' || versionsQuery.isLoading}>
          <option value="">Активная версия базы</option>
          {availableVersions.map((item: KnowledgeVersion) => (
            <option key={item.knowledge_version_id} value={item.knowledge_version_id}>
              {item.version_no} · {formatKnowledgeVersionLabel(item)}
            </option>
          ))}
        </Select>
      </FormRow>

      {selectedBase?.kind === 'user_managed' && selectedVersion ? (
        <div className="muted small">
          Будет использоваться {formatKnowledgeVersionLabel(selectedVersion)} · статус: {selectedVersion.status}.
        </div>
      ) : null}
      {selectedBaseNeedsVersion ? (
        <Banner tone="warning">
          У этой базы пока нет активной или выбранной версии знаний. Сначала активируйте проверенную версию в карточке базы или выберите доступную версию из списка.
        </Banner>
      ) : null}

      {applyMutation.isError ? <ErrorNotice error={applyMutation.error} fallback="Не удалось применить базу знаний." /> : null}
      <div className="actions">
        <Button primary onClick={() => applyMutation.mutate()} disabled={effectiveDisabled || applyMutation.isPending || !selectedBaseId || !isDirty || selectedBaseNeedsVersion}>
          {applyMutation.isPending ? 'Сохраняю выбор…' : 'Сохранить выбор для генерации'}
        </Button>
      </div>
    </div>
  );
}
