import { Badge, Banner, Card, Panel, StateBox } from '../../shared/ui/components';
import { architectureBoundaryLabel, cleanDisplayFileName, solutionSectionLabel } from '../../shared/lib/format';
import { sanitizeHtml } from '../../shared/lib/html';
import type { NormalizedSolution } from '../../shared/api/normalized';
import type { SolutionSectionAssessment } from '../../types/api';
import { sectionScorePercent } from './lib';

interface SolutionContentTabProps {
  solution: NormalizedSolution;
  renderedHtml?: string | null;
  sectionAssessmentMap: Map<string, SolutionSectionAssessment>;
}

export function SolutionContentTab({ solution, renderedHtml, sectionAssessmentMap }: SolutionContentTabProps) {
  const safeRenderedHtml = sanitizeHtml(renderedHtml);

  return (
    <>
      <Card title="Краткий вывод">
        <StateBox>{solution.executive_summary}</StateBox>
      </Card>

      {safeRenderedHtml ? (
        <Card title="Веб-версия решения">
          <div className="html-preview" dangerouslySetInnerHTML={{ __html: safeRenderedHtml }} />
        </Card>
      ) : (
        <Banner tone="warning">Веб-версия решения пока недоступна. Ниже показана TOGAF-структура из сохранённых секций.</Banner>
      )}

      <div className="grid grid-2">
        <Card title="TOGAF-секции решения" subtitle="Каждый раздел показан вместе с оценкой готовности и списком допустимых объектов слоя.">
          <div className="stack compact">
            {solution.sections.map((section) => {
              const assessment = sectionAssessmentMap.get(section.section_code);
              return (
                <Panel key={section.section_id ?? section.section_code} id={`section-${section.section_code}`}>
                  <div className="actions between">
                    <strong>{solutionSectionLabel(section.section_code, section.title)}</strong>
                    <Badge value={assessment?.status ?? 'draft'} />
                  </div>
                  <div className="muted small">
                    Код: {section.section_code}
                    {assessment ? ` · сигнал: ${sectionScorePercent(assessment.score)}` : ''}
                    {assessment?.fallback_applied ? ' · применён fallback' : ''}
                  </div>
                  <div className="pre-wrap" style={{ marginTop: 8 }}>{section.body_markdown}</div>
                  {assessment?.allowed_archimate_elements?.length ? (
                    <div className="muted small" style={{ marginTop: 8 }}>
                      Допустимые объекты слоя: {assessment.allowed_archimate_elements.join(', ')}
                    </div>
                  ) : null}
                  {assessment?.reasons?.length ? (
                    <ul className="compact-list" style={{ marginTop: 8 }}>
                      {assessment.reasons.map((reason, index) => <li key={`${section.section_id}-reason-${index}`}>{reason}</li>)}
                    </ul>
                  ) : null}
                  {(section.source_refs ?? []).length ? (
                    <ul className="compact-list" style={{ marginTop: 8 }}>
                      {(section.source_refs ?? []).slice(0, 5).map((ref) => (
                        <li key={`${section.section_id ?? section.section_code}-${ref.sort_order ?? ref.fragment_id ?? ref.document_title ?? 'ref'}`}>
                          {cleanDisplayFileName(ref.document_title) ?? ref.document_title ?? ref.fragment_id ?? 'Источник'} · {ref.role_code ?? 'справочный материал'}
                          {ref.source_location ? ` · ${ref.source_location}` : ''}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </Panel>
              );
            })}
          </div>
        </Card>
        <Card title="Архитектурные объекты, интеграции и риски">
          <div className="stack compact">
            {solution.components.map((component) => (
              <Panel key={component.component_id ?? component.component_name}>
                <strong>{component.component_name}</strong>
                <div>{component.role_description}</div>
                <div className="muted small">Слой: {architectureBoundaryLabel(component.boundary_type)}</div>
                <div className="muted small">Технологии: {component.technology_stack ?? 'не указаны'}</div>
              </Panel>
            ))}
            {solution.integrations.length ? (
              <Panel>
                <strong>Интеграции</strong>
                <ul className="compact-list">
                  {solution.integrations.map((integration) => (
                    <li key={integration.integration_id ?? `${integration.interaction}-${integration.protocol ?? 'protocol'}`}>
                      {integration.interaction}{integration.protocol ? ` · ${integration.protocol}` : ''}{integration.rationale ? ` · ${integration.rationale}` : ''}
                    </li>
                  ))}
                </ul>
              </Panel>
            ) : null}
            {solution.risks.length ? (
              <Panel>
                <strong>Риски</strong>
                <ul className="compact-list">
                  {solution.risks.map((risk) => (
                    <li key={risk.risk_id ?? risk.title}>
                      <strong>{risk.title}</strong> · {risk.mitigation ?? risk.description}
                    </li>
                  ))}
                </ul>
              </Panel>
            ) : null}
          </div>
        </Card>
      </div>
    </>
  );
}
