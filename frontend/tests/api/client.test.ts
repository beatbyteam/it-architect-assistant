import assert from 'node:assert/strict';
import test from 'node:test';

import { uploadAndIngestKnowledgeFiles } from '../../src/shared/api/knowledge';
import { getApiErrorMessage, request } from '../../src/shared/api/client';

test('request omits json header for GET without body and parses payload', async () => {
  const originalFetch = global.fetch;
  let capturedContentType = '';
  global.fetch = (async (_input, init) => {
    const headers = new Headers(init?.headers);
    capturedContentType = headers.get('Content-Type') ?? '';
    return new Response(JSON.stringify({ ok: true, value: 7 }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }) as typeof fetch;

  try {
    const payload = await request<{ ok: boolean; value: number }>('/health');
    assert.equal(capturedContentType, '');
    assert.deepEqual(payload, { ok: true, value: 7 });
  } finally {
    global.fetch = originalFetch;
  }
});

test('request forwards abort signal to fetch', async () => {
  const originalFetch = global.fetch;
  const controller = new AbortController();
  let capturedSignal: AbortSignal | undefined;
  global.fetch = (async (_input, init) => {
    capturedSignal = init?.signal ?? undefined;
    return new Response(JSON.stringify({ ok: true }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }) as typeof fetch;

  try {
    await request<{ ok: boolean }>('/health', { signal: controller.signal });
    assert.equal(capturedSignal, controller.signal);
  } finally {
    global.fetch = originalFetch;
  }
});

test('request raises structured error and helper extracts best message', async () => {
  const originalFetch = global.fetch;
  global.fetch = (async () => new Response(JSON.stringify({ user_message: 'Проверка не пройдена' }), { status: 422, headers: { 'Content-Type': 'application/json' } })) as typeof fetch;

  try {
    await assert.rejects(async () => {
      await request('/knowledge');
    }, (error: unknown) => {
      assert.equal(getApiErrorMessage(error), 'Проверка не пройдена');
      return true;
    });
  } finally {
    global.fetch = originalFetch;
  }
});


test('request formats FastAPI validation detail arrays', async () => {
  const originalFetch = global.fetch;
  global.fetch = (async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'raw_text'], msg: 'Field required' }] }), { status: 422, headers: { 'Content-Type': 'application/json' } })) as typeof fetch;

  try {
    await assert.rejects(async () => {
      await request('/tasks');
    }, (error: unknown) => {
      assert.equal(getApiErrorMessage(error), 'описание задачи: Поле обязательно.');
      return true;
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test('request prefers backend validation details over generic validation summary', async () => {
  const originalFetch = global.fetch;
  global.fetch = (async () => new Response(JSON.stringify({
    user_message: 'Request validation failed',
    message: 'Request validation failed',
    details: {
      errors: [{ loc: ['body', 'raw_text'], msg: 'Field required' }],
    },
  }), { status: 422, headers: { 'Content-Type': 'application/json' } })) as typeof fetch;

  try {
    await assert.rejects(async () => {
      await request('/tasks');
    }, (error: unknown) => {
      assert.equal(getApiErrorMessage(error), 'описание задачи: Поле обязательно.');
      return true;
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test('request translates known backend error codes before raw technical messages', async () => {
  const originalFetch = global.fetch;
  global.fetch = (async () => new Response(JSON.stringify({
    error_code: 'NO_ACTIVE_SOURCE_SET',
    message: 'No active knowledge sources available',
  }), { status: 422, headers: { 'Content-Type': 'application/json' } })) as typeof fetch;

  try {
    await assert.rejects(async () => {
      await request('/knowledge/bases/kb-1/sync');
    }, (error: unknown) => {
      assert.equal(
        getApiErrorMessage(error),
        'В базе знаний нет активных источников или загруженных документов. Добавьте источник либо загрузите файл, затем запустите обновление.',
      );
      return true;
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test('request translates knowledge upload errors before raw technical messages', async () => {
  const originalFetch = global.fetch;
  global.fetch = (async () => new Response(JSON.stringify({
    error_code: 'KNOWLEDGE_UPLOAD_FILE_INVALID',
    message: 'Unsupported or damaged knowledge document',
  }), { status: 422, headers: { 'Content-Type': 'application/json' } })) as typeof fetch;

  try {
    await assert.rejects(async () => {
      await request('/knowledge/uploads/ingest-batch');
    }, (error: unknown) => {
      assert.equal(
        getApiErrorMessage(error),
        'Файл не удалось разобрать: он повреждён, пустой или имеет неподдерживаемое содержимое.',
      );
      return true;
    });
  } finally {
    global.fetch = originalFetch;
  }
});

test('uploadAndIngestKnowledgeFiles posts all files as one multipart ingest request', async () => {
  const originalFetch = global.fetch;
  let capturedUrl = '';
  let capturedBody: BodyInit | null | undefined;
  let capturedContentType = '';
  global.fetch = (async (input, init) => {
    capturedUrl = String(input);
    capturedBody = init?.body;
    capturedContentType = new Headers(init?.headers).get('Content-Type') ?? '';
    return new Response(JSON.stringify({ documents: [], update_run: { update_run_id: 'run-1' } }), {
      status: 202,
      headers: { 'Content-Type': 'application/json' },
    });
  }) as typeof fetch;

  try {
    const firstFile = new File(['first'], 'first.md', { type: 'text/markdown' });
    const secondFile = new File(['second'], 'second.md', { type: 'text/markdown' });

    await uploadAndIngestKnowledgeFiles({
      files: [firstFile, secondFile],
      title: 'Uploaded',
      knowledge_base_id: 'kb-1',
      execute_update_inline: false,
      reason: 'batch_upload:kb-1',
    });

    assert.match(capturedUrl, /\/knowledge\/uploads\/ingest-batch$/);
    assert.equal(capturedContentType, '');
    assert.ok(capturedBody instanceof FormData);
    assert.equal(capturedBody.getAll('files').length, 2);
    assert.equal(capturedBody.get('title'), 'Uploaded');
    assert.equal(capturedBody.get('knowledge_base_id'), 'kb-1');
    assert.equal(capturedBody.get('execute_update_inline'), 'false');
    assert.equal(capturedBody.get('reason'), 'batch_upload:kb-1');
  } finally {
    global.fetch = originalFetch;
  }
});
