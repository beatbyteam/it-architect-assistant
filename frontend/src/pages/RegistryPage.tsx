import { type ChangeEvent, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';

import { getTasks, getSolutionsRegistry } from '../shared/api/tasks';
import { getVerificationProtocolsRegistry } from '../shared/api/verification';
import { Badge, Banner, Button, Card, EmptyState, ErrorNotice, Input, LoadingState, PageHeader, Select, StatCard, TabStrip } from '../shared/ui/components';
import { formatDateTime, titleStatus, truncate } from '../shared/lib/format';
import { matchesSearch } from '../shared/lib/search';
import type { SolutionRegistryItem, TaskListItem, VerificationProtocolRegistryItem } from '../types/api';

type RegistryTab = 'tasks' | 'solutions' | 'protocols';
type RegistryTask = TaskListItem & {
  latest_generation_state?: string | null;
};

type StatusOption = {
  value: string;
  label: string;
};

const REGISTRY_LIMIT_STEP = 100;
const REGISTRY_LIMIT_MAX = 200;

const STATUS_OPTIONS: Record<RegistryTab, StatusOption[]> = {
  tasks: [
    { value: 'draft', label: 'Черновик' },
    { value: 'submitted', label: 'Принято в работу' },
    { value: 'running', label: 'В работе' },
    { value: 'needs_clarification', label: 'Нужны уточнения' },
    { value: 'ready_for_generation', label: 'Можно готовить решение' },
    { value: 'completed', label: 'Завершено' },
    { value: 'clarified', label: 'Данные уточнены' },
  ],
  solutions: [
    { value: 'published', label: 'Опубликовано' },
    { value: 'superseded', label: 'Есть новая версия' },
    { value: 'failed', label: 'Ошибка' },
  ],
  protocols: [
    { value: 'passed', label: 'Без замечаний' },
    { value: 'passed_with_comments', label: 'Есть комментарии' },
    { value: 'incomplete', label: 'Неполный результат' },
    { value: 'failed', label: 'Ошибка' },
  ],
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

function matchesDate(value: string | null | undefined, from?: string, to?: string) {
  if (!from && !to) return true;
  if (!value) return false;

  const current = new Date(value).getTime();
  if (Number.isNaN(current)) return true;
  if (from && current < new Date(from).getTime()) return false;
  if (to) {
    const end = new Date(to);
    end.setHours(23, 59, 59, 999);
    if (current > end.getTime()) return false;
  }
  return true;
}

function taskActionLabel(item: TaskListItem) {
  if (item.state === 'needs_clarification') return 'Ответить на уточнения';
  if (item.state === 'ready_for_generation') return 'Подготовить решение';
  if (item.state === 'failed') return 'Повторить подготовку';
  if (item.state === 'draft') return 'Продолжить черновик';
  return 'Открыть задачу';
}

function taskBadgeValue(item: RegistryTask) {
  return item.latest_generation_state && ACTIVE_GENERATION_STATES.has(item.latest_generation_state)
    ? 'running'
    : item.state;
}

function activeDateRangeLabel(dateFrom: string, dateTo: string) {
  if (dateFrom && dateTo) return `Период: ${dateFrom} - ${dateTo}`;
  if (dateFrom) return `С ${dateFrom}`;
  if (dateTo) return `До ${dateTo}`;
  return 'Без ограничения по дате';
}

function hasStatusOption(tab: RegistryTab, value: string) {
  return !value || STATUS_OPTIONS[tab].some((option) => option.value === value);
}

export function RegistryPage() {
  const [tab, setTab] = useState<RegistryTab>('tasks');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [tasksLimit, setTasksLimit] = useState(REGISTRY_LIMIT_STEP);
  const [solutionsLimit, setSolutionsLimit] = useState(REGISTRY_LIMIT_STEP);
  const [protocolsLimit, setProtocolsLimit] = useState(REGISTRY_LIMIT_STEP);

  const tasksQuery = useQuery({
    queryKey: ['registry-tasks', tasksLimit],
    queryFn: ({ signal }) => getTasks({ limit: tasksLimit }, { signal }),
    staleTime: 10_000,
  });
  const solutionsQuery = useQuery({
    queryKey: ['registry-solutions', solutionsLimit],
    queryFn: ({ signal }) => getSolutionsRegistry({ limit: solutionsLimit }, { signal }),
    staleTime: 10_000,
  });
  const protocolsQuery = useQuery({
    queryKey: ['registry-protocols', protocolsLimit],
    queryFn: ({ signal }) => getVerificationProtocolsRegistry({ limit: protocolsLimit }, { signal }),
    staleTime: 10_000,
  });

  useEffect(() => {
    if (!hasStatusOption(tab, statusFilter)) {
      setStatusFilter('');
    }
  }, [statusFilter, tab]);

  const searchValue = search.trim().toLowerCase();
  const filtersAreActive = Boolean(search || statusFilter || dateFrom || dateTo);
  const resetFilters = () => {
    setSearch('');
    setStatusFilter('');
    setDateFrom('');
    setDateTo('');
  };

  const filteredTasks = useMemo(() => {
    const rows = tasksQuery.data ?? [];
    return rows.filter((item: RegistryTask) => {
      const badgeStatus = taskBadgeValue(item);
      const searchParts = [
        item.task_id,
        item.title ?? 'Задача без названия',
        item.state,
        titleStatus(item.state),
        badgeStatus,
        titleStatus(badgeStatus),
        item.open_clarification_count,
        item.overdue_clarification_flag ? 'Есть просрочка' : null,
        taskActionLabel(item),
      ];
      return matchesSearch(searchParts, searchValue)
        && (!statusFilter || item.state === statusFilter || badgeStatus === statusFilter)
        && matchesDate(item.updated_at, dateFrom, dateTo);
    });
  }, [dateFrom, dateTo, searchValue, statusFilter, tasksQuery.data]);

  const filteredSolutions = useMemo(() => {
    const rows = solutionsQuery.data ?? [];
    return rows.filter((item: SolutionRegistryItem) => {
      const searchParts = [
        item.solution_version_id,
        item.solution_title,
        'Задача',
        item.task_id,
        item.state,
        titleStatus(item.state),
        item.generation_run_id,
        item.latest_verification_state,
        titleStatus(item.latest_verification_state),
        item.latest_protocol_id,
        item.verification_run_count,
      ];
      return matchesSearch(searchParts, searchValue)
        && (!statusFilter || item.state === statusFilter)
        && matchesDate(item.published_at ?? item.created_at, dateFrom, dateTo);
    });
  }, [dateFrom, dateTo, searchValue, solutionsQuery.data, statusFilter]);

  const filteredProtocols = useMemo(() => {
    const rows = protocolsQuery.data ?? [];
    return rows.filter((item: VerificationProtocolRegistryItem) => {
      const searchParts = [
        item.protocol_id,
        item.verification_run_id,
        item.solution_version_id,
        item.knowledge_version_id,
        item.summary_text,
        item.state,
        titleStatus(item.state),
        item.summary_status,
        titleStatus(item.summary_status),
        item.basis_document_count,
        item.finding_count,
        item.has_blockers ? 'Есть блокеры' : null,
      ];
      return matchesSearch(searchParts, searchValue)
        && (!statusFilter || item.summary_status === statusFilter || item.state === statusFilter)
        && matchesDate(item.created_at, dateFrom, dateTo);
    });
  }, [dateFrom, dateTo, protocolsQuery.data, searchValue, statusFilter]);

  const overdueCount = (tasksQuery.data ?? []).filter((item: TaskListItem) => item.overdue_clarification_flag).length;
  const readyTaskCount = (tasksQuery.data ?? []).filter((item: TaskListItem) => item.state === 'ready_for_generation').length;
  const needsClarificationCount = (tasksQuery.data ?? []).filter((item: TaskListItem) => item.state === 'needs_clarification').length;
  const failedProtocolCount = (protocolsQuery.data ?? []).filter((item: VerificationProtocolRegistryItem) => item.summary_status === 'failed' || item.state === 'failed').length;

  const canLoadMoreTasks = tasksLimit < REGISTRY_LIMIT_MAX && (tasksQuery.data?.length ?? 0) >= tasksLimit;
  const canLoadMoreSolutions = solutionsLimit < REGISTRY_LIMIT_MAX && (solutionsQuery.data?.length ?? 0) >= solutionsLimit;
  const canLoadMoreProtocols = protocolsLimit < REGISTRY_LIMIT_MAX && (protocolsQuery.data?.length ?? 0) >= protocolsLimit;

  const currentStatusOptions = STATUS_OPTIONS[tab];
  const isCurrentTabLoading = tab === 'tasks'
    ? tasksQuery.isLoading
    : tab === 'solutions'
      ? solutionsQuery.isLoading
      : protocolsQuery.isLoading;

  return (
    <div className="stack">
      <PageHeader
        title="Задачи и результаты"
        subtitle="Единый реестр задач, подготовленных решений и протоколов проверки."
        actions={<Link to="/tasks/new" className="button button-primary">Создать задачу</Link>}
      />

      {overdueCount > 0 ? (
        <Banner tone="warning">
          Есть задачи с просроченными уточнениями: {overdueCount}. Открой вкладку «Задачи» и ответь на вопросы.
        </Banner>
      ) : null}

      <div className="grid grid-4">
        <StatCard label="Нужны уточнения" value={tasksQuery.isError ? '—' : String(needsClarificationCount)} hint="Среди загруженных задач" />
        <StatCard label="Можно готовить решение" value={tasksQuery.isError ? '—' : String(readyTaskCount)} hint="Среди загруженных задач" />
        <StatCard label="Загружено решений" value={solutionsQuery.isError ? '—' : String(solutionsQuery.data?.length ?? 0)} hint="Фильтры ниже применяются к этой выборке" />
        <StatCard label="Проверки с ошибкой" value={protocolsQuery.isError ? '—' : String(failedProtocolCount)} hint="Среди загруженных протоколов" />
      </div>

      <Card
        title="Фильтры"
        subtitle="Поиск, статус и даты применяются к загруженной выборке текущей вкладки."
        actions={filtersAreActive ? <Button onClick={resetFilters}>Сбросить фильтры</Button> : null}
      >
        <div className="toolbar-grid toolbar-grid-4">
          <TabStrip>
            <button type="button" className={`button ${tab === 'tasks' ? 'button-primary' : ''}`} onClick={() => setTab('tasks')}>Задачи</button>
            <button type="button" className={`button ${tab === 'solutions' ? 'button-primary' : ''}`} onClick={() => setTab('solutions')}>Решения</button>
            <button type="button" className={`button ${tab === 'protocols' ? 'button-primary' : ''}`} onClick={() => setTab('protocols')}>Проверки</button>
          </TabStrip>
          <Input value={search} onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)} placeholder="Название, id или статус" />
          <Select value={statusFilter} onChange={(event: ChangeEvent<HTMLSelectElement>) => setStatusFilter(event.target.value)}>
            <option value="">Все статусы</option>
            {currentStatusOptions.map((option) => (
              <option value={option.value} key={option.value}>{option.label}</option>
            ))}
          </Select>
          <div className="toolbar-grid">
            <Input type="date" aria-label="Дата с" value={dateFrom} onChange={(event: ChangeEvent<HTMLInputElement>) => setDateFrom(event.target.value)} />
            <Input type="date" aria-label="Дата до" value={dateTo} onChange={(event: ChangeEvent<HTMLInputElement>) => setDateTo(event.target.value)} />
          </div>
        </div>
        <div className="filter-summary muted small">{activeDateRangeLabel(dateFrom, dateTo)}</div>
      </Card>

      {isCurrentTabLoading ? <LoadingState message="Загружаю данные текущей вкладки…" /> : null}

      {tab === 'tasks' && !isCurrentTabLoading ? (
        <Card
          title="Задачи"
          subtitle="Рабочие входные данные: черновики, уточнения и задачи, готовые к подготовке решения."
          actions={<div className="actions"><span className="muted small">Загружено: {tasksQuery.data?.length ?? 0}</span>{canLoadMoreTasks ? <Button onClick={() => setTasksLimit((current) => Math.min(REGISTRY_LIMIT_MAX, current + REGISTRY_LIMIT_STEP))}>Показать ещё</Button> : null}</div>}
        >
          {tasksQuery.isError ? (
            <ErrorNotice error={tasksQuery.error} fallback="Не удалось загрузить задачи." />
          ) : filteredTasks.length === 0 ? (
            <EmptyState title="Подходящих задач не найдено" description="Проверьте фильтры или создайте новую задачу." action={<Link className="button" to="/tasks/new">Создать задачу</Link>} />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Задача</th><th>Статус</th><th>Уточнения</th><th>Обновлена</th><th /></tr>
                </thead>
                <tbody>
                  {filteredTasks.map((item: RegistryTask) => (
                    <tr key={item.task_id}>
                      <td>
                        <strong>{item.title ?? 'Задача без названия'}</strong>
                        <div className="muted small mono">{truncate(item.task_id, 18)}</div>
                      </td>
                      <td><Badge value={taskBadgeValue(item)} /></td>
                      <td>
                        {item.open_clarification_count ?? 0}
                        {item.overdue_clarification_flag ? <div className="muted small">Есть просрочка</div> : null}
                      </td>
                      <td>{formatDateTime(item.updated_at)}</td>
                      <td><Link className="button" to={`/tasks/${item.task_id}`}>{taskActionLabel(item)}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : null}

      {tab === 'solutions' && !isCurrentTabLoading ? (
        <Card
          title="Решения"
          subtitle="Опубликованные версии решений и их связь с задачами и последними проверками."
          actions={<div className="actions"><span className="muted small">Загружено: {solutionsQuery.data?.length ?? 0}</span>{canLoadMoreSolutions ? <Button onClick={() => setSolutionsLimit((current) => Math.min(REGISTRY_LIMIT_MAX, current + REGISTRY_LIMIT_STEP))}>Показать ещё</Button> : null}</div>}
        >
          {solutionsQuery.isError ? (
            <ErrorNotice error={solutionsQuery.error} fallback="Не удалось загрузить решения." />
          ) : filteredSolutions.length === 0 ? (
            <EmptyState title="Подходящих решений не найдено" description="Проверьте фильтры или сначала подготовьте решение из задачи." />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Решение</th><th>Статус</th><th>Проверки</th><th>Дата публикации</th><th /></tr>
                </thead>
                <tbody>
                  {filteredSolutions.map((item: SolutionRegistryItem) => (
                    <tr key={item.solution_version_id}>
                      <td>
                        <strong>{item.solution_title}</strong>
                        <div className="muted small">Задача: {truncate(item.task_id, 18)}</div>
                      </td>
                      <td><Badge value={item.state} /></td>
                      <td>
                        {item.verification_run_count ?? 0}
                        {item.latest_verification_state ? <div className="muted small">Последняя: <Badge value={item.latest_verification_state} /></div> : null}
                      </td>
                      <td>{formatDateTime(item.published_at ?? item.created_at)}</td>
                      <td>
                        <div className="actions">
                          <Link className="button" to={`/solutions/${item.solution_version_id}`}>Открыть решение</Link>
                          <Link className="button" to={`/tasks/${item.task_id}`}>Открыть задачу</Link>
                          {item.latest_protocol_id ? <Link className="button" to={`/protocols/${item.latest_protocol_id}`}>Открыть последнюю проверку</Link> : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : null}

      {tab === 'protocols' && !isCurrentTabLoading ? (
        <Card
          title="Проверки"
          subtitle="Протоколы проверки решений: итог, состояние процесса и количество замечаний."
          actions={<div className="actions"><span className="muted small">Загружено: {protocolsQuery.data?.length ?? 0}</span>{canLoadMoreProtocols ? <Button onClick={() => setProtocolsLimit((current) => Math.min(REGISTRY_LIMIT_MAX, current + REGISTRY_LIMIT_STEP))}>Показать ещё</Button> : null}</div>}
        >
          {protocolsQuery.isError ? (
            <ErrorNotice error={protocolsQuery.error} fallback="Не удалось загрузить проверки." />
          ) : filteredProtocols.length === 0 ? (
            <EmptyState title="Подходящих проверок не найдено" description="Проверьте фильтры или запустите проверку из готового решения." />
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr><th>Проверка</th><th>Итог</th><th>Статус</th><th>Замечания</th><th>Создана</th><th /></tr>
                </thead>
                <tbody>
                  {filteredProtocols.map((item: VerificationProtocolRegistryItem) => (
                    <tr key={item.protocol_id}>
                      <td>
                        <strong>{truncate(item.summary_text || 'Проверка решения', 40)}</strong>
                        <div className="muted small">Решение: {truncate(item.solution_version_id, 18)}</div>
                      </td>
                      <td><Badge value={item.summary_status} /></td>
                      <td><Badge value={item.state} /></td>
                      <td>
                        {item.finding_count ?? 0}
                        {item.has_blockers ? <div className="muted small">Есть блокеры</div> : null}
                      </td>
                      <td>{formatDateTime(item.created_at)}</td>
                      <td>
                        <div className="actions">
                          <Link className="button" to={`/protocols/${item.protocol_id}`}>Открыть протокол</Link>
                          <Link className="button" to={`/solutions/${item.solution_version_id}`}>Открыть решение</Link>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      ) : null}
    </div>
  );
}
