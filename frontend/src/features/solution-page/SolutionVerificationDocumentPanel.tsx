import { useState } from 'react';

import {
  KnowledgeDocumentScopePicker,
  type KnowledgeDocumentScopeMode,
} from '../../entities/knowledge/KnowledgeDocumentScopePicker';
import { Banner, Button, Card, ErrorNotice } from '../../shared/ui/components';
import type { NormalizedVerificationRun } from '../../shared/api/normalized';
import { isTerminal } from './lib';

interface SolutionVerificationDocumentPanelProps {
  verificationRun?: NormalizedVerificationRun | null;
  verificationPending: boolean;
  verificationError: unknown;
  verificationIsError: boolean;
  onStartVerification: (payload?: { knowledge_document_ids?: string[] }) => void;
}

export function SolutionVerificationDocumentPanel({
  verificationRun,
  verificationPending,
  verificationError,
  verificationIsError,
  onStartVerification,
}: SolutionVerificationDocumentPanelProps) {
  const [mode, setMode] = useState<KnowledgeDocumentScopeMode>('full');
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<string[]>([]);
  const verificationRunning = Boolean(verificationRun && !isTerminal(verificationRun.state));
  const canStart = !verificationPending && !verificationRunning && (mode === 'full' || selectedDocumentIds.length > 0);

  function handleStart() {
    if (!canStart) return;
    onStartVerification(
      mode === 'selected'
        ? { knowledge_document_ids: selectedDocumentIds }
        : {},
    );
  }

  return (
    <Card
      title="Проверка по базе знаний"
      subtitle="Можно проверить решение по всей выбранной базе знаний или только по конкретным документам из нее."
    >
      <div className="stack compact">
        {verificationRunning ? (
          <Banner tone="info">Проверка уже выполняется. Новый запуск станет доступен после завершения текущего.</Banner>
        ) : null}
        <KnowledgeDocumentScopePicker
          mode={mode}
          selectedDocumentIds={selectedDocumentIds}
          onModeChange={setMode}
          onSelectedDocumentIdsChange={setSelectedDocumentIds}
          disabled={verificationPending || verificationRunning}
        />
        {verificationIsError ? (
          <ErrorNotice error={verificationError} fallback="Не удалось запустить проверку решения." />
        ) : null}
        <div className="actions">
          <Button primary type="button" onClick={handleStart} disabled={!canStart}>
            {verificationPending ? 'Запускаю проверку...' : 'Запустить проверку'}
          </Button>
          <span className="muted small">
            {mode === 'selected'
              ? `Будет использовано документов: ${selectedDocumentIds.length}`
              : 'Будет использована вся выбранная база знаний'}
          </span>
        </div>
      </div>
    </Card>
  );
}
