import { Link } from 'react-router-dom';

import { titleStatus, verificationFindingImpact } from '../../shared/lib/format';
import type { VerificationFinding } from '../../types/api';

export function FindingsGroup(props: { title: string; findings: VerificationFinding[]; solutionId: string }) {
  return (
    <div className="stack compact">
      <h3>{props.title}</h3>
      <div className="timeline">
        {props.findings.map((finding: VerificationFinding, index: number) => (
          <div className="timeline-item" key={finding.check_result_id ?? finding.rule_id ?? `${props.title}-${index}`}>
            <div className="actions between">
              <strong>{finding.rule_name ?? finding.rule_id ?? 'Проверка'}</strong>
              <span className="muted small">{titleStatus(finding.status)} · {verificationFindingImpact(finding.status, finding.severity).label}</span>
            </div>
            <div>{finding.finding_text ?? 'Замечаний нет.'}</div>
            {finding.evidence ? <div className="muted small">Основание: {finding.evidence}</div> : null}
            {finding.related_section_ref ? (
              <div className="actions">
                <span className="muted small">Раздел: {finding.related_section_ref}</span>
                <Link className="button" to={`/solutions/${props.solutionId}#section-${finding.related_section_ref}`}>Открыть раздел</Link>
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
