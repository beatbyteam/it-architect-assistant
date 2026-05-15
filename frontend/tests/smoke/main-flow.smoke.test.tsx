import assert from 'node:assert/strict';
import test from 'node:test';

import { queryKeys } from '../../src/shared/api/queryKeys';
import { renderAppAt } from '../support/render';
import { activeKnowledgeVersion, generationRun, protocol, solution, task, verificationRun } from '../support/fixtures';

test('main solution flow route resolves from task workspace to linked artifacts', () => {
  const html = renderAppAt('/tasks/task-1', [
    { key: queryKeys.task('task-1'), data: task },
    { key: queryKeys.taskActiveVersion('task-1'), data: activeKnowledgeVersion },
    { key: queryKeys.generationRun('generation-run-1'), data: generationRun },
    { key: queryKeys.solution('solution-1'), data: solution },
    { key: queryKeys.solutionRendered('solution-1'), data: { rendered_html: '<article>solution</article>' } },
    { key: queryKeys.verificationRun('verification-run-1'), data: verificationRun },
    { key: queryKeys.protocol('protocol-1'), data: protocol },
  ]);

  assert.match(html, /\/solutions\/solution-1/);
  assert.match(html, /\/protocols\/protocol-1/);
  assert.match(html, /\/operations\/op-generation-1/);
  assert.match(html, /\/operations\/op-verification-1/);
});
