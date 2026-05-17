import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import {
  generationDetailLines,
  generationRunElapsedSeconds,
  generationRunProgressLine,
  generationRunStageProgress,
  generationStageElapsedSeconds,
  generationStageHint,
} from '../../entities/knowledge/generationRunProgress';
import { Banner, Button, Card, MetricCard, StateBox } from '../../shared/ui/components';
import { formatDateTime, formatSeconds, titleStatus } from '../../shared/lib/format';
import type { NormalizedGenerationRun } from '../../shared/api/normalized';
import type { GenerationRunRef, SolutionVerificationRunRef, TaskSnapshot } from '../../types/api';

const TERMINAL_GENERATION_STATES = new Set(['completed', 'completed_with_warnings', 'failed', 'canceled']);

interface TaskSummarySectionProps {
  task: TaskSnapshot;
  activeKnowledgeBanner: ReactNode;
  generationState: string | null | undefined;
  generationCurrentStage: string | null | undefined;
  generationRun: NormalizedGenerationRun | null;
  generationError?: string | null;
  solutionId: string | null;
  generationOperationId: string | null;
  verificationOperationId: string | null;
  protocolId: string | null;
  verificationState: string | null | undefined;
  verificationCurrentStage: string | null | undefined;
  latestGenerationRef: GenerationRunRef | null;
  latestVerificationRef: SolutionVerificationRunRef | null;
  canStartGeneration: boolean;
  canCancelGeneration?: boolean;
  generationPending: boolean;
  generationCancelPending?: boolean;
  verificationPending: boolean;
  onStartGeneration: () => void;
  onCancelGeneration?: () => void;
  onStartVerification: () => void;
}

export function TaskSummarySection({
  task,
  activeKnowledgeBanner,
  generationState,
  generationCurrentStage,
  generationRun,
  generationError,
  solutionId,
  generationOperationId,
  verificationOperationId,
  protocolId,
  verificationState,
  verificationCurrentStage,
  latestGenerationRef,
  latestVerificationRef,
  canStartGeneration,
  canCancelGeneration = false,
  generationPending,
  generationCancelPending = false,
  verificationPending,
  onStartGeneration,
  onCancelGeneration,
  onStartVerification,
}: TaskSummarySectionProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const intervalId = window.setInterval(() => setNowMs(Date.now()), 1_000);
    return () => window.clearInterval(intervalId);
  }, []);

  const effectiveGenerationStage = generationCurrentStage;
  const effectiveGenerationState = generationState ?? latestGenerationRef?.state ?? 'draft';
  const generationIsActive = effectiveGenerationState !== 'draft' && !TERMINAL_GENERATION_STATES.has(effectiveGenerationState);
  const generationIsInProgress = generationIsActive || generationPending;
  const generationIsTerminalWithSolution = Boolean(solutionId) && ['completed', 'completed_with_warnings'].includes(effectiveGenerationState);
  const canClickGeneration = canStartGeneration && !generationIsInProgress && !generationIsTerminalWithSolution;
  const generationElapsedSec = generationRunElapsedSeconds(generationRun, nowMs);
  const generationStageElapsedSec = generationStageElapsedSeconds(generationRun, nowMs);
  const generationDetails = useMemo(
    () => generationDetailLines(generationRun, nowMs),
    [generationRun, nowMs],
  );
  const generationProgress = generationRun ? generationRunProgressLine(generationRun, nowMs) : null;
  const hasVerification = Boolean(
    latestVerificationRef
    || verificationState
    || verificationCurrentStage
    || verificationOperationId
    || protocolId
    || verificationPending,
  );
  const generationButtonLabel = generationPending
    ? 'Запускаю…'
    : task.state === 'ready_for_generation'
      ? 'Подготовить решение'
      : task.state === 'failed'
        ? 'Повторить подготовку решения'
      : task.state === 'draft'
        ? 'Отправить на проверку входных данных'
        : task.state === 'needs_clarification'
          ? 'Проверить уточнения'
          : 'Проверить входные данные';

  return (
    <>
      {activeKnowledgeBanner}

      <div className="grid grid-2">
        <Card title="О задаче">
          <div className="stack compact">
            <div><strong>Состояние:</strong> {titleStatus(task.state)}</div>
            <div><strong>Создана:</strong> {formatDateTime(task.created_at)}</div>
            <div><strong>Обновлена:</strong> {formatDateTime(task.updated_at)}</div>
            <div><strong>Открытых уточнений:</strong> {task.open_clarification_count ?? 0}</div>
            {task.overdue_clarification_flag ? <Banner tone="warning">Есть старые уточнения, на которые лучше ответить перед запуском.</Banner> : null}
          </div>
          <StateBox className="with-top-margin">{task.raw_text}</StateBox>
        </Card>

        <Card title="Подготовка решения">
          <div className="stack compact">
            <div><strong>Статус:</strong> {titleStatus(effectiveGenerationState)}</div>
            <div><strong>Текущий шаг:</strong> {titleStatus(effectiveGenerationStage)}</div>
            {generationRun ? (
              <>
                <div className="grid grid-4">
                  <MetricCard label="Всего прошло" value={formatSeconds(generationElapsedSec)} />
                  <MetricCard label="Текущий шаг" value={formatSeconds(generationStageElapsedSec)} />
                  <MetricCard label="Прогресс этапов" value={generationRunStageProgress(generationRun)} />
                  <MetricCard label="Старт" value={formatDateTime(generationRun.started_at)} />
                </div>
                {generationProgress ? <div className="muted small">{generationProgress}</div> : null}
              </>
            ) : null}
            {effectiveGenerationState === 'running' && generationStageHint(effectiveGenerationStage) ? (
              <StateBox tone="info">
                <strong>Сейчас выполняется: {titleStatus(effectiveGenerationStage)}</strong>
                <div>{generationStageHint(effectiveGenerationStage)}</div>
                {generationDetails.length ? (
                  <div className="muted small" style={{ marginTop: 8 }}>
                    {generationDetails.map((line) => <div key={line}>{line}</div>)}
                  </div>
                ) : null}
              </StateBox>
            ) : null}
            {generationError ? <Banner tone="danger">{generationError}</Banner> : null}
            <div className="actions">
              {!generationIsTerminalWithSolution ? (
                <Button primary onClick={onStartGeneration} disabled={!canClickGeneration}>
                  {generationButtonLabel}
                </Button>
              ) : null}
              {solutionId ? <Link className="button" to={`/solutions/${solutionId}`}>Открыть решение</Link> : null}
              {generationOperationId ? <Link className="button" to={`/operations/${generationOperationId}`}>Ход выполнения</Link> : null}
              {canCancelGeneration && onCancelGeneration ? (
                <Button onClick={onCancelGeneration} disabled={generationCancelPending}>
                  {generationCancelPending ? 'Останавливаю…' : 'Остановить подготовку'}
                </Button>
              ) : null}
            </div>
          </div>
        </Card>
      </div>

      {solutionId && hasVerification ? (
        <div className="grid grid-2">
          <Card title="Последняя проверка решения">
            <div className="stack compact">
              <div><strong>Статус:</strong> {titleStatus(verificationState ?? latestVerificationRef?.state ?? 'draft')}</div>
              <div><strong>Текущий шаг:</strong> {titleStatus(verificationCurrentStage)}</div>
              <div className="actions">
                <Button primary onClick={onStartVerification} disabled={verificationPending}>{verificationPending ? 'Запускаю…' : 'Запустить проверку'}</Button>
                {verificationOperationId ? <Link className="button" to={`/operations/${verificationOperationId}`}>Ход выполнения</Link> : null}
                {protocolId ? <Link className="button" to={`/protocols/${protocolId}`}>Открыть проверку</Link> : null}
              </div>
            </div>
          </Card>
        </div>
      ) : null}
    </>
  );
}
