import { Card, CollapsibleCodeBlock, EmptyState } from '../../shared/ui/components';
import { solutionSectionLabel } from '../../shared/lib/format';
import type { NormalizedSolution } from '../../shared/api/normalized';
import { normalizeArray } from './lib';

interface SolutionBasisTabProps {
  solution: NormalizedSolution;
  retrievalSummary: Record<string, unknown>;
  basisDocuments: Array<Record<string, unknown>>;
  sectionCoverage: Array<Record<string, unknown>>;
  evidenceCoverage: Record<string, unknown>;
  guidanceSummary: Record<string, Record<string, unknown>>;
  snapshotSummary: Record<string, unknown>;
}

export function SolutionBasisTab({
  solution,
  retrievalSummary,
  basisDocuments,
  sectionCoverage,
  evidenceCoverage,
  guidanceSummary,
  snapshotSummary,
}: SolutionBasisTabProps) {
  return (
    <div className="stack">
      <div className="grid grid-2">
        <Card title="Основания решения" subtitle="Как система подбирала материалы и насколько ими покрыты секции.">
          <div className="stack compact">
            <div><strong>Правило подбора:</strong> {String(retrievalSummary.policy_id ?? '—')}</div>
            <div><strong>Бэкенд retrieval:</strong> {String(retrievalSummary.retrieval_backend ?? '—')}</div>
            <div><strong>Разделов с основаниями:</strong> {String(evidenceCoverage.sections_with_evidence ?? 0)} / {String(evidenceCoverage.section_count ?? solution.sections.length)}</div>
            <div><strong>Всего ссылок:</strong> {String(evidenceCoverage.total_source_refs ?? 0)}</div>
            <div><strong>Неиспользованных фрагментов:</strong> {String((((retrievalSummary.dropped_fragment_ids as unknown[]) ?? []).length))}</div>
          </div>
        </Card>
        <Card title="Профиль подбора материалов">
          <CollapsibleCodeBlock>{JSON.stringify(retrievalSummary.query_profile ?? {}, null, 2)}</CollapsibleCodeBlock>
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Guidance по секциям" subtitle="Методические и предметные фрагменты, найденные для TOGAF-разделов.">
          {Object.keys(guidanceSummary).length === 0 ? <EmptyState title="Guidance summary пока не собран" /> : (
            <div className="timeline">
              {solution.sections.map((section) => {
                const item = guidanceSummary[section.section_code] ?? {};
                const titles = normalizeArray(item.document_titles as string[] | undefined);
                return (
                  <div className="timeline-item" key={`guidance-${section.section_code}`}>
                    <div className="actions between">
                      <strong>{solutionSectionLabel(section.section_code, section.title)}</strong>
                      <span className="muted small">{String(item.fragment_count ?? 0)} фрагм.</span>
                    </div>
                    <div className="muted small">Методических фрагментов: {String(item.methodology_fragment_count ?? 0)}</div>
                    {titles.length ? <div className="muted small">Документы: {titles.join(', ')}</div> : null}
                  </div>
                );
              })}
            </div>
          )}
        </Card>
        <Card title="Сводка по снимку">
          <CollapsibleCodeBlock>{JSON.stringify(snapshotSummary, null, 2)}</CollapsibleCodeBlock>
        </Card>
      </div>

      <Card title="Использованные материалы" subtitle="Список материалов, на которые опиралось решение.">
        {basisDocuments.length === 0 ? (
          <EmptyState title="Основания не собраны" description="Для решения не удалось собрать список материалов-оснований." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Документ</th><th>Роль</th><th>Версия</th><th>Тип</th><th>Основной</th><th>Разделов</th><th>Фрагментов</th></tr>
              </thead>
              <tbody>
                {basisDocuments.map((item, index) => (
                  <tr key={`${String(item.document_id ?? item.title ?? index)}`}>
                    <td>{String(item.title ?? '—')}<div className="muted small">{String(item.source_name ?? '')}</div></td>
                    <td>{String(item.role_code ?? 'справочный материал')}</td>
                    <td>{String(item.version_ref ?? '—')}</td>
                    <td>{String(item.document_type ?? '—')}</td>
                    <td>{item.required_flag ? 'Да' : 'Нет'}</td>
                    <td>{Array.isArray(item.sections) ? item.sections.length : 0}</td>
                    <td>{String(item.fragment_count ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Покрытие разделов" subtitle="По каждому разделу видно, хватает ли материалов-оснований.">
        {sectionCoverage.length === 0 ? <EmptyState title="Покрытие не собрано" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Раздел</th><th>Название</th><th>Ссылки на материалы</th><th>Материалы</th></tr>
              </thead>
              <tbody>
                {sectionCoverage.map((item, index) => (
                  <tr key={`${String(item.section_code ?? index)}`}>
                    <td>{String(item.section_code ?? '—')}</td>
                    <td>{solutionSectionLabel(String(item.section_code ?? ''), String(item.title ?? '—'))}</td>
                    <td>{String(item.source_ref_count ?? 0)}</td>
                    <td>{String(item.basis_document_count ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
