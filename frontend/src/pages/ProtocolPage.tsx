import { type ChangeEvent, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useParams } from 'react-router-dom';

import {
  getVerificationProtocol,
  getVerificationProtocolRendered,
  getVerificationProtocolViolations,
} from '../shared/api/verification';
import { queryKeys } from '../shared/api/queryKeys';
import { sanitizeHtml } from '../shared/lib/html';
import { Badge, Banner, Button, Card, CollapsibleCodeBlock, EmptyState, ErrorState, Input, LoadingState, PageHeader, Select, StateBox } from '../shared/ui/components';
import { KnowledgeScopeSummary } from '../entities/knowledge/KnowledgeScopeSummary';
import { cleanDisplayFileName, formatDateTime, titleStatus, verificationFindingImpact, verificationRuleGroupLabel } from '../shared/lib/format';
import {
  normalizeVerificationProtocol,
} from '../shared/api/normalized';
import type { NormalizedVerificationProtocol } from '../shared/api/normalized';
import type {
  PublicationRevision,
  VerificationFinding,
  VerificationProtocolViolation,
} from '../types/api';

function diagnosticsOperationId(diagnostics?: Record<string, unknown> | null, fallbackOperationId?: string | null) {
  const value = diagnostics?.operation_id ?? diagnostics?.run_operation_id ?? diagnostics?.operation_ref ?? fallbackOperationId;
  return typeof value === 'string' ? value : null;
}

function normalizeFindings(value: VerificationFinding[] | VerificationProtocolViolation[] | null | undefined): VerificationFinding[] {
  return Array.isArray(value) ? (value as VerificationFinding[]) : [];
}

function compactEvidenceLabel(value?: string | null) {
  if (!value) return null;
  const sourceMatch = value.match(/([A-Za-z0-9А-Яа-яЁё_. -]+\.(?:pdf|docx?|xlsx?|md|txt|csv))/i);
  const sourceLocationMatch = value.match(/(?:fragment|chunk|compact|section|раздел|фрагмент)\s*[:#]?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)/i);
  const source = cleanDisplayFileName(sourceMatch?.[1]) ?? null;
  const location = sourceLocationMatch?.[1] ? `фрагмент ${sourceLocationMatch[1]}` : null;
  if (source && location) return `${source} · ${location}`;
  if (source) return source;
  const sectionMatch = value.match(/section[_ -]?([A-Za-zА-Яа-яЁё0-9_.-]+)/i);
  if (sectionMatch?.[1]) return `Раздел ${sectionMatch[1]}`;
  return value
    .replace(/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/gi, '')
    .replace(/\b[a-f0-9]{24,}\b/gi, '')
    .replace(/\s+/g, ' ')
    .replace(/^[\s|:;,-]+|[\s|:;,-]+$/g, '')
    .slice(0, 160) || 'Документ-основание';
}

function ImpactBadge(props: { finding: VerificationFinding }) {
  const impact = verificationFindingImpact(props.finding.status, props.finding.severity);
  return <span className={`badge badge-${impact.tone}`}>{impact.label}</span>;
}

export function ProtocolPage() {
  const { protocolId = '' } = useParams();
  const [search, setSearch] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [groupFilter, setGroupFilter] = useState('');
  const [exportNotice, setExportNotice] = useState('');

  const protocolQuery = useQuery({
    queryKey: queryKeys.protocol(protocolId),
    queryFn: ({ signal }) => getVerificationProtocol(protocolId, { signal }),
    enabled: Boolean(protocolId),
  });
  const renderedQuery = useQuery({
    queryKey: queryKeys.protocolRendered(protocolId),
    queryFn: ({ signal }) => getVerificationProtocolRendered(protocolId, { signal }),
    enabled: Boolean(protocolId),
  });
  const shouldFetchViolations = Boolean(protocolId) && Boolean(protocolQuery.data) && (protocolQuery.data?.findings.length ?? 0) === 0;
  const violationsQuery = useQuery({
    queryKey: queryKeys.protocolViolations(protocolId),
    queryFn: ({ signal }) => getVerificationProtocolViolations(protocolId, { signal }),
    enabled: shouldFetchViolations,
  });

    const protocol: NormalizedVerificationProtocol = normalizeVerificationProtocol(protocolQuery.data);
  const effectiveFindings = protocol.findings.length > 0
    ? protocol.findings
    : normalizeFindings(violationsQuery.data?.violations);
  const impactTotals = useMemo(() => effectiveFindings.reduce<Record<string, number>>((acc, finding) => {
    const label = verificationFindingImpact(finding.status, finding.severity).label;
    acc[label] = (acc[label] ?? 0) + 1;
    return acc;
  }, {}), [effectiveFindings]);

  const groupedFindings = useMemo(() => {
    const filtered = effectiveFindings.filter((finding: VerificationFinding) => {
      const haystack = `${finding.rule_id ?? ''} ${finding.rule_name ?? ''} ${finding.finding_text ?? ''} ${finding.status} ${finding.severity} ${finding.related_section_ref ?? ''} ${finding.rule_group ?? ''}`.toLowerCase();
      return haystack.includes(search.toLowerCase())
        && (!severityFilter || finding.severity === severityFilter)
        && (!statusFilter || finding.status === statusFilter)
        && (!groupFilter || finding.rule_group === groupFilter);
    });
    const groups: Record<string, VerificationFinding[]> = {};
    filtered.forEach((finding: VerificationFinding) => {
      const key = finding.rule_group ?? 'other';
      groups[key] = groups[key] ?? [];
      groups[key].push(finding);
    });
    return groups;
  }, [effectiveFindings, groupFilter, search, severityFilter, statusFilter]);

  if (protocolQuery.isLoading) return <LoadingState message="Открываю протокол проверки…" />;
  if (protocolQuery.isError || !protocolQuery.data) return <ErrorState message="Не удалось загрузить протокол проверки." />;

  const blockerCount = effectiveFindings.filter((item) => item.status === 'failed' || item.status === 'not_determined').length;
  const diagnostics = protocol.diagnostics ?? null;
  const operationId = diagnosticsOperationId(diagnostics, protocol.verification_run_id);
  const explainability = (renderedQuery.data?.explainability ?? {}) as Record<string, unknown>;
  const basisPackage = ((explainability.basis_package as Record<string, unknown> | undefined) ?? {});
  const evidenceCoverage = ((explainability.evidence_coverage as Record<string, unknown> | undefined) ?? {});
  const ruleExecution = ((explainability.rule_execution as Record<string, unknown> | undefined) ?? {});
  const publicationHistory = ((protocol.publication_history ?? renderedQuery.data?.publication_history ?? []) as PublicationRevision[]);
  const snapshotSummary = ((protocol.snapshot_summary ?? renderedQuery.data?.snapshot_summary ?? {}) as Record<string, unknown>);
  const complianceSummary = protocol.compliance_summary;
  const complianceGroups = ((complianceSummary.groups ?? {}) as Record<string, Record<string, number>>);
  const groupOptions = Array.from(new Set([...Object.keys(complianceGroups), ...effectiveFindings.map((item) => item.rule_group ?? 'other')])).sort();
  const safeRenderedHtml = sanitizeHtml(renderedQuery.data?.rendered_html);

  return (
    <div className="stack">
      <PageHeader
        title="Протокол проверки"
        subtitle="Здесь собран итог проверки, список нарушений, группировка по правилам и адресные замечания по TOGAF и ArchiMate."
        actions={(
          <>
            <Button type="button" onClick={() => setExportNotice('Экспорт PDF появится после подключения backend-выгрузки.')}>Экспорт PDF</Button>
            <Button type="button" onClick={() => setExportNotice('Экспорт DOCX появится после подключения backend-выгрузки.')}>Экспорт DOCX</Button>
            <Link to={`/solutions/${protocol.solution_version_id}`} className="button">Вернуться к решению</Link>
          </>
        )}
      />

      {exportNotice ? <Banner tone="info">{exportNotice}</Banner> : null}

      {(protocol.summary_status === 'incomplete' || protocol.state === 'incomplete') ? (
        <Banner tone="warning">Проверка завершилась не полностью. Итог лучше просмотреть вручную.</Banner>
      ) : null}
      {blockerCount > 0 ? (
        <Banner tone="danger">В проверке есть {blockerCount} важных замечаний. Их нужно разобрать перед использованием результата.</Banner>
      ) : null}

      <div className="grid grid-4">
        <Card title="Итог"><Badge value={protocol.summary_status} /></Card>
        <Card title="Статус протокола"><Badge value={protocol.state} /></Card>
        <Card title="Критичных нарушений"><strong>{String(complianceSummary.critical_violation_count ?? 0)}</strong></Card>
        <Card title="Замечаний по TOGAF/ArchiMate"><strong>{String(complianceSummary.relevant_violation_count ?? 0)}</strong></Card>
      </div>

      <KnowledgeScopeSummary
        scope={protocol.knowledge_scope}
        title="Область знаний проверки"
        subtitle="Протокол фиксирует тот же knowledge scope, который использовался в generation и verification."
      />

      {safeRenderedHtml ? (
        <Card title="Веб-артефакт протокола" subtitle="Самостоятельное rendered-представление verification protocol.">
          <div className="html-preview" dangerouslySetInnerHTML={{ __html: safeRenderedHtml }} />
        </Card>
      ) : null}

      <div className="grid grid-2">
        <Card title="Паспорт протокола">
          <div className="stack compact">
            <div><strong>Дата выпуска:</strong> {formatDateTime(protocol.created_at)}</div>
            <div><strong>Версия знаний:</strong> <span className="mono">{protocol.knowledge_version_id}</span></div>
            <div><strong>Solution version:</strong> <span className="mono">{protocol.solution_version_id}</span></div>
            <div className="actions">
              {operationId ? <Link className="button" to={`/operations/${operationId}`}>Операция проверки</Link> : null}
              <Link className="button" to={`/solutions/${protocol.solution_version_id}`}>К решению</Link>
            </div>
          </div>
          <StateBox className="with-top-margin">{protocol.summary_text}</StateBox>
        </Card>

        <Card title="Фильтры и агрегаты">
          <div className="toolbar-grid toolbar-grid-4">
            <Input value={search} onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)} placeholder="Поиск по правилу, тексту замечания или разделу" />
            <Select value={severityFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setSeverityFilter(event.target.value)}>
              <option value="">Все уровни важности</option>
              <option value="critical">Критично</option>
              <option value="major">Серьёзно</option>
              <option value="minor">Незначительно</option>
              <option value="info">Информация</option>
            </Select>
            <Select value={statusFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setStatusFilter(event.target.value)}>
              <option value="">Все статусы</option>
              <option value="passed">Без замечаний</option>
              <option value="warning">Warning</option>
              <option value="failed">Ошибка</option>
              <option value="not_determined">Требует проверки вручную</option>
            </Select>
            <Select value={groupFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setGroupFilter(event.target.value)}>
              <option value="">Все группы правил</option>
              {groupOptions.map((group) => <option key={group} value={group}>{verificationRuleGroupLabel(group)}</option>)}
            </Select>
          </div>
          <div className="grid grid-3" style={{ marginTop: 12 }}>
            <div className="section-box">
              <strong>По статусам</strong>
              <ul className="compact-list">
                {Object.entries(protocol.totals_by_status).map(([key, value]) => <li key={key}>{titleStatus(key)}: {value}</li>)}
              </ul>
            </div>
            <div className="section-box">
              <strong>По оценке</strong>
              <ul className="compact-list">
                {Object.entries(impactTotals).map(([key, value]) => <li key={key}>{key}: {value}</li>)}
              </ul>
            </div>
            <div className="section-box">
              <strong>По весу правил</strong>
              <div className="muted small">Это не текущая критичность результата.</div>
              <ul className="compact-list">
                {Object.entries(protocol.totals_by_severity).map(([key, value]) => <li key={key}>{titleStatus(key)}: {value}</li>)}
              </ul>
            </div>
          </div>
        </Card>
      </div>

      <Card
        title="Оценка проверок"
        subtitle="Здесь статус проверки отделён от важности правила: пройденная критичная проверка считается нормальной, а не критичным замечанием."
      >
        {effectiveFindings.length === 0 ? (
          <EmptyState title="Проверки пока не найдены" />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Группа</th>
                  <th>Проверка</th>
                  <th>Результат</th>
                  <th>Оценка</th>
                  <th>Важность правила</th>
                </tr>
              </thead>
              <tbody>
                {effectiveFindings.map((finding: VerificationFinding) => {
                  const impact = verificationFindingImpact(finding.status, finding.severity);
                  return (
                    <tr key={finding.check_result_id ?? finding.rule_id ?? `${finding.rule_group}-${finding.sort_order}`}>
                      <td>{verificationRuleGroupLabel(finding.rule_group ?? 'other')}</td>
                      <td>{finding.rule_name ?? finding.rule_id ?? 'Проверка'}</td>
                      <td><Badge value={finding.status} /></td>
                      <td>
                        <div className="stack compact">
                          <ImpactBadge finding={finding} />
                          <span className="muted small">{impact.description}</span>
                        </div>
                      </td>
                      <td>{titleStatus(finding.severity)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Compliance summary" subtitle="Отдельная сводка по структуре TOGAF, метамодели ArchiMate и семантической согласованности.">
        {Object.keys(complianceGroups).length === 0 ? <EmptyState title="Сводка по группам пока недоступна" /> : (
          <div className="grid grid-4">
            {Object.entries(complianceGroups).map(([group, values]) => (
              <Card key={group} title={verificationRuleGroupLabel(group)}>
                <div className="stack compact">
                  <div><strong>Всего:</strong> {String(values.count ?? 0)}</div>
                  <div><strong>Failed:</strong> {String(values.failed ?? 0)}</div>
                  <div><strong>Warnings:</strong> {String(values.warnings ?? 0)}</div>
                  <div><strong>Incomplete:</strong> {String(values.incomplete ?? 0)}</div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </Card>

      <div className="grid grid-2">
        <Card title="Пояснение к проверке" subtitle="Показывает, насколько полно проверка опиралась на материалы.">
          <div className="stack compact">
            <div><strong>Версия правил:</strong> {String(ruleExecution.rulebook_version ?? '—')}</div>
            <div><strong>Объём проверки:</strong> {String(ruleExecution.validation_scope ?? 'full')}</div>
            <div><strong>Проверенные группы:</strong> {Array.isArray(ruleExecution.executed_rule_groups) ? ruleExecution.executed_rule_groups.map((value) => verificationRuleGroupLabel(String(value))).join(', ') || '—' : '—'}</div>
            <div><strong>Замечаний с основанием:</strong> {String(evidenceCoverage.findings_with_evidence ?? 0)} / {String(evidenceCoverage.finding_count ?? effectiveFindings.length)}</div>
            <div><strong>Обязательных материалов:</strong> {String(basisPackage.required_basis_count ?? 0)} / {String(basisPackage.basis_document_count ?? protocol.basis_documents.length)}</div>
          </div>
        </Card>
        <Card title="Снимок базы знаний">
          <CollapsibleCodeBlock>{JSON.stringify(explainability.knowledge_snapshot ?? {}, null, 2)}</CollapsibleCodeBlock>
        </Card>
      </div>

      <div className="grid grid-2">
        <Card title="Сводка по снимку">
          <CollapsibleCodeBlock>{JSON.stringify(snapshotSummary, null, 2)}</CollapsibleCodeBlock>
        </Card>
        <Card title="История публикаций протокола">
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

      <Card title="Материалы проверки" subtitle="Список материалов, которые использовались при проверке.">
        {protocol.basis_documents.length === 0 ? (
          <EmptyState title="Список документов пуст" description="Это означает, что проверке не хватило материалов-оснований." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Документ</th><th>Роль</th><th>Версия</th><th>Обязательный</th></tr>
              </thead>
              <tbody>
                {protocol.basis_documents.map((item) => (
                  <tr key={item.protocol_basis_document_id ?? `${item.title}-${item.sort_order}`}>
                    <td>{item.title}</td>
                    <td>{item.role_code ?? '—'}</td>
                    <td>{item.version_ref ?? '—'}</td>
                    <td>{item.required_flag ? 'Да' : 'Нет'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Замечания и нарушения" subtitle="Здесь показаны адресные нарушения, сгруппированные по rule group из verification API.">
        {Object.keys(groupedFindings).length === 0 ? (
          <EmptyState title="По текущему фильтру ничего не найдено" />
        ) : (
          <div className="stack">
            {Object.entries(groupedFindings).map(([group, findings]) => (
              <div className="section-box" key={group}>
                <div className="actions between">
                  <h3>{verificationRuleGroupLabel(group)}</h3>
                  <span className="muted small">{findings.length} проверок</span>
                </div>
                <div className="timeline">
                  {findings.map((finding: VerificationFinding) => (
                    <div className="timeline-item" key={finding.check_result_id ?? finding.rule_id ?? `${group}-${finding.related_section_ref ?? 'finding'}`}>
                      <div className="actions between">
                        <strong>
                          {finding.rule_name ?? finding.rule_id ?? 'Проверка'}
                        </strong>
                        <span className="muted small">{titleStatus(finding.status)} · {verificationFindingImpact(finding.status, finding.severity).label}</span>
                      </div>
                      <div>{finding.finding_text ?? 'Замечаний нет.'}</div>
                      {finding.evidence ? <div className="muted small">Основание: {compactEvidenceLabel(finding.evidence)}</div> : null}
                      {finding.related_section_ref ? (
                        <div className="actions">
                          <span className="muted small">Раздел решения: {finding.related_section_ref}</span>
                          <Link className="button" to={`/solutions/${protocol.solution_version_id}#section-${finding.related_section_ref}`}>Перейти к разделу решения</Link>
                        </div>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {Array.isArray(evidenceCoverage.findings_without_evidence) && evidenceCoverage.findings_without_evidence.length ? (
        <Card title="Что ещё стоит проверить вручную" subtitle="Эти замечания требуют ручного просмотра, потому что для них не хватает явной ссылки на основание.">
          <ul className="compact-list">
            {(evidenceCoverage.findings_without_evidence as unknown[]).map((item, index) => <li key={`${index}`}>{String(item)}</li>)}
          </ul>
        </Card>
      ) : null}

      {diagnostics ? (
        <Card title="Техническая диагностика">
          <CollapsibleCodeBlock>{JSON.stringify(diagnostics, null, 2)}</CollapsibleCodeBlock>
        </Card>
      ) : null}
    </div>
  );
}
