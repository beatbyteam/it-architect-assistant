import assert from 'node:assert/strict';
import test from 'node:test';

import { queryKeys } from '../../src/shared/api/queryKeys';
import { renderAppAt } from '../support/render';
import {
  activeKnowledgeVersion,
  dashboardTask,
  generationRun,
  knowledgeBase,
  knowledgeNotification,
  knowledgeSource,
  mandatoryBase,
  metrics,
  protocol,
  solution,
  task,
  verificationRun,
} from '../support/fixtures';

const dashboardSeeds = [
  { key: ['dashboard-tasks'] as const, data: [dashboardTask] },
  { key: ['dashboard-active-version'] as const, data: activeKnowledgeVersion },
  { key: ['dashboard-knowledge-bases'] as const, data: [knowledgeBase, mandatoryBase] },
  { key: ['dashboard-knowledge-notifications'] as const, data: [knowledgeNotification] },
  { key: ['dashboard-solutions'] as const, data: [solution] },
  { key: ['dashboard-protocols'] as const, data: [protocol] },
];

const knowledgeSeeds = [
  { key: ['knowledge-bases'] as const, data: [knowledgeBase, mandatoryBase] },
  { key: ['knowledge-sources-registry'] as const, data: [knowledgeSource] },
  { key: ['knowledge-notifications'] as const, data: [knowledgeNotification] },
  { key: ['operation-metrics'] as const, data: metrics },
];

const workspaceSeeds = [
  { key: queryKeys.task('task-1'), data: task },
  { key: queryKeys.taskActiveVersion('task-1'), data: activeKnowledgeVersion },
  { key: queryKeys.generationRun('generation-run-1'), data: generationRun },
  { key: queryKeys.solution('solution-1'), data: solution },
  { key: queryKeys.solutionRendered('solution-1'), data: { rendered_html: '<article>solution</article>' } },
  { key: queryKeys.verificationRun('verification-run-1'), data: verificationRun },
  { key: queryKeys.protocol('protocol-1'), data: protocol },
];

const solutionSeeds = [
  { key: queryKeys.solution('solution-1'), data: solution },
  { key: queryKeys.solutionRendered('solution-1'), data: { rendered_html: '<article>solution</article>', publication_revision_no: 'rev-3' } },
  { key: queryKeys.solutionModel('solution-1'), data: { architecture_model: solution.architecture_model } },
  { key: queryKeys.solutionSectionAssessments('solution-1'), data: { section_assessments: solution.section_assessments } },
  { key: queryKeys.verificationRun('verification-run-1'), data: verificationRun },
];

const protocolSeeds = [
  { key: queryKeys.protocol('protocol-1'), data: protocol },
  { key: queryKeys.protocolRendered('protocol-1'), data: { explainability: protocol.explainability, publication_history: [] } },
  { key: queryKeys.protocolViolations('protocol-1'), data: { violations: protocol.findings } },
];

test('dashboard route renders preloaded content', () => {
  const html = renderAppAt('/', dashboardSeeds);
  assert.match(html, /Главная/);
  assert.match(html, /Архитектура сервиса согласования/);
  assert.match(html, /Последние задачи/);
});

test('knowledge route renders registry and notifications', () => {
  const html = renderAppAt('/knowledge', knowledgeSeeds);
  assert.match(html, /Базы знаний/);
  assert.match(html, /ERP baseline/);
  assert.match(html, /Обновление завершено/);
});

test('task workspace route renders readiness and actions', () => {
  const html = renderAppAt('/tasks/task-1', workspaceSeeds);
  assert.match(html, /Что нужно для запуска/);
  assert.match(html, /Архитектура сервиса согласования/);
  assert.match(html, /Можно запускать подготовку решения/);
});

test('task workspace preserves user line breaks and indentation', () => {
  const formattedText = '1. Цель решения\n  - сохранить переносы\n\n2. Ограничения';
  const formattedWorkspaceSeeds = workspaceSeeds.map((seed) => (
    seed.key[0] === 'task' && seed.key[1] === 'task-1'
      ? { ...seed, data: { ...task, raw_text: formattedText } }
      : seed
  ));
  const html = renderAppAt('/tasks/task-1', formattedWorkspaceSeeds);
  assert.match(html, /preserve-lines task-raw-text/);
  assert.ok(html.includes(formattedText));
});

test('external architecture check route renders form', () => {
  const html = renderAppAt('/external-check');
  assert.match(html, /General information/);
  assert.match(html, /Application architecture/);
});

test('solution route renders document tabs and scope summary', () => {
  const html = renderAppAt('/solutions/solution-1', solutionSeeds);
  assert.match(html, /TOGAF-документ/);
  assert.match(html, /Архитектурная модель/);
  assert.match(html, /Область знаний решения/);
});

test('protocol route renders grouped findings and explainability', () => {
  const html = renderAppAt('/protocols/protocol-1', protocolSeeds);
  assert.match(html, /Протокол проверки/);
  assert.match(html, /Есть замечания по структурному разделу/);
  assert.match(html, /general_information/);
});
