import { useEffect, useState } from 'react';
import { Link, useLocation, useParams } from 'react-router-dom';

import { KnowledgeScopeSummary } from '../entities/knowledge/KnowledgeScopeSummary';
import { SolutionBasisTab } from '../features/solution-page/SolutionBasisTab';
import { SolutionContentTab } from '../features/solution-page/SolutionContentTab';
import { SolutionHeaderCards } from '../features/solution-page/SolutionHeaderCards';
import { SolutionHistoryTab } from '../features/solution-page/SolutionHistoryTab';
import { SolutionModelTab } from '../features/solution-page/SolutionModelTab';
import { SolutionVerificationDocumentPanel } from '../features/solution-page/SolutionVerificationDocumentPanel';
import { useSolutionPageData } from '../features/solution-page/useSolutionPageData';
import { Banner, ErrorState, LoadingState, PageHeader, TabStrip } from '../shared/ui/components';

function scrollToHashTarget(hash: string) {
  if (!hash || typeof document === 'undefined') return false;
  const element = document.getElementById(hash.replace(/^#/, ''));
  if (!element) return false;
  element.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return true;
}

export function SolutionPage() {
  const { solutionId = '' } = useParams();
  const location = useLocation();
  const [tab, setTab] = useState<'content' | 'basis' | 'model' | 'history'>('content');

  const {
    copied,
    solutionQuery,
    renderedQuery,
    verificationMutation,
    verificationRunQuery,
    solution,
    verificationOperationId,
    retrievalSummary,
    basisDocuments,
    sectionCoverage,
    evidenceCoverage,
    guidanceSummary,
    publicationHistory,
    snapshotSummary,
    knowledgeScope,
    sectionAssessments,
    architectureModel,
    sectionAssessmentMap,
    readyCount,
    partialCount,
    insufficientCount,
    normalizedEntityCount,
    relationCount,
    entitiesByLayer,
    copyLink,
  } = useSolutionPageData(solutionId);

  useEffect(() => {
    if (!location.hash?.startsWith('#section-')) return;
    if (tab !== 'content') {
      setTab('content');
      return;
    }

    let cancelled = false;
    let attempt = 0;
    let timer: number | undefined;

    const tryScroll = () => {
      if (cancelled) return;
      attempt += 1;
      if (scrollToHashTarget(location.hash) || attempt >= 8) return;
      timer = window.setTimeout(tryScroll, 120);
    };

    timer = window.setTimeout(tryScroll, 0);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [location.hash, renderedQuery.data?.rendered_html, solution?.sections.length, tab]);

  if (solutionQuery.isLoading) return <LoadingState message="Открываю решение…" />;
  if (solutionQuery.isError || !solution) return <ErrorState message="Не удалось загрузить решение." />;

  return (
    <div className="stack">
      <PageHeader
        title={solution.solution_title}
        subtitle="Здесь собраны содержание решения, материалы-основания, TOGAF-секции и нормализованная архитектурная модель."
        actions={<Link to={`/tasks/${solution.task_id}`} className="button">Вернуться к задаче</Link>}
      />

      {verificationRunQuery.data?.state === 'failed' ? (
        <Banner tone="danger">Последняя проверка завершилась ошибкой. Перед повторным запуском лучше посмотреть журнал.</Banner>
      ) : null}

      <SolutionHeaderCards
        copied={copied}
        solution={solution}
        architectureModel={architectureModel}
        verificationRun={verificationRunQuery.data}
        verificationOperationId={verificationOperationId}
        normalizedEntityCount={normalizedEntityCount}
        readyCount={readyCount}
        partialCount={partialCount}
        insufficientCount={insufficientCount}
        relationCount={relationCount}
        publicationRevisionNo={solution.publication_revision_no ?? renderedQuery.data?.publication_revision_no ?? '—'}
        onCopyLink={copyLink}
      />

      <SolutionVerificationDocumentPanel
        verificationRun={verificationRunQuery.data}
        verificationPending={verificationMutation.isPending}
        verificationError={verificationMutation.error}
        verificationIsError={verificationMutation.isError}
        onStartVerification={(payload) => verificationMutation.mutate(payload)}
      />

      <KnowledgeScopeSummary
        scope={knowledgeScope}
        title="Область знаний решения"
        subtitle="Какие версии базы знаний участвовали в подготовке решения."
      />

      <TabStrip>
        <button type="button" className={`button ${tab === 'content' ? 'button-primary' : ''}`} onClick={() => setTab('content')}>TOGAF-документ</button>
        <button type="button" className={`button ${tab === 'basis' ? 'button-primary' : ''}`} onClick={() => setTab('basis')}>Основания и знания</button>
        <button type="button" className={`button ${tab === 'model' ? 'button-primary' : ''}`} onClick={() => setTab('model')}>Архитектурная модель</button>
        <button type="button" className={`button ${tab === 'history' ? 'button-primary' : ''}`} onClick={() => setTab('history')}>История проверок</button>
      </TabStrip>

      {tab === 'content' ? (
        <SolutionContentTab
          solution={solution}
          renderedHtml={renderedQuery.data?.rendered_html}
          sectionAssessmentMap={sectionAssessmentMap}
        />
      ) : null}

      {tab === 'basis' ? (
        <SolutionBasisTab
          solution={solution}
          retrievalSummary={retrievalSummary}
          basisDocuments={basisDocuments}
          sectionCoverage={sectionCoverage}
          evidenceCoverage={evidenceCoverage}
          guidanceSummary={guidanceSummary}
          snapshotSummary={snapshotSummary}
        />
      ) : null}

      {tab === 'model' ? (
        <SolutionModelTab
          architectureModel={architectureModel}
          sectionAssessments={sectionAssessments}
          entitiesByLayer={entitiesByLayer}
          normalizedEntityCount={normalizedEntityCount}
        />
      ) : null}

      {tab === 'history' ? (
        <SolutionHistoryTab solution={solution} publicationHistory={publicationHistory} />
      ) : null}
    </div>
  );
}
