import { useParams } from 'react-router-dom';

import { KnowledgeScopeSelector } from '../entities/knowledge/KnowledgeScopeSelector';
import { ClarificationHistoryCard } from '../features/task-workspace/ClarificationHistoryCard';
import { ClarificationsCard } from '../features/task-workspace/ClarificationsCard';
import { DraftEditorCard } from '../features/task-workspace/DraftEditorCard';
import { SolutionAndProtocolSection } from '../features/task-workspace/SolutionAndProtocolSection';
import { TaskSummarySection } from '../features/task-workspace/TaskSummarySection';
import { useTaskWorkspaceData } from '../features/task-workspace/useTaskWorkspaceData';
import { getApiErrorStatus } from '../shared/api/client';
import { formatKnowledgeVersionLabel } from '../shared/lib/format';
import { Banner, Card, ErrorNotice, ErrorState, LoadingState, PageHeader, StateBox } from '../shared/ui/components';
import { isTerminal } from '../features/task-workspace/lib';

export function TaskWorkspacePage() {
  const { taskId = '' } = useParams();
  const {
    answerDrafts,
    setAnswerDrafts,
    draftTitle,
    setDraftTitle,
    draftText,
    setDraftText,
    draftSaveMode,
    generationDispatchNotice,
    taskQuery,
    activeVersionQuery,
    generationRunQuery,
    solutionQuery,
    renderedQuery,
    verificationRunQuery,
    protocolQuery,
    answerMutation,
    saveDraftMutation,
    generationMutation,
    verificationMutation,
    task,
    openClarifications,
    clarificationHistory,
    groupedFindings,
    latestGenerationRef,
    latestVerificationRef,
    solutionId,
    protocolId,
    generationOperationId,
    verificationOperationId,
    readinessMissingInputs,
  } = useTaskWorkspaceData(taskId);

  if (taskQuery.isLoading) return <LoadingState message="Открываю задачу…" />;
  if (taskQuery.isError || !task) return <ErrorState message="Не удалось загрузить задачу." />;

  const activeVersionStatus = getApiErrorStatus(activeVersionQuery.error);
  const canEditTask = !latestGenerationRef && ['draft', 'submitted', 'needs_clarification', 'clarified', 'ready_for_generation'].includes(task.state);
  const generationState = generationRunQuery.data?.state ?? latestGenerationRef?.state ?? null;
  const generationInProgress = generationMutation.isPending || Boolean(generationState && !isTerminal(generationState));
  const inputValidationPassed = task.state === 'ready_for_generation' && readinessMissingInputs.length === 0;
  const knowledgeBanner = activeVersionQuery.data
    ? <Banner tone="info">Сейчас используется {formatKnowledgeVersionLabel(activeVersionQuery.data)}.</Banner>
    : activeVersionStatus === 404
      ? <Banner tone="warning">База знаний пока не выбрана. Задачу можно редактировать, но подготовка решения и проверка будут недоступны.</Banner>
      : activeVersionQuery.isError
        ? <ErrorNotice error={activeVersionQuery.error} fallback="Не удалось загрузить активную версию базы знаний для этой задачи." />
        : null;

  return (
    <div className="stack">
      <PageHeader
        title={task.title ?? 'Задача без названия'}
        subtitle="Здесь можно уточнить входные данные, подготовить решение и запустить его проверку."
      />

      {generationMutation.isError ? <ErrorNotice error={generationMutation.error} fallback="Не удалось запустить подготовку решения." /> : null}
      {generationDispatchNotice?.dispatch_type === 'needs_clarification' ? (
        <Banner tone="warning">Перед подготовкой решения нужно ответить на уточняющие вопросы ниже.</Banner>
      ) : null}
      {generationDispatchNotice?.dispatch_type === 'generation_run' ? (
        <Banner tone="info">Подготовка решения запущена. Ниже можно следить за её состоянием.</Banner>
      ) : null}

      <Card
        title="База знаний для этого запуска"
        subtitle={generationInProgress ? 'Во время подготовки решения выбор базы знаний зафиксирован.' : 'Перед генерацией можно сменить пользовательскую базу, зафиксировать старую версию или явно выбрать optional baseline.'}
      >
        <KnowledgeScopeSelector
          compact
          disabled={generationInProgress}
          disabledReason="Подготовка решения уже идет, поэтому базу знаний сейчас менять нельзя."
        />
      </Card>

      <TaskSummarySection
        task={task}
        activeKnowledgeBanner={knowledgeBanner}
        generationState={generationRunQuery.data?.state}
        generationCurrentStage={generationRunQuery.data?.current_stage}
        generationRun={generationRunQuery.data ?? null}
        generationError={typeof generationRunQuery.data?.diagnostics?.error === 'string' ? generationRunQuery.data.diagnostics.error : null}
        solutionId={solutionId}
        generationOperationId={generationOperationId}
        verificationOperationId={verificationOperationId}
        protocolId={protocolId}
        verificationState={verificationRunQuery.data?.state}
        verificationCurrentStage={verificationRunQuery.data?.current_stage}
        latestGenerationRef={latestGenerationRef}
        latestVerificationRef={latestVerificationRef}
        canStartGeneration={Boolean(activeVersionQuery.data)}
        generationPending={generationMutation.isPending}
        verificationPending={verificationMutation.isPending}
        onStartGeneration={() => generationMutation.mutate()}
        onStartVerification={() => verificationMutation.mutate()}
      />

      <Card title="Что нужно для запуска">
        {readinessMissingInputs.length === 0 ? (
          <StateBox>Сейчас всё необходимое заполнено. Можно запускать подготовку решения.</StateBox>
        ) : (
          <div className="stack compact">
            <div>Пока не хватает:</div>
            <ul className="compact-list">
              {readinessMissingInputs.map((item) => <li key={item}>{item}</li>)}
            </ul>
            {task.next_action_hint ? <div className="muted small">{task.next_action_hint}</div> : null}
          </div>
        )}
      </Card>

      {canEditTask ? (
        <DraftEditorCard
          draftTitle={draftTitle}
          draftText={draftText}
          pending={saveDraftMutation.isPending}
          onDraftTitleChange={setDraftTitle}
          onDraftTextChange={setDraftText}
          onSave={(mode) => saveDraftMutation.mutate(mode)}
          pendingMode={draftSaveMode}
          error={saveDraftMutation.error}
          inputValidationPassed={inputValidationPassed}
        />
      ) : null}

      <ClarificationsCard
        clarifications={openClarifications}
        answerDrafts={answerDrafts}
        pending={answerMutation.isPending}
        error={answerMutation.error}
        onAnswerChange={(key, value) => setAnswerDrafts((current) => ({ ...current, [key]: value }))}
        onSubmitAnswers={(clarificationId, answers) => answerMutation.mutate({ clarificationId, answers })}
      />

      {clarificationHistory.length ? <ClarificationHistoryCard clarifications={clarificationHistory} /> : null}

      <SolutionAndProtocolSection
        solution={solutionQuery.data ?? null}
        renderedHtml={renderedQuery.data?.rendered_html}
        protocol={protocolQuery.data ?? null}
        groupedFindings={groupedFindings}
      />
    </div>
  );
}
