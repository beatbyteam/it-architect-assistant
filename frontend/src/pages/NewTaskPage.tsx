import { type ChangeEvent, type FormEvent, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';

import { createTask } from '../shared/api/tasks';
import { getActiveKnowledgeVersion, getKnowledgeBases } from '../shared/api/knowledge';
import { getApiErrorStatus } from '../shared/api/client';
import { KnowledgeScopeSelector } from '../entities/knowledge/KnowledgeScopeSelector';
import { Banner, Button, Card, ErrorNotice, FormRow, Input, PageHeader, Textarea } from '../shared/ui/components';
import { formatKnowledgeVersionLabel } from '../shared/lib/format';
import type { KnowledgeBase, TaskSnapshot } from '../types/api';

const MIN_TASK_LENGTH = 20;
type SubmitMode = 'draft' | 'submit';

export function NewTaskPage() {
  const navigate = useNavigate();
  const activeVersionQuery = useQuery({
    queryKey: ['new-task-active-version'],
    queryFn: ({ signal }) => getActiveKnowledgeVersion({ signal }),
    staleTime: 30_000,
    retry: false,
  });
  const basesQuery = useQuery({
    queryKey: ['knowledge-bases-selector'],
    queryFn: ({ signal }) => getKnowledgeBases({ signal }),
    staleTime: 15_000,
  });
  const [title, setTitle] = useState('');
  const [taskText, setTaskText] = useState('');
  const [localError, setLocalError] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<SubmitMode | null>(null);
  const [knowledgeSelectionSaved, setKnowledgeSelectionSaved] = useState(false);
  const idempotencyRef = useRef<{ key: string; fingerprint: string } | null>(null);

  const mutation = useMutation({
    mutationFn: createTask,
    onSuccess: (task: TaskSnapshot) => {
      idempotencyRef.current = null;
      navigate(`/tasks/${task.task_id}`);
    },
    onSettled: () => setPendingAction(null),
  });

  const qualityHints = useMemo(() => [
    'цель и ожидаемый бизнес-результат;',
    'текущий контекст или исходная система;',
    'ограничения: сроки, безопасность, нагрузка, бюджет;',
    'интеграции: API, сервисы, базы данных, очереди;',
    'ожидаемый результат: концепт, схема, компонентная модель или рекомендации.',
  ], []);

  const submit = (saveAsDraft: boolean) => {
    const mode: SubmitMode = saveAsDraft ? 'draft' : 'submit';
    const normalizedText = taskText.trim();
    if (!saveAsDraft && normalizedText.length < MIN_TASK_LENGTH) {
      setLocalError(`Для отправки описание должно содержать минимум ${MIN_TASK_LENGTH} символов.`);
      return;
    }
    if (!normalizedText.length) {
      setLocalError('Описание задачи не может быть пустым.');
      return;
    }
    setLocalError(null);
    const normalizedTitle = title.trim() || undefined;
    const fingerprint = JSON.stringify({ title: normalizedTitle ?? null, raw_text: normalizedText, save_as_draft: saveAsDraft });
    let idempotencyRecord = idempotencyRef.current;
    if (!idempotencyRecord || idempotencyRecord.fingerprint !== fingerprint) {
      idempotencyRecord = { key: crypto.randomUUID(), fingerprint };
      idempotencyRef.current = idempotencyRecord;
    }
    setPendingAction(mode);
    mutation.mutate({ title: normalizedTitle, raw_text: normalizedText, save_as_draft: saveAsDraft, idempotency_key: idempotencyRecord.key });
  };

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    submit(false);
  };

  const activeVersionStatus = getApiErrorStatus(activeVersionQuery.error);
  const activeVersionErrorPayload = (activeVersionQuery.error as { payload?: { error_code?: unknown } } | null)?.payload;
  const activeVersionMissing = activeVersionStatus === 404 || activeVersionErrorPayload?.error_code === 'ENTITY_NOT_FOUND';
  const hasSavedKnowledgeSelection = knowledgeSelectionSaved || (basesQuery.data ?? []).some((item: KnowledgeBase) => item.selected_for_generation);
  const shouldShowActiveVersionState = !basesQuery.isLoading && !hasSavedKnowledgeSelection;

  return (
    <div className="stack">
      <PageHeader
        title="Новая задача"
        subtitle="Опишите входные данные. Система проверит полноту и откроет уточнения, если чего-то не хватит."
      />

      <Card title="Версия знаний для генерации" subtitle="Выбор применяется к следующим запускам подготовки решения. Задачу можно сохранить и без активной версии знаний.">
        {activeVersionQuery.data ? (
          <Banner tone="info">
            Сейчас используется {formatKnowledgeVersionLabel(activeVersionQuery.data)}.
          </Banner>
        ) : activeVersionMissing && shouldShowActiveVersionState ? (
          <Banner tone="warning">
            Активная версия знаний не выбрана. Задачу можно сохранить сейчас, но подготовка решения и проверка будут недоступны до выбора версии.
          </Banner>
        ) : activeVersionQuery.isError && shouldShowActiveVersionState ? (
          <ErrorNotice error={activeVersionQuery.error} fallback="Не удалось загрузить активную версию знаний." />
        ) : null}
        <KnowledgeScopeSelector compact onApplied={() => setKnowledgeSelectionSaved(true)} />
      </Card>

      <Card title="Как лучше сформулировать задачу" subtitle="Сначала лучше пройтись по этому чек-листу, а потом уже писать текст задачи. Так система реже будет возвращать уточняющие вопросы.">
        <div className="stack compact">
          <Banner tone="info">
            Лучше писать не длиннее, а конкретнее: короткий, но предметный ответ полезнее длинного абстрактного описания.
          </Banner>
          <ul className="compact-list">
            {qualityHints.map((hint) => <li key={hint}>{hint}</li>)}
          </ul>
          <div className="muted small">
            Нормально писать и коротко, если есть смысл. Например: <strong>Интеграций нет</strong>, <strong>Нужен HLD</strong>, <strong>Срок 3 месяца</strong>.
          </div>
        </div>
      </Card>

      <Card title="Описание задачи" subtitle="Черновик сохраняется без проверки полноты. Отправка на проверку входных данных создаёт уточнения или переводит задачу к подготовке решения.">
        <form className="stack" onSubmit={handleSubmit}>
          <Banner tone="info">
            Сначала укажите цель и контекст, затем ограничения, интеграции и ожидаемый результат. Если каких-то данных нет, лучше указать это явно.
          </Banner>
          <FormRow label="Короткое название">
            <Input value={title} onChange={(event: ChangeEvent<HTMLInputElement>) => setTitle(event.target.value)} placeholder="Например: Архитектура сервиса согласования артефактов" />
          </FormRow>
          <FormRow label="Подробное описание" hint="Опишите цель, контекст, ограничения, интеграции и ожидаемый результат.">
            <Textarea value={taskText} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => setTaskText(event.target.value)} placeholder="Нужно подготовить решение для..." />
          </FormRow>
          <div className="muted small">Сейчас символов: {taskText.trim().length}. Для отправки желательно не меньше {MIN_TASK_LENGTH}.</div>
          {localError ? <Banner tone="danger">{localError}</Banner> : null}
          {mutation.isError ? <ErrorNotice error={mutation.error} fallback="Не удалось сохранить задачу. Проверьте доступность сервера." /> : null}
          <div className="actions">
            <Button type="button" onClick={() => submit(true)} disabled={mutation.isPending}>{pendingAction === 'draft' ? 'Сохраняю черновик…' : 'Сохранить черновик'}</Button>
            <Button type="submit" primary disabled={mutation.isPending}>{pendingAction === 'submit' ? 'Проверяю входные данные…' : 'Отправить на проверку входных данных'}</Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
