import assert from 'node:assert/strict';
import test from 'node:test';

import {
  auditEventTitle,
  auditMessageText,
  solutionSectionLabel,
  titleStatus,
  verificationFindingImpact,
  verificationRuleGroupLabel,
} from '../../src/shared/lib/format';
import { matchesSearch } from '../../src/shared/lib/search';

test('search matches localized status titles', () => {
  const parts = ['completed', titleStatus('completed')];

  assert.equal(matchesSearch(parts, 'завершено'), true);
  assert.equal(matchesSearch(parts, 'completed'), true);
});

test('search matches numeric tokens in task titles', () => {
  const parts = ['task-id', 'Задача 1', titleStatus('draft')];

  assert.equal(matchesSearch(parts, 'задача 1'), true);
  assert.equal(matchesSearch(parts, '1'), true);
});

test('search reads audit event translations and payload values', () => {
  const parts = [
    'generation.business_task.created',
    auditEventTitle('generation.business_task.created'),
    'Business task created through canonical MVP intake',
    auditMessageText('Business task created through canonical MVP intake'),
    { title: 'Задача 1', initial_state: 'draft' },
  ];

  assert.equal(matchesSearch(parts, 'создана задача'), true);
  assert.equal(matchesSearch(parts, 'черновик'), true);
  assert.equal(matchesSearch(parts, '1'), true);
});

test('search normalizes underscores and yo letters', () => {
  const parts = ['completed_with_warnings', titleStatus('completed_with_warnings')];

  assert.equal(matchesSearch(parts, 'completed warnings'), true);
  assert.equal(matchesSearch(parts, 'завершено с замечаниями'), true);
});

test('search matches verification protocol visible labels', () => {
  const warningImpact = verificationFindingImpact('warning', 'major');
  const failedImpact = verificationFindingImpact('failed', 'critical');
  const passedImpact = verificationFindingImpact('passed', 'critical');

  const warningParts = [
    {
      rule_id: 'VR-SEM-02',
      rule_name: 'Application components are supported by technology nodes/services',
      status: 'warning',
      severity: 'major',
      rule_group: 'consistency',
      related_section_ref: 'technology_architecture',
    },
    titleStatus('warning'),
    titleStatus('major'),
    verificationRuleGroupLabel('consistency'),
    solutionSectionLabel('technology_architecture'),
    warningImpact.label,
    warningImpact.description,
  ];

  assert.equal(matchesSearch(warningParts, 'предупреждение'), true);
  assert.equal(matchesSearch(warningParts, 'есть замечание'), true);
  assert.equal(matchesSearch(warningParts, 'семантическая'), true);
  assert.equal(matchesSearch(warningParts, 'technology'), true);

  const failedParts = ['failed', titleStatus('failed'), 'critical', titleStatus('critical'), failedImpact.label];
  const passedParts = ['passed', titleStatus('passed'), passedImpact.label, passedImpact.description];

  assert.equal(matchesSearch(failedParts, 'ошибка'), true);
  assert.equal(matchesSearch(failedParts, 'критично'), true);
  assert.equal(matchesSearch(passedParts, 'без замечаний'), true);
  assert.equal(matchesSearch(passedParts, 'нормально'), true);
});
