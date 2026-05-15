export function formatDateTime(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'short' }).format(date);
}

const TOGAF_SECTION_TITLES: Record<string, string> = {
  general_information: '1. Общие сведения',
  business_tasks_description: '2. Описание бизнес-задач',
  it_architecture_content: '3. Содержание ИТ-архитектуры',
  business_architecture: '3.1 Бизнес-архитектура',
  data_architecture: '3.2 Архитектура данных',
  application_architecture: '3.3 Архитектура приложений',
  technology_architecture: '3.4 Технологическая архитектура',
  additional_information: '4. Дополнительные сведения',
};

const ARCHITECTURE_BOUNDARY_TITLES: Record<string, string> = {
  business_architecture: 'Бизнес-архитектура',
  data_architecture: 'Архитектура данных',
  application_architecture: 'Архитектура приложений',
  technology_architecture: 'Технологическая архитектура',
};

const STATUS_TITLES: Record<string, string> = {
  created: 'Создано',
  draft: 'Черновик',
  submitted: 'Принято в работу',
  needs_clarification: 'Нужны уточнения',
  clarified: 'Данные уточнены',
  ready_for_generation: 'Можно готовить решение',
  queued: 'В очереди',
  pending: 'Ожидает запуска',
  running: 'В работе',
  completed: 'Завершено',
  completed_with_warnings: 'Завершено с замечаниями',
  failed: 'Ошибка',
  canceled: 'Остановлено',
  loading: 'Загрузка материалов',
  parsing: 'Разбор материалов',
  extracting: 'Извлечение знаний',
  indexing: 'Индексация',
  preparing: 'Подготовка',
  retrieving: 'Подбор материалов',
  prompting: 'Подготовка текста для модели',
  model_generation: 'Ожидание ответа модели',
  persisting: 'Сохранение',
  validating: 'Проверка',
  finalizing: 'Финализация',
  publishing: 'Публикация',
  verification: 'Проверка решения',
  loaded: 'Загружено',
  indexed: 'Индексировано',
  validated: 'Проверено',
  active: 'Активна',
  selected_for_generation: 'Выбрана',
  archived: 'В архиве',
  rejected: 'Отклонено',
  unavailable: 'Недоступно',
  disabled: 'Отключено',
  registered: 'Добавлено',
  fetched: 'Получено',
  parsed: 'Разобрано',
  skipped: 'Пропущено',
  deprecated: 'Устарело',
  excluded: 'Исключено',
  published: 'Опубликовано',
  superseded: 'Есть более новая версия',
  incomplete: 'Неполный результат',
  passed: 'Без замечаний',
  passed_with_comments: 'Есть комментарии',
  success: 'Успешно',
  warning: 'Предупреждение',
  danger: 'Ошибка',
  not_determined: 'Требует проверки вручную',
  not_applicable: 'Не применяется',
  open: 'Открыто',
  answered: 'Ответы получены',
  closed: 'Закрыто',
  info: 'Информация',
  critical: 'Критично',
  major: 'Серьёзно',
  minor: 'Незначительно',
  requires_operator_decision: 'Нужно ручное решение',
  error: 'Ошибка',
  available: 'Доступно',
  ready: 'Готово',
  partial: 'Частично готово',
  insufficient: 'Недостаточно данных',
  normalized: 'Нормализовано',
  unnormalized: 'Требует нормализации',
  extracted: 'Извлечено',
  inferred: 'Выведено',
  review_required: 'Нужна проверка',
  new: 'Новый',
  changed: 'Изменён',
  deleted: 'Удалён',
  unchanged: 'Без изменений',
  manual: 'Ручной',
  monthly: 'Ежемесячно',
  weekly: 'Еженедельно',
  import: 'Импорт',
  upload: 'Дозагрузка',
  delete: 'Удаление',
  rebuild: 'Пересборка',
  scheduled_sync: 'Плановая синхронизация',
  system_mandatory: 'Системная baseline',
  user_managed: 'Пользовательская',
  full_scan: 'Полное сканирование',
  link_discovery: 'Обход ссылок',
};

const READINESS_LABELS: Record<string, string> = {
  goal_present: 'цель задачи',
  context_present: 'контекст',
  constraints_present: 'ограничения',
  integrations_present: 'интеграции',
  expected_output_present: 'ожидаемый результат',
  raw_text_length: 'описание задачи',
  context_note_count: 'контекстные заметки',
  clarification_answer_count: 'ответы на уточнения',
  goal: 'цель задачи',
  context: 'контекст',
  constraints: 'ограничения',
  integrations: 'интеграции',
  expected_output: 'ожидаемый результат',
  raw_text: 'описание задачи',
};

const AUDIT_EVENT_TITLES: Record<string, string> = {
  'generation.business_task.created': 'Создана задача',
  'generation.business_task.updated': 'Обновлена задача',
  'generation.business_task.clarification.answered': 'Получены ответы на уточнения',
  'generation.run.created': 'Запущена подготовка решения',
  'generation.run.completed': 'Решение подготовлено',
  'generation.run.failed': 'Подготовка решения завершилась ошибкой',
  'verification.run.created': 'Запущена проверка решения',
  'verification.run.completed': 'Проверка завершена',
  'verification.run.failed': 'Проверка завершилась ошибкой',
  'knowledge.source.created': 'Добавлен источник материалов',
  'knowledge.source.updated': 'Обновлён источник материалов',
  'knowledge.source.disabled': 'Источник материалов отключён',
  'knowledge.source.archived': 'Источник материалов отправлен в архив',
  'knowledge.document.registered': 'Добавлен материал',
  'knowledge.document.updated': 'Обновлён материал',
  'knowledge.document.disabled': 'Материал отключён',
  'knowledge.version.activated': 'Выбрана версия базы знаний',
  'knowledge.refresh.started': 'Начато обновление базы знаний',
  'knowledge.refresh.completed': 'База знаний обновлена',
  'knowledge.refresh.failed': 'Обновление базы знаний завершилось ошибкой',
};

export function titleStatus(status?: string | null) {
  return status ? STATUS_TITLES[status] ?? status : '—';
}

export function tone(status?: string | null) {
  if (!status) return 'neutral';
  if (['published', 'completed', 'passed', 'active', 'selected_for_generation', 'validated', 'ready_for_generation', 'closed', 'loaded', 'indexed', 'parsed', 'fetched', 'registered', 'available', 'success'].includes(status)) return 'success';
  if (['needs_clarification', 'warning', 'passed_with_comments', 'incomplete', 'answered', 'completed_with_warnings', 'not_determined', 'requires_operator_decision', 'pending', 'unavailable', 'draft'].includes(status)) return 'warning';
  if (['failed', 'critical', 'rejected', 'archived', 'canceled', 'disabled', 'excluded', 'error', 'danger'].includes(status)) return 'danger';
  return 'neutral';
}

export function verificationFindingImpact(status?: string | null, severity?: string | null) {
  if (status === 'passed') {
    return {
      label: 'Нормально',
      tone: 'neutral',
      description: 'Проверка пройдена, замечаний нет.',
    };
  }
  if (status === 'not_applicable') {
    return {
      label: 'Нейтрально',
      tone: 'neutral',
      description: 'Правило не применимо к выбранному объёму проверки.',
    };
  }
  if (status === 'warning') {
    return {
      label: 'Есть замечание',
      tone: 'warning',
      description: `Замечание без блокировки. Важность правила: ${titleStatus(severity)}.`,
    };
  }
  if (status === 'not_determined') {
    return {
      label: 'Нужно проверить вручную',
      tone: 'warning',
      description: `Автоматическая проверка не смогла дать итог. Важность правила: ${titleStatus(severity)}.`,
    };
  }
  if (status === 'failed') {
    return {
      label: severity === 'critical' ? 'Критично' : titleStatus(severity),
      tone: 'danger',
      description: `Найдено нарушение. Важность правила: ${titleStatus(severity)}.`,
    };
  }
  return {
    label: titleStatus(status),
    tone: 'neutral',
    description: `Статус проверки: ${titleStatus(status)}.`,
  };
}

export function truncate(value: string, size = 120) {
  return value.length > size ? `${value.slice(0, size)}…` : value;
}

export function groupTitleFromRule(ruleName?: string | null) {
  const value = ruleName ?? '';
  if (value.startsWith('VR-STR') || value.includes('структ')) return 'Структура решения';
  if (value.startsWith('VR-NRM') || value.includes('норм')) return 'Нормативные требования';
  if (value.startsWith('VR-CNS') || value.includes('соглас')) return 'Согласованность';
  if (value.startsWith('VR-TEC') || value.includes('техн')) return 'Технические проверки';
  return 'Прочие проверки';
}

export function operationKindLabel(value?: string | null) {
  const map: Record<string, string> = {
    knowledge_update_run: 'Обновление базы знаний',
    generation_run: 'Подготовка решения',
    verification_run: 'Проверка решения',
  };
  return value ? map[value] ?? value : '—';
}

export function refreshPolicyLabel(value?: string | null) {
  const map: Record<string, string> = {
    monthly: 'Авто: раз в месяц',
    weekly: 'Авто: раз в неделю',
    manual: 'Только вручную',
  };
  return value ? map[value] ?? value : '—';
}

export function sourceTypeLabel(value?: string | null) {
  const map: Record<string, string> = {
    repository: 'Локальная папка',
    local_folder: 'Локальная папка',
    url_list: 'URL-источник',
    url: 'URL-источник',
    manual_upload: 'Ручная дозагрузка',
    catalog: 'Каталог',
    manual_registry: 'Ручной список',
  };
  return value ? map[value] ?? value : '—';
}

export function documentTypeLabel(value?: string | null) {
  const map: Record<string, string> = {
    normative: 'Нормативный документ',
    architecture: 'Архитектурный документ',
    api: 'API-описание',
    technology: 'Технологический стандарт',
    other: 'Прочее',
  };
  return value ? map[value] ?? value : '—';
}

export function safeJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function formatKnowledgeVersionLabel(value?: { created_at?: string | null; activated_at?: string | null } | null) {
  if (!value) return 'Версия не выбрана';
  const stamp = value.activated_at ?? value.created_at;
  return stamp ? `Версия от ${formatDateTime(stamp)}` : 'Выбранная версия';
}

export function readinessLabel(key: string) {
  return READINESS_LABELS[key] ?? key.replace(/_/g, ' ');
}

export function auditEventTitle(value?: string | null) {
  return value ? AUDIT_EVENT_TITLES[value] ?? value : 'Событие';
}

export function auditMessageText(value?: string | null) {
  if (!value) return '—';

  const simpleMap: Record<string, string> = {
    'Business task created': 'Задача создана',
    'Business task created through canonical MVP intake': 'Задача создана',
    'Business task updated': 'Задача обновлена',
    'Clarification answers submitted': 'Ответы на уточнения сохранены',
    'Generation run created': 'Подготовка решения запущена',
    'Knowledge retrieval started': 'Начат подбор материалов из базы знаний',
    'Knowledge fragments selected': 'Материалы из базы знаний подобраны',
    'Prompt artifact prepared': 'Текст запроса к модели подготовлен',
    'LLM request sent; waiting for model response': 'Запрос отправлен в модель, ждём ответ',
    'LLM response received': 'Ответ модели получен',
    'LLM response received; validation started': 'Ответ модели получен, начата проверка',
    'LLM response validated': 'Ответ модели проверен',
    'Validation passed; persisting solution': 'Проверка пройдена, решение сохраняется',
    'Solution persisted; publishing rendered artifact': 'Решение сохранено, готовится публикация',
    'Solution published': 'Решение опубликовано',
    'Generation run was interrupted by API restart during local inline execution.': 'Запуск был прерван перезапуском API во время локального inline-выполнения',
    "Section 'business_architecture' does not expose allowed ArchiMate 3.2 objects": 'В разделе «Бизнес-архитектура» не распознаны допустимые объекты ArchiMate 3.2',
    'Risk mitigations must be specific': 'Для рисков нужны конкретные меры: ответственный, действие, контрольная точка и условие отката или запасной вариант.',
    'Generation run completed and solution published': 'Решение подготовлено и сохранено',
    'Generation run failed': 'Во время подготовки решения произошла ошибка',
    'Verification run created': 'Проверка решения запущена',
    'Verification run completed and protocol issued': 'Проверка завершена, итог сохранён',
    'Verification run failed': 'Во время проверки произошла ошибка',
    'Knowledge version activated': 'Выбрана версия базы знаний',
    'Knowledge update run created': 'Создано обновление базы знаний',
    'Knowledge update run finished': 'Обновление базы знаний завершено',
    'Knowledge update run failed': 'Обновление базы знаний завершилось ошибкой',
  };

  if (simpleMap[value]) return simpleMap[value];

  let match = value.match(/^Document '(.+)' registered$/);
  if (match) return `Добавлен материал: «${match[1]}»`;
  match = value.match(/^Document '(.+)' updated$/);
  if (match) return `Обновлён материал: «${match[1]}»`;
  match = value.match(/^Document '(.+)' disabled$/);
  if (match) return `Материал отключён: «${match[1]}»`;
  match = value.match(/^Knowledge source '(.+)' registered in draft state$/);
  if (match) return `Добавлен источник материалов: «${match[1]}»`;
  match = value.match(/^Knowledge source '(.+)' updated$/);
  if (match) return `Обновлён источник материалов: «${match[1]}»`;
  match = value.match(/^Knowledge source '(.+)' disabled$/);
  if (match) return `Источник материалов отключён: «${match[1]}»`;
  match = value.match(/^Knowledge source '(.+)' archived$/);
  if (match) return `Источник материалов отправлен в архив: «${match[1]}»`;

  return value;
}

export function entityLabel(value: string) {
  const map: Record<string, string> = {
    business_task_id: 'Задача',
    solution_version_id: 'Решение',
    verification_protocol_id: 'Протокол проверки',
    candidate_version_id: 'Подготовленная версия базы знаний',
    activated_version_id: 'Выбранная версия базы знаний',
    knowledge_version_id: 'Версия базы знаний',
  };
  return map[value] ?? value.replace(/_/g, ' ');
}

export function knowledgeBaseKindLabel(value?: string | null) {
  const map: Record<string, string> = {
    system_mandatory: 'Системная baseline',
    user_managed: 'Пользовательская',
  };
  return value ? map[value] ?? value : '—';
}

export function extractedItemTypeLabel(value?: string | null) {
  const map: Record<string, string> = {
    summary: 'Краткая выжимка',
    normative_rule: 'Нормативное правило',
    architectural_principle: 'Архитектурный принцип',
    constraint: 'Ограничение',
    mandatory_requirement: 'Обязательное требование',
    entity: 'Сущность',
    entity_relation: 'Связь сущностей',
    integration_requirement: 'Интеграционное требование',
    technology_standard: 'Технологический стандарт',
    term: 'Термин',
    risk: 'Риск / оговорка',
  };
  return value ? map[value] ?? value : '—';
}

export function formatSeconds(value?: number | null) {
  if (value == null) return '—';
  if (value < 60) return `${value} сек`;
  const minutes = Math.floor(value / 60);
  const seconds = value % 60;
  if (minutes < 60) return `${minutes} мин ${seconds} сек`;
  const hours = Math.floor(minutes / 60);
  const restMinutes = minutes % 60;
  return `${hours} ч ${restMinutes} мин`;
}

export function solutionSectionLabel(value?: string | null, fallbackTitle?: string | null) {
  if (!value) return fallbackTitle ?? '—';
  return TOGAF_SECTION_TITLES[value] ?? fallbackTitle ?? value;
}

export function architectureBoundaryLabel(value?: string | null) {
  if (!value) return 'Архитектурный слой не указан';
  return ARCHITECTURE_BOUNDARY_TITLES[value] ?? value;
}

export function verificationRuleGroupLabel(value?: string | null) {
  const map: Record<string, string> = {
    structure: 'Соответствие структуре TOGAF',
    normative: 'Соответствие метамодели ArchiMate',
    consistency: 'Семантическая согласованность',
    technical: 'Техническая готовность',
    other: 'Прочие проверки',
  };
  return value ? map[value] ?? value : 'Прочие проверки';
}
