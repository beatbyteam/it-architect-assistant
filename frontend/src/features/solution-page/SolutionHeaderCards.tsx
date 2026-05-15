import { Link } from 'react-router-dom';

import { Badge, Button, Card } from '../../shared/ui/components';
import { formatDateTime, titleStatus } from '../../shared/lib/format';
import type {
  NormalizedSolution,
  NormalizedSolutionArchitectureModel,
  NormalizedVerificationRun,
} from '../../shared/api/normalized';

interface SolutionHeaderCardsProps {
  copied: boolean;
  solution: NormalizedSolution;
  architectureModel: NormalizedSolutionArchitectureModel;
  verificationRun: NormalizedVerificationRun | null | undefined;
  verificationOperationId: string | null;
  normalizedEntityCount: number;
  readyCount: number;
  partialCount: number;
  insufficientCount: number;
  relationCount: number;
  publicationRevisionNo?: string | number | null;
  onCopyLink: () => void;
}

export function SolutionHeaderCards({
  copied,
  solution,
  architectureModel,
  verificationRun,
  verificationOperationId,
  normalizedEntityCount,
  readyCount,
  partialCount,
  insufficientCount,
  relationCount,
  publicationRevisionNo,
  onCopyLink,
}: SolutionHeaderCardsProps) {
  return (
    <>
      <div className="grid grid-2">
        <Card title="Паспорт решения">
          <div className="stack compact">
            <div><strong>Статус:</strong> {titleStatus(solution.state)}</div>
            <div><strong>Опубликовано:</strong> {formatDateTime(solution.published_at)}</div>
            <div><strong>Версия знаний:</strong> <span className="mono">{solution.knowledge_version_id ?? '—'}</span></div>
            <div><strong>Запуск подготовки:</strong> <span className="mono">{solution.generation_run_id}</span></div>
            <div><strong>Версия публикации:</strong> {String(publicationRevisionNo ?? '—')}</div>
            <div><strong>TOGAF-секций:</strong> {solution.sections.length}</div>
            <div><strong>Нормализованных сущностей:</strong> {normalizedEntityCount} / {architectureModel.entities.length}</div>
          </div>
        </Card>

        <Card title="Проверка решения">
          <div className="stack compact">
            <div><strong>Состояние:</strong> <Badge value={verificationRun?.run_state ?? verificationRun?.state ?? solution.verification_runs[0]?.state ?? 'draft'} /></div>
            <div><strong>Текущий этап:</strong> {titleStatus(verificationRun?.current_stage)}</div>
            {verificationRun?.protocol_id ? <Link className="button" to={`/protocols/${verificationRun.protocol_id}`}>Открыть протокол</Link> : null}
            {verificationOperationId ? <Link className="button" to={`/operations/${verificationOperationId}`}>Открыть операцию</Link> : null}
          </div>
          <div className="actions" style={{ marginTop: 12 }}>
            <Button type="button" onClick={onCopyLink}>{copied ? 'Ссылка скопирована' : 'Скопировать ссылку'}</Button>
          </div>
        </Card>
      </div>

      <div className="grid grid-4">
        <Card title="Готовые секции"><strong>{readyCount}</strong></Card>
        <Card title="Частично готовые"><strong>{partialCount}</strong></Card>
        <Card title="Недостаточно данных"><strong>{insufficientCount}</strong></Card>
        <Card title="Связей в модели"><strong>{relationCount}</strong></Card>
      </div>
    </>
  );
}
