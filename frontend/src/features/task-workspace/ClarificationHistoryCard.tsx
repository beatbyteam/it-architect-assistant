import { Card } from '../../shared/ui/components';
import { formatDateTime, titleStatus } from '../../shared/lib/format';
import type { NormalizedClarificationRequest } from '../../shared/api/normalized';

interface ClarificationHistoryCardProps {
  clarifications: NormalizedClarificationRequest[];
}

export function ClarificationHistoryCard({ clarifications }: ClarificationHistoryCardProps) {
  return (
    <Card title="История уточнений">
      <div className="timeline">
        {clarifications.map((clarification) => (
          <div className="timeline-item" key={clarification.clarification_id}>
            <div className="actions between">
              <strong>Уточнение</strong>
              <span className="muted small">{titleStatus(clarification.state)}</span>
            </div>
            <div className="muted small">
              Создано: {formatDateTime(clarification.created_at)} · Закрыто: {formatDateTime(clarification.closed_at)}
            </div>
            {clarification.answers.length ? (
              <ul className="compact-list">
                {clarification.answers.map((answer) => (
                  <li key={answer.clarification_answer_id}>
                    <div style={{ fontWeight: 700, marginBottom: '0.25rem' }}>
                      {answer.question_text ?? answer.question_code}
                    </div>
                    <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{answer.answer_text}</div>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        ))}
      </div>
    </Card>
  );
}
