import { Badge, Card, CollapsibleCodeBlock, EmptyState } from '../../shared/ui/components';
import { architectureBoundaryLabel, solutionSectionLabel } from '../../shared/lib/format';
import type { NormalizedSolutionArchitectureModel } from '../../shared/api/normalized';
import type {
  SolutionArchitectureEntity,
  SolutionArchitectureRelation,
  SolutionSectionAssessment,
} from '../../types/api';
import { sectionScorePercent } from './lib';

interface SolutionModelTabProps {
  architectureModel: NormalizedSolutionArchitectureModel;
  sectionAssessments: SolutionSectionAssessment[];
  entitiesByLayer: Record<string, SolutionArchitectureEntity[]>;
  normalizedEntityCount: number;
}

export function SolutionModelTab({ architectureModel, sectionAssessments, entitiesByLayer, normalizedEntityCount }: SolutionModelTabProps) {
  return (
    <div className="stack">
      <div className="grid grid-4">
        <Card title="Версия модели"><strong>{architectureModel.version ?? '—'}</strong></Card>
        <Card title="Сущностей"><strong>{architectureModel.entities.length}</strong></Card>
        <Card title="Нормализовано"><strong>{normalizedEntityCount}</strong></Card>
        <Card title="Связей"><strong>{architectureModel.relations.length}</strong></Card>
      </div>

      <div className="grid grid-2">
        <Card title="Готовность секций" subtitle="Отдельный API-слой для section assessments.">
          {sectionAssessments.length === 0 ? <EmptyState title="Оценки секций отсутствуют" /> : (
            <div className="timeline">
              {sectionAssessments.map((item: SolutionSectionAssessment) => (
                <div className="timeline-item" key={item.section_assessment_id}>
                  <div className="actions between">
                    <strong>{item.heading ?? solutionSectionLabel(item.section_code, item.section_code)}</strong>
                    <Badge value={item.status} />
                  </div>
                  <div className="muted small">Сигнал: {sectionScorePercent(item.score)} · fallback: {item.fallback_applied ? 'да' : 'нет'}</div>
                  {item.observed_signal_groups?.length ? <div className="muted small">Найдено: {item.observed_signal_groups.join(', ')}</div> : null}
                  {item.missing_signal_groups?.length ? <div className="muted small">Не хватает: {item.missing_signal_groups.join(', ')}</div> : null}
                </div>
              ))}
            </div>
          )}
        </Card>
        <Card title="Диагностика модели">
          <CollapsibleCodeBlock>{JSON.stringify(architectureModel.diagnostics ?? {}, null, 2)}</CollapsibleCodeBlock>
        </Card>
      </div>

      <Card title="Сущности по слоям ArchiMate">
        {Object.keys(entitiesByLayer).length === 0 ? <EmptyState title="Сущности не сохранены" /> : (
          <div className="stack compact">
            {Object.entries(entitiesByLayer).map(([group, items]) => (
              <div className="section-box" key={group}>
                <div className="actions between">
                  <strong>{architectureBoundaryLabel(group)}</strong>
                  <span className="muted small">{items.length} сущн.</span>
                </div>
                <div className="table-wrap" style={{ marginTop: 8 }}>
                  <table className="table">
                    <thead>
                      <tr><th>Имя</th><th>Тип</th><th>Секция</th><th>Статус</th><th>Confidence</th></tr>
                    </thead>
                    <tbody>
                      {items.map((item: SolutionArchitectureEntity) => (
                        <tr key={item.architecture_entity_id}>
                          <td>{item.display_name}</td>
                          <td>{item.archimate_element_title ?? item.archimate_element_code ?? '—'}</td>
                          <td>{solutionSectionLabel(item.section_code ?? '', item.section_code ?? '—')}</td>
                          <td>{item.normalized_flag ? 'Нормализовано' : 'Требует проверки'}</td>
                          <td>{item.confidence != null ? item.confidence.toFixed(2) : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Связи модели">
        {architectureModel.relations.length === 0 ? <EmptyState title="Связи не сохранены" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Тип связи</th><th>Источник</th><th>Цель</th><th>Секция</th><th>Статус</th></tr>
              </thead>
              <tbody>
                {architectureModel.relations.map((item: SolutionArchitectureRelation) => (
                  <tr key={item.architecture_relation_id}>
                    <td>{item.relation_type}</td>
                    <td>{item.source_entity_key ?? '—'}</td>
                    <td>{item.target_entity_key ?? '—'}</td>
                    <td>{solutionSectionLabel(item.section_code ?? '', item.section_code ?? '—')}</td>
                    <td>{item.normalized_flag ? 'Нормализовано' : 'Требует проверки'}</td>
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
