import { type ChangeEvent, type FormEvent, useRef, useState } from 'react';

import { Banner, Button, Card, EmptyState, ErrorNotice, FormRow, Textarea } from '../../shared/ui/components';
import { formatDateTime, titleStatus } from '../../shared/lib/format';
import type { ClarificationQuestionItem, ClarificationRequest } from '../../types/api';
import { evaluateClarificationDraft, getClarificationGuidance } from './lib';

interface ClarificationsCardProps {
  clarifications: ClarificationRequest[];
  answerDrafts: Record<string, string>;
  pending: boolean;
  error?: unknown;
  onAnswerChange: (key: string, value: string) => void;
  onSubmitAnswers: (clarificationId: string, answers: Array<{ question_code: string; answer_text: string }>) => void;
}

export function ClarificationsCard({
  clarifications,
  answerDrafts,
  pending,
  error,
  onAnswerChange,
  onSubmitAnswers,
}: ClarificationsCardProps) {
  const [localNotice, setLocalNotice] = useState<{ tone: 'danger' | 'warning'; message: string } | null>(null);
  const noticeRef = useRef<HTMLDivElement | null>(null);
  const questionRefs = useRef<Record<string, HTMLDivElement | null>>({});

  const scrollToProblem = (options?: { questionKey?: string; showNoticeFirst?: boolean }) => {
    requestAnimationFrame(() => {
      if (options?.showNoticeFirst) {
        const questionKey = options.questionKey;
        noticeRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        if (questionKey) {
          window.setTimeout(() => {
            questionRefs.current[questionKey]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }, 180);
        }
        return;
      }
      if (options?.questionKey) {
        questionRefs.current[options.questionKey]?.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
      noticeRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    });
  };

  const submitClarification = (event: FormEvent<HTMLFormElement>, clarification: ClarificationRequest) => {
    event.preventDefault();
    const answers = clarification.question_items
      .map((question: ClarificationQuestionItem) => ({
        question_code: question.question_code,
        answer_text: (answerDrafts[`${clarification.clarification_id}:${question.question_code}`] ?? '').trim(),
      }))
      .filter((item) => item.answer_text.length > 0);

    if (!answers.length) {
      setLocalNotice({ tone: 'danger', message: 'Заполните хотя бы один ответ перед сохранением.' });
      scrollToProblem();
      return;
    }

    const genericAnswers = answers.filter((item) => evaluateClarificationDraft(item.question_code, item.answer_text).status === 'generic');
    if (genericAnswers.length > 0) {
      const firstGenericKey = `${clarification.clarification_id}:${genericAnswers[0].question_code}`;
      setLocalNotice({
        tone: 'warning',
        message: 'Некоторые ответы пока выглядят слишком общими. Их можно сохранить сейчас и дополнить позже, но система, вероятно, запросит дополнительные детали.',
      });
      scrollToProblem({ questionKey: firstGenericKey, showNoticeFirst: true });
    } else {
      setLocalNotice(null);
    }

    onSubmitAnswers(clarification.clarification_id, answers);
  };

  return (
    <Card
      title="Уточняющие вопросы"
      subtitle="Можно сохранить один или несколько ответов. Если данных пока недостаточно, система запросит недостающие детали повторно."
    >
      {clarifications.length === 0 ? (
        <EmptyState title="Сейчас уточнений нет" description="Если данных достаточно, можно переходить к подготовке решения." />
      ) : (
        <div className="stack">
          {localNotice ? (
            <div ref={noticeRef}>
              <Banner tone={localNotice.tone}>{localNotice.message}</Banner>
            </div>
          ) : null}
          {error ? <ErrorNotice error={error} fallback="Не удалось сохранить ответы на уточнения." /> : null}
          {clarifications.map((clarification) => (
            <form
              key={clarification.clarification_id}
              className="section-box stack compact"
              onSubmit={(event: FormEvent<HTMLFormElement>) => submitClarification(event, clarification)}
            >
              <div className="actions between">
                <strong>Уточнение</strong>
                <span className="muted small">{titleStatus(clarification.state)} · создано {formatDateTime(clarification.created_at)}</span>
              </div>
              {clarification.question_items.map((question: ClarificationQuestionItem) => {
                const key = `${clarification.clarification_id}:${question.question_code}`;
                const draft = answerDrafts[key] ?? '';
                const evaluation = evaluateClarificationDraft(question.question_code, draft);

                return (
                  <div
                    key={key}
                    ref={(node) => {
                      questionRefs.current[key] = node;
                    }}
                  >
                    <FormRow label={question.question_text} hint={getClarificationGuidance(question.question_code)}>
                      <Textarea
                        value={draft}
                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) => {
                          setLocalNotice(null);
                          onAnswerChange(key, event.target.value);
                        }}
                        placeholder="Введите ответ"
                      />
                      {evaluation.status !== 'empty' ? (
                        <div className={`small ${evaluation.status === 'ready' ? '' : 'muted'}`}>{evaluation.message}</div>
                      ) : null}
                    </FormRow>
                  </div>
                );
              })}
              <div className="actions">
                <Button type="submit" primary disabled={pending}>
                  {pending ? 'Сохраняю…' : 'Сохранить ответы'}
                </Button>
              </div>
            </form>
          ))}
        </div>
      )}
    </Card>
  );
}
