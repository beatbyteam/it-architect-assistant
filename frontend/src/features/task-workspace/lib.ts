export function isTerminal(state?: string | null) {
  return ['completed', 'failed', 'canceled'].includes(state ?? '');
}

export function diagnosticsOperationId(diagnostics?: Record<string, unknown> | null, fallbackOperationId?: string | null) {
  const value = diagnostics?.operation_id ?? diagnostics?.run_operation_id ?? diagnostics?.operation_ref ?? fallbackOperationId;
  return typeof value === 'string' ? value : null;
}

const LOW_SIGNAL_ANSWERS = new Set([
  'n/a',
  'na',
  'нет',
  'не знаю',
  'unknown',
  'none',
  '-',
  '?',
  'todo',
  'tbd',
  'пока не знаю',
  'непонятно',
  'без деталей',
  'что-нибудь',
  'как-нибудь',
  'потом уточню',
  'неважно',
]);

export type ClarificationDraftStatus = 'empty' | 'generic' | 'partial' | 'ready';

export function getClarificationGuidance(questionCode: string): string {
  switch (questionCode) {
    case 'goal':
      return 'Укажите цель, объект изменений и ожидаемый бизнес-эффект: например, сократить срок, снизить затраты, повысить качество или улучшить SLA.';
    case 'context':
      return 'Опишите текущую ситуацию: какая система, процесс или команда участвуют и в чём состоит основная проблема.';
    case 'constraints':
      return 'Назовите конкретные ограничения: сроки, безопасность, нагрузка, бюджет, регуляторные требования или зависимость от смежных систем.';
    case 'integrations':
      return 'Укажите системы, API, данные или каналы обмена. Короткий ответ «Интеграций нет» тоже подходит.';
    case 'expected_output':
      return 'Уточните, какой результат ожидается: концепт, HLD, схема интеграций, компонентная модель, рекомендации или другой артефакт.';
    default:
      return 'Ответ лучше делать конкретным: с объектом, контекстом и ожидаемым результатом.';
  }
}

export function evaluateClarificationDraft(questionCode: string, rawValue: string): { status: ClarificationDraftStatus; message?: string } {
  const normalized = rawValue.trim().replace(/\s+/g, ' ');
  if (!normalized) return { status: 'empty' };

  const lowered = normalized.toLowerCase();
  if (LOW_SIGNAL_ANSWERS.has(lowered)) {
    return { status: 'generic', message: 'Ответ пока выглядит слишком общим. Лучше добавить немного конкретики по сути вопроса.' };
  }

  switch (questionCode) {
    case 'goal': {
      const hasObjective = /(цель|целев|сниз|уменьш|ускор|автомат|повыс|сократ|оптимиз|обеспеч|мигр|внедр|улучш)/i.test(lowered);
      const hasSubject =
        /(процесс|заяв|заказ|клиент|отчет|сервис|систем|данн|интеграц|канал|поток|документ|маршрут|согласован)/i.test(lowered) ||
        lowered.split(' ').filter((item) => item.length >= 5).length >= 3;
      const hasEffect =
        /(результат|эффект|outcome|business outcome|чтобы|для того|в результате|эконом|sla|доступност|качеств|точност|срок|время|стоим|метрик|kpi)/i.test(lowered) ||
        /\d/.test(lowered);

      if (hasObjective && hasSubject && hasEffect) {
        return { status: 'ready', message: 'Ответ выглядит достаточно конкретным.' };
      }
      if (hasObjective && hasSubject) {
        return { status: 'partial', message: 'Цель уже понятна, но лучше добавить ожидаемый бизнес-эффект или метрику результата.' };
      }
      return { status: 'generic', message: 'Нужны не только намерение, но и объект изменений, а также ожидаемый эффект.' };
    }

    case 'context': {
      const hasCurrentState = /(сейчас|текущ|as is|существующ|сегодня|имеется|используется|контекст)/i.test(lowered);
      const hasScopeEntity = /(систем|процесс|контур|модул|приложен|команд|пользоват|канал|crm|erp|sap|1с|кафка|шина)/i.test(lowered);
      const hasPainPoint = /(проблем|ручн|ошиб|долго|узк|не хватает|разрознен|задерж|неудоб|дублир|потер)/i.test(lowered);

      if (hasCurrentState && (hasScopeEntity || hasPainPoint)) {
        return { status: 'ready', message: 'Контекст уже описан достаточно ясно.' };
      }
      if (hasCurrentState || hasScopeEntity || hasPainPoint) {
        return { status: 'partial', message: 'Есть часть контекста, но можно точнее описать текущую ситуацию и проблему.' };
      }
      return { status: 'generic', message: 'Лучше описать текущую систему или процесс и что именно в них не устраивает.' };
    }

    case 'constraints': {
      if (/(ограничений нет|жестких ограничений нет|без ограничений|нет специальных ограничений)/i.test(lowered)) {
        return { status: 'ready', message: 'Явное отсутствие ограничений тоже считается корректным ответом.' };
      }

      const hasCategory = /(огранич|срок|sla|бюдж|безопас|нагруз|регламент|требован|latency|availability|дедлайн|месяц|недел|квартал)/i.test(lowered);
      const hasDetail = /\d/.test(lowered) || /(не более|не меньше|только|запрещ|обязательно|должен|нельзя|допускается)/i.test(lowered);

      if (hasCategory && hasDetail) {
        return { status: 'ready', message: 'Ограничения описаны достаточно предметно.' };
      }
      if (hasCategory) {
        return { status: 'partial', message: 'Тип ограничения понятен, но лучше добавить конкретику.' };
      }
      return { status: 'generic', message: 'Нужны конкретные ограничения: сроки, бюджет, безопасность, нагрузка или регуляторика.' };
    }

    case 'integrations': {
      if (/(интеграций нет|без интеграций|внешних систем нет|автономно|изолированно)/i.test(lowered)) {
        return { status: 'ready', message: 'Короткий ответ про отсутствие интеграций подходит.' };
      }

      const hasCounterparty = /(sap|1с|crm|erp|dwh|kafka|postgres|oracle|email|ldap|ad|billing|api gateway|service bus|очеред|интегр|внешн|смежн|систем|витрин|каталог)/i.test(lowered);
      const hasExchange = /(api|rest|soap|webhook|файл|обмен|событ|очеред|mq|данн|статус|запрос|синхрон|асинхрон|topic|queue)/i.test(lowered);

      if (hasCounterparty && hasExchange) {
        return { status: 'ready', message: 'Интеграции описаны понятно.' };
      }
      if (hasCounterparty || hasExchange) {
        return { status: 'partial', message: 'Есть часть информации, но лучше уточнить и систему, и тип обмена.' };
      }
      return { status: 'generic', message: 'Лучше назвать систему или сервис и способ обмена, либо явно указать, что интеграций нет.' };
    }

    case 'expected_output': {
      const hasArtifactType = /(hld|high-level|концепт|концепция|архитектурн|решени|дизайн|компонентн|интеграцион|диаграм|схем|модел|документ|рекомендац)/i.test(lowered);
      const hasDetailLevel = /(верхнеуров|деталь|на уровне|для согласования|чернов|подроб|только концепт|без детализации|вариант)/i.test(lowered);

      if (hasArtifactType && hasDetailLevel) {
        return { status: 'ready', message: 'Ожидаемый результат описан ясно.' };
      }
      if (hasArtifactType) {
        return { status: 'partial', message: 'Тип результата понятен, но можно уточнить глубину или фокус.' };
      }
      return { status: 'generic', message: 'Укажите, что именно нужно на выходе: концепт, HLD, схема, модель или рекомендации.' };
    }

    default:
      if (normalized.length < 8) {
        return { status: 'generic', message: 'Ответ пока слишком короткий и общий.' };
      }
      return { status: 'partial', message: 'Ответ сохранится, но лучше сделать его конкретнее.' };
  }
}
