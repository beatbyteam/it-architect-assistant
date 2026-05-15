import { Link } from 'react-router-dom';

import { Banner, Card } from '../../shared/ui/components';
import { formatDateTime, titleStatus } from '../../shared/lib/format';
import { sanitizeHtml } from '../../shared/lib/html';
import type { NormalizedSolution, NormalizedVerificationProtocol } from '../../shared/api/normalized';
import type { VerificationFinding } from '../../types/api';
import { FindingsGroup } from './FindingsGroup';

interface SolutionAndProtocolSectionProps {
  solution: NormalizedSolution | null;
  renderedHtml?: string | null;
  protocol: NormalizedVerificationProtocol | null;
  groupedFindings: Record<string, VerificationFinding[]>;
}

export function SolutionAndProtocolSection({ solution, renderedHtml, protocol, groupedFindings }: SolutionAndProtocolSectionProps) {
  if (!solution && !protocol) return null;
  const safeRenderedHtml = sanitizeHtml(renderedHtml);

  return (
    <>
      {solution ? (
        <div className="grid grid-2">
          <Card title="Решение">
            <div className="stack compact">
              <div><strong>Название:</strong> {solution.solution_title}</div>
              <div><strong>Статус:</strong> {titleStatus(solution.state)}</div>
              <div><strong>Опубликовано:</strong> {formatDateTime(solution.published_at)}</div>
            </div>
            {safeRenderedHtml ? <div className="html-preview" dangerouslySetInnerHTML={{ __html: safeRenderedHtml }} /> : null}
            <div className="actions">
              <Link className="button" to={`/solutions/${solution.solution_version_id}`}>Открыть полностью</Link>
            </div>
          </Card>
        </div>
      ) : null}

      {protocol ? (
        <Card title="Итог последней проверки">
          {(protocol.summary_status === 'incomplete' || protocol.state === 'incomplete') ? (
            <Banner tone="warning">Проверка завершилась не полностью. Итог лучше просмотреть вручную.</Banner>
          ) : null}
          <div className="stack compact">
            <div><strong>Итог:</strong> {titleStatus(protocol.summary_status)}</div>
            <div>{protocol.summary_text}</div>
          </div>
          <div className="grid grid-2" style={{ marginTop: 12 }}>
            {Object.entries(groupedFindings).map(([group, findings]) => (
              <FindingsGroup key={group} title={group} findings={findings} solutionId={protocol.solution_version_id} />
            ))}
          </div>
        </Card>
      ) : null}
    </>
  );
}
