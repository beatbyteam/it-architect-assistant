import { type ChangeEvent, type FormEvent } from 'react';

import { Button, Card, ErrorNotice, FormRow, Input, Textarea } from '../../shared/ui/components';

interface DraftEditorCardProps {
  draftTitle: string;
  draftText: string;
  pending: boolean;
  pendingMode?: 'draft' | 'submit' | null;
  error?: unknown;
  inputValidationPassed?: boolean;
  onDraftTitleChange: (value: string) => void;
  onDraftTextChange: (value: string) => void;
  onSave: (mode: 'draft' | 'submit') => void;
}

export function DraftEditorCard({
  draftTitle,
  draftText,
  pending,
  pendingMode,
  error,
  inputValidationPassed,
  onDraftTitleChange,
  onDraftTextChange,
  onSave,
}: DraftEditorCardProps) {
  return (
    <Card title="Редактирование черновика">
      <form className="stack" onSubmit={(event: FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        if (inputValidationPassed) return;
        onSave('submit');
      }}>
        <FormRow label="Короткое название">
          <Input value={draftTitle} onChange={(event: ChangeEvent<HTMLInputElement>) => onDraftTitleChange(event.target.value)} />
        </FormRow>
        <FormRow label="Подробное описание">
          <Textarea value={draftText} onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onDraftTextChange(event.target.value)} />
        </FormRow>
        {error ? <ErrorNotice error={error} fallback="Не удалось сохранить черновик." /> : null}
        <div className="actions">
          <Button type="button" onClick={() => onSave('draft')} disabled={pending}>{pendingMode === 'draft' ? 'Сохраняю черновик…' : 'Сохранить черновик'}</Button>
          <Button type="submit" primary={!inputValidationPassed} disabled={pending || inputValidationPassed}>
            {inputValidationPassed ? 'Входные данные проверены' : pendingMode === 'submit' ? 'Проверяю входные данные…' : 'Отправить на проверку входных данных'}
          </Button>
        </div>
      </form>
    </Card>
  );
}
