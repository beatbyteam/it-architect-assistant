import { Link } from 'react-router-dom';

import { Badge, Card, EmptyState } from '../../shared/ui/components';
import { formatDateTime } from '../../shared/lib/format';
import type { NormalizedSolution } from '../../shared/api/normalized';
import type { PublicationRevision } from '../../types/api';

interface SolutionHistoryTabProps {
  solution: NormalizedSolution;
  publicationHistory: PublicationRevision[];
}

export function SolutionHistoryTab({ solution, publicationHistory }: SolutionHistoryTabProps) {
  return (
    <div className="stack">
      <Card title="История и связанные протоколы">
        {solution.verification_runs.length === 0 ? (
          <EmptyState title="Проверок пока нет" />
        ) : (
          <div className="timeline">
            {solution.verification_runs.map((run) => (
              <div className="timeline-item" key={run.verification_run_id}>
                <div className="actions between">
                  <strong>Проверка</strong>
                  <Badge value={run.state} />
                </div>
                <div className="muted small">Старт: {formatDateTime(run.started_at)}</div>
                <div className="actions">
                  {run.protocol_id ? <Link className="button" to={`/protocols/${run.protocol_id}`}>Открыть протокол</Link> : null}
                  <Link className="button" to={`/tasks/${solution.task_id}`}>Вернуться в рабочую область</Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="История публикаций">
        {publicationHistory.length === 0 ? <EmptyState title="Ревизий публикации пока нет" /> : (
          <div className="timeline">
            {publicationHistory.map((item) => (
              <div className="timeline-item" key={item.published_artifact_id}>
                <div className="actions between">
                  <strong>Версия {item.revision_no}</strong>
                  <Badge value={item.state} />
                </div>
                <div className="muted small">публикация {item.published_artifact_id}</div>
                <div className="muted small">опубликовано {formatDateTime(item.published_at)} · заменено {formatDateTime(item.superseded_at)}</div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
