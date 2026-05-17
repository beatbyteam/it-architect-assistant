import { Card } from '../../shared/ui/components';
import { cleanDisplayFileName, formatDateTime, titleStatus } from '../../shared/lib/format';
import type { KnowledgeScope, KnowledgeScopeVersionSnapshot } from '../../types/api';

function renderVersionMeta(version?: KnowledgeScopeVersionSnapshot | null) {
  if (!version || !version.knowledge_version_id) {
    return <div className="muted small">Не зафиксирована</div>;
  }
  return (
    <div className="stack compact">
      <div><strong>Версия:</strong> <span className="mono">{version.version_code ?? version.knowledge_version_id}</span></div>
      <div><strong>ID:</strong> <span className="mono">{version.knowledge_version_id}</span></div>
      <div><strong>Статус:</strong> {titleStatus(version.status)}</div>
      <div><strong>Документов:</strong> {String(version.document_count ?? 0)} · <strong>оснований:</strong> {String(version.basis_document_count ?? 0)}</div>
      <div><strong>Создана:</strong> {formatDateTime(version.created_at)}</div>
      {version.activated_at ? <div><strong>Активирована:</strong> {formatDateTime(version.activated_at)}</div> : null}
    </div>
  );
}

export function KnowledgeScopeSummary(props: {
  scope?: KnowledgeScope | null;
  title?: string;
  subtitle?: string;
}) {
  const scope = props.scope;
  if (!scope) {
    return (
      <Card title={props.title ?? 'Область знаний'} subtitle={props.subtitle ?? 'Снимок базы знаний для этого запуска.'}>
        <div className="muted small">Снимок базы знаний для этого результата не сохранён.</div>
      </Card>
    );
  }

  return (
    <Card title={props.title ?? 'Область знаний'} subtitle={props.subtitle ?? 'Какие версии знаний реально участвовали в подготовке и проверке решения.'}>
      <div className="grid grid-2">
        <div className="section-box">
          <h3>Обязательная baseline-база</h3>
          <div className="muted small" style={{ marginBottom: 8 }}>
            {scope.mandatory_version?.knowledge_base_code ?? 'mandatory_architecture_baseline'}
          </div>
          {renderVersionMeta(scope.mandatory_version)}
        </div>
        <div className="section-box">
          <h3>Выбранная база знаний</h3>
          <div className="muted small" style={{ marginBottom: 8 }}>
            {scope.selected_user_version?.knowledge_base_code ?? 'user_managed'}
          </div>
          {renderVersionMeta(scope.selected_user_version)}
        </div>
      </div>
      <div className="section-box" style={{ marginTop: 12 }}>
        <div><strong>Идентификаторы участвующих версий:</strong></div>
        {(scope.effective_version_ids ?? []).length ? (
          <ul className="compact-list" style={{ marginTop: 8 }}>
            {scope.effective_version_ids.map((item) => <li key={item}><span className="mono">{item}</span></li>)}
          </ul>
        ) : (
          <div className="muted small" style={{ marginTop: 8 }}>Нет сохранённых идентификаторов участвующих версий.</div>
        )}
        <div className="muted small" style={{ marginTop: 8 }}>
          Версия для снимка подготовки решения: <span className="mono">{scope.selected_generation_version_id ?? '—'}</span>
        </div>
      </div>
      {scope.document_scope?.mode === 'selected' ? (
        <div className="section-box" style={{ marginTop: 12 }}>
          <div><strong>Документы проверки:</strong> {String(scope.document_scope.document_count ?? 0)}</div>
          {(scope.document_scope.selected_documents ?? []).length ? (
            <ul className="compact-list" style={{ marginTop: 8 }}>
              {(scope.document_scope.selected_documents ?? []).map((item, index) => (
                <li key={String(item.document_id ?? index)}>
                  {cleanDisplayFileName(String(item.title ?? '')) ?? String(item.title ?? item.document_id ?? 'Документ')}
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Card>
  );
}
