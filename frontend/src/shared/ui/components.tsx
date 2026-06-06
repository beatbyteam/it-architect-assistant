import type {
  ButtonHTMLAttributes,
  CSSProperties,
  HTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';
import { useState } from 'react';

import type { ApiError } from '../api/client';
import { getApiErrorMessage } from '../api/client';
import { tone, titleStatus } from '../lib/format';

function cn(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ');
}

export function PageHeader(props: { title: string; subtitle?: string; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn('page-header', props.className)}>
      <div>
        <h1>{props.title}</h1>
        {props.subtitle ? <p className="muted page-header-description">{props.subtitle}</p> : null}
      </div>
      {props.actions ? <div className="actions">{props.actions}</div> : null}
    </div>
  );
}

export function Card(props: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <section className={cn('card', props.compact && 'card-compact', props.className)}>
      {(props.title || props.subtitle || props.actions) ? (
        <div className="card-header">
          <div>
            {props.title ? <h2 className="card-title">{props.title}</h2> : null}
            {props.subtitle ? <p className="muted card-description">{props.subtitle}</p> : null}
          </div>
          {props.actions ? <div className="actions">{props.actions}</div> : null}
        </div>
      ) : null}
      <div className="card-content">{props.children}</div>
      {props.footer ? <div className="card-footer">{props.footer}</div> : null}
    </section>
  );
}

export function Badge(props: { value?: string | null; className?: string }) {
  return <span className={cn(`badge badge-${tone(props.value)}`, props.className)}>{titleStatus(props.value)}</span>;
}

export function Button({
  primary,
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { primary?: boolean }) {
  return <button {...props} className={cn('button', primary ? 'button-primary' : 'button-outline', className)} />;
}

export function CollapsibleCodeBlock(props: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  defaultCollapsed?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(Boolean(props.defaultCollapsed));
  const label = collapsed ? 'Развернуть блок с кодом' : 'Свернуть блок с кодом';

  return (
    <div className={cn('collapsible-code-block', collapsed && 'collapsible-code-block-collapsed')} style={props.style}>
      <button
        type="button"
        className="collapsible-code-toggle"
        onClick={() => setCollapsed((value) => !value)}
        aria-expanded={!collapsed}
        aria-label={label}
        title={label}
      >
        <span className="collapsible-code-chevron" aria-hidden="true" />
      </button>
      {collapsed ? (
        <div className={cn('diagnostic-box collapsible-code-placeholder', props.className)}>Блок свернут</div>
      ) : (
        <pre className={cn('pre-wrap diagnostic-box collapsible-code-content', props.className)}>{props.children}</pre>
      )}
    </div>
  );
}

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn('input', props.className)} />;
}

export function Textarea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn('textarea', props.className)} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn('input select', props.className)} />;
}

export function FormRow(props: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="form-row">
      <span className="form-label">{props.label}</span>
      {props.children}
      {props.hint ? <span className="muted small">{props.hint}</span> : null}
    </label>
  );
}

export function LoadingState(props: { message?: string }) {
  return <StateBox>{props.message ?? 'Загрузка…'}</StateBox>;
}

export function ErrorState(props: { message: string }) {
  return (
    <StateBox tone="danger">
      <strong>Ошибка</strong>
      <p>{props.message}</p>
    </StateBox>
  );
}

export function ErrorNotice(props: { error: unknown; fallback?: string }) {
  const message = getApiErrorMessage(props.error, props.fallback ?? 'Не удалось выполнить операцию.');
  const payload = (props.error as Partial<ApiError> | null | undefined)?.payload;
  return (
    <StateBox tone="danger">
      <strong>Ошибка</strong>
      <p>{message}</p>
      {payload?.error_code && typeof payload.error_code === 'string' ? <div className="muted small">Код: {payload.error_code}</div> : null}
      {payload?.request_id && typeof payload.request_id === 'string' ? <div className="muted small">Идентификатор запроса: {payload.request_id}</div> : null}
      {payload?.operation_id && typeof payload.operation_id === 'string' ? <div className="muted small">Идентификатор процесса: {payload.operation_id}</div> : null}
    </StateBox>
  );
}

export function EmptyState(props: { title: string; description?: string; action?: ReactNode }) {
  return (
    <StateBox className="empty-state">
      <strong className="empty-title">{props.title}</strong>
      {props.description ? <p className="muted">{props.description}</p> : null}
      {props.action ? <div className="empty-action">{props.action}</div> : null}
    </StateBox>
  );
}

export function Banner(props: { tone?: 'info' | 'warning' | 'danger' | 'success'; children: ReactNode }) {
  return <div className={`banner banner-${props.tone ?? 'info'}`}>{props.children}</div>;
}

export function StatCard(props: { label: string; value: string; hint?: string }) {
  return <MetricCard {...props} />;
}

export function MetricCard(props: { label: string; value: string; hint?: string; className?: string }) {
  return (
    <div className={cn('card compact-card metric-card', props.className)}>
      <div className="muted small">{props.label}</div>
      <strong>{props.value}</strong>
      {props.hint ? <div className="muted small">{props.hint}</div> : null}
    </div>
  );
}

export function KeyValueTable(props: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className="dl-grid">
      {props.rows.map(([key, value]) => (
        <div className="dl-row" key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function StateBox(props: {
  tone?: 'default' | 'info' | 'warning' | 'danger';
  children: ReactNode;
  className?: string;
}) {
  return <div className={cn('state-box', props.tone && props.tone !== 'default' && `state-${props.tone}`, props.className)}>{props.children}</div>;
}

export function Panel(props: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cn('section-box panel', props.className)} />;
}

export function Timeline(props: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cn('timeline', props.className)} />;
}

export function TimelineItem(props: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cn('timeline-item', props.className)} />;
}

export function TabStrip(props: HTMLAttributes<HTMLDivElement>) {
  return <div {...props} className={cn('tab-strip', props.className)} />;
}
