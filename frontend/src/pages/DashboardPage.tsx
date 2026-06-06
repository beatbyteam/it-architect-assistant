import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { getActiveKnowledgeVersion, getKnowledgeBases, getKnowledgeNotifications } from '../shared/api/knowledge';
import { getTasks, getSolutionsRegistry } from '../shared/api/tasks';
import { getVerificationProtocolsRegistry } from '../shared/api/verification';
import { getApiErrorStatus } from '../shared/api/client';
import { Badge, Banner, Card, EmptyState, ErrorNotice, LoadingState, PageHeader, StatCard } from '../shared/ui/components';
import { formatDateTime, formatKnowledgeVersionLabel, knowledgeBaseKindLabel } from '../shared/lib/format';
import type { KnowledgeBase, KnowledgeNotification, SolutionRegistryItem, TaskListItem, VerificationProtocolRegistryItem } from '../types/api';

type DashboardTask = TaskListItem & {
  latest_generation_state?: string | null;
  latest_verification_state?: string | null;
  metadata?: Record<string, unknown> | null;
};

const ACTIVE_GENERATION_STATES = new Set([
  'queued',
  'pending',
  'running',
  'preparing',
  'retrieving',
  'prompting',
  'model_generation',
  'persisting',
  'validating',
  'finalizing',
  'publishing',
]);
const ACTIVE_VERIFICATION_STATES = new Set(['queued', 'running']);

function dashboardTaskBadgeValue(task: DashboardTask) {
  if (task.latest_verification_state && ACTIVE_VERIFICATION_STATES.has(task.latest_verification_state)) {
    return 'running';
  }
  return task.latest_generation_state && ACTIVE_GENERATION_STATES.has(task.latest_generation_state)
    ? 'running'
    : task.state;
}

function isExternalArchitectureTask(task: DashboardTask) {
  return task.metadata?.source === 'external_architecture' && task.metadata?.verification_only === true;
}

function dashboardTaskLink(task: DashboardTask) {
  return isExternalArchitectureTask(task) && task.state === 'draft'
    ? `/external-check?draft_task_id=${encodeURIComponent(task.task_id)}`
    : `/tasks/${task.task_id}`;
}

export function DashboardPage() {
  const tasksQuery = useQuery({ queryKey: ['dashboard-tasks'], queryFn: ({ signal }) => getTasks({ limit: 12 }, { signal }), staleTime: 15_000 });
  const activeVersionQuery = useQuery({ queryKey: ['dashboard-active-version'], queryFn: ({ signal }) => getActiveKnowledgeVersion({ signal }), staleTime: 30_000, retry: false });
  const basesQuery = useQuery({ queryKey: ['dashboard-knowledge-bases'], queryFn: ({ signal }) => getKnowledgeBases({ signal }), staleTime: 15_000 });
  const notificationsQuery = useQuery({ queryKey: ['dashboard-knowledge-notifications'], queryFn: ({ signal }) => getKnowledgeNotifications(6, undefined, { signal }), staleTime: 10_000 });
  const solutionsQuery = useQuery({ queryKey: ['dashboard-solutions'], queryFn: ({ signal }) => getSolutionsRegistry({ limit: 5 }, { signal }), staleTime: 10_000 });
  const protocolsQuery = useQuery({ queryKey: ['dashboard-protocols'], queryFn: ({ signal }) => getVerificationProtocolsRegistry({ limit: 5 }, { signal }), staleTime: 10_000 });

  if ([tasksQuery, activeVersionQuery, basesQuery, notificationsQuery, solutionsQuery, protocolsQuery].some((item) => item.isLoading)) {
    return <LoadingState message="Собираю главную страницу…" />;
  }

  const tasks = (tasksQuery.data ?? []) as DashboardTask[];
  const recentTasks = [...tasks].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5);
  const needsClarification = tasks.filter((task: TaskListItem) => task.state === 'needs_clarification');
  const readyTasks = tasks.filter((task: TaskListItem) => task.state === 'ready_for_generation');
  const recentSolutions = solutionsQuery.data ?? [];
  const recentProtocols = protocolsQuery.data ?? [];
  const activeVersion = activeVersionQuery.data;
  const bases = basesQuery.data ?? [];
  const notifications = notificationsQuery.data ?? [];
  const selectedBase = bases.find((item: KnowledgeBase) => item.selected_for_generation) ?? null;
  const activeVersionStatus = getApiErrorStatus(activeVersionQuery.error);

  const taskActionLabel = (task: DashboardTask) => {
    if (isExternalArchitectureTask(task) && task.latest_verification_state && ACTIVE_VERIFICATION_STATES.has(task.latest_verification_state)) return 'Открыть проверку в работе';
    if (isExternalArchitectureTask(task) && task.state === 'draft') return 'Продолжить черновик проверки';
    if (task.state === 'needs_clarification') return 'Ответить на уточнения';
    if (task.state === 'ready_for_generation') return 'Подготовить решение';
    if (task.state === 'failed') return 'Повторить подготовку';
    if (task.state === 'draft') return 'Продолжить черновик';
    return 'Открыть задачу';
  };

  return (
    <div className="stack">
      <PageHeader
        title="Главная"
        subtitle="Рабочая панель задач, решений, проверок и активной версии знаний."
        actions={<Link to="/tasks/new" className="button button-primary">Создать задачу</Link>}
      />

      <Card title="Активная версия знаний">
        <div className="stack compact">
          {activeVersion ? (
            <>
              <div><strong>Сейчас используется:</strong> {formatKnowledgeVersionLabel(activeVersion)}</div>
              {activeVersion.activated_at ? <div className="muted small">Активирована: {formatDateTime(activeVersion.activated_at)}</div> : null}
              {selectedBase ? (
                <div className="muted small">Выбранная база: {selectedBase.name} · {knowledgeBaseKindLabel(selectedBase.kind)}</div>
              ) : (
                <div className="muted small">База знаний не выбрана.</div>
              )}
            </>
          ) : selectedBase ? (
            <div className="muted small">Выбранная база: {selectedBase.name} · {knowledgeBaseKindLabel(selectedBase.kind)}</div>
          ) : activeVersionStatus === 404 ? (
            <Banner tone="warning">
              Активная версия знаний не выбрана. Задачу можно создать сейчас, но подготовка решения и проверка станут доступны после выбора версии.
            </Banner>
          ) : activeVersionQuery.isError ? (
            <ErrorNotice error={activeVersionQuery.error} fallback="Не удалось загрузить активную версию знаний." />
          ) : (
            <div className="muted">Версия знаний не выбрана.</div>
          )}
          {basesQuery.isError ? <ErrorNotice error={basesQuery.error} fallback="Не удалось загрузить список баз знаний." /> : null}
          <div className="actions">
            <Link to="/knowledge" className="button">Открыть базы знаний</Link>
            {selectedBase ? <Link to={`/knowledge/bases/${selectedBase.knowledge_base_id}`} className="button">Открыть выбранную базу</Link> : null}
          </div>
        </div>
      </Card>

      <div className="grid grid-4">
        <StatCard label="Нужны уточнения" value={String(needsClarification.length)} hint="Среди загруженных задач" />
        <StatCard label="Готовы к решению" value={String(readyTasks.length)} hint="Среди загруженных задач" />
        <StatCard label="Последние решения" value={String(recentSolutions.length)} hint="Загруженная выборка" />
        <StatCard label="Последние проверки" value={String(recentProtocols.length)} hint="Загруженная выборка" />
      </div>

      <div className="grid grid-2">
        <Card title="Последние задачи">
          {tasksQuery.isError ? (
            <ErrorNotice error={tasksQuery.error} fallback="Не удалось загрузить задачи." />
          ) : recentTasks.length === 0 ? (
            <EmptyState title="Пока нет ни одной задачи" description="Создайте первую задачу, чтобы подготовить проект решения." />
          ) : (
            <div className="timeline">
              {recentTasks.map((task: TaskListItem) => (
                <div className="timeline-item" key={task.task_id}>
                  <div className="actions between">
                    <strong>{task.title ?? 'Задача без названия'}</strong>
                    <Badge value={dashboardTaskBadgeValue(task)} />
                  </div>
                  <div className="muted small">Обновлена: {formatDateTime(task.updated_at)}</div>
                  {task.latest_verification_state ? <div className="muted small">Проверка: <Badge value={task.latest_verification_state} /></div> : null}
                  <div className="actions">
                    <Link className="button" to={dashboardTaskLink(task)}>{taskActionLabel(task)}</Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Готовые решения">
          {solutionsQuery.isError ? <ErrorNotice error={solutionsQuery.error} fallback="Не удалось загрузить решения." /> : recentSolutions.length === 0 ? <EmptyState title="Решений пока нет" /> : (
            <div className="timeline">
              {recentSolutions.map((item: SolutionRegistryItem) => (
                <div className="timeline-item" key={item.solution_version_id}>
                  <div className="actions between">
                    <strong>{item.solution_title}</strong>
                    <Badge value={item.latest_verification_state && ACTIVE_VERIFICATION_STATES.has(item.latest_verification_state) ? 'running' : item.state} />
                  </div>
                  <div className="muted small">Опубликовано: {formatDateTime(item.published_at ?? item.created_at)}</div>
                  {item.latest_verification_state ? <div className="muted small">Проверка: <Badge value={item.latest_verification_state} /></div> : null}
                  <div className="actions">
                    <Link className="button" to={`/solutions/${item.solution_version_id}`}>Открыть решение</Link>
                    {item.latest_protocol_id ? <Link className="button" to={`/protocols/${item.latest_protocol_id}`}>Открыть последнюю проверку</Link> : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      <Card title="Последние проверки">
        {protocolsQuery.isError ? <ErrorNotice error={protocolsQuery.error} fallback="Не удалось загрузить проверки." /> : recentProtocols.length === 0 ? <EmptyState title="Проверок пока нет" /> : (
          <div className="timeline">
            {recentProtocols.map((item: VerificationProtocolRegistryItem) => (
              <div className="timeline-item" key={item.protocol_id}>
                <div className="actions between">
                  <strong>{item.summary_text || 'Проверка решения'}</strong>
                  <Badge value={item.summary_status} />
                </div>
                <div className="muted small">Создано: {formatDateTime(item.created_at)}</div>
                <div className="muted small">Замечаний: {item.finding_count}</div>
                <div className="actions">
                  <Link className="button" to={`/protocols/${item.protocol_id}`}>Открыть протокол</Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title="Уведомления по базам знаний">
        {notificationsQuery.isError ? <ErrorNotice error={notificationsQuery.error} fallback="Не удалось загрузить уведомления по базам знаний." /> : notifications.length === 0 ? <EmptyState title="Уведомлений пока нет" /> : (
          <div className="timeline">
            {notifications.map((item: KnowledgeNotification) => (
              <div className="timeline-item" key={item.notification_id}>
                <div className="actions between">
                  <strong>{item.title}</strong>
                  <Badge value={item.status} />
                </div>
                <div>{item.message}</div>
                <div className="muted small">{item.knowledge_base_name} · {formatDateTime(item.created_at)}</div>
                <div className="actions">
                  <Link className="button" to={`/knowledge/bases/${item.knowledge_base_id}`}>Открыть базу</Link>
                  <Link className="button" to={`/operations/${item.update_run_id}`}>Ход обновления</Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
