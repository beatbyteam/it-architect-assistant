# Инвентарь компонентов фронтенда

Источник анализа: `frontend/src/app/App.tsx`, `frontend/src/pages`, `frontend/src/features`, `frontend/src/entities`, `frontend/src/shared/ui/components.tsx`, `frontend/src/styles.css`.

Исключены из инвентаризации: `node_modules`, `dist`, `.test-dist`, `src/generated`, тесты и API/helper-файлы без UI-разметки.

## 1. Каркас приложения и навигация

- `App` - корневой компонент приложения.
- `AppProviders` - обертка `QueryClientProvider` и выбор `BrowserRouter`/`MemoryRouter`.
- `AppRoutes` - дерево маршрутов приложения.
- `AppLayout` - общий layout с боковой навигацией и областью страницы.
- `app-shell` - двухколоночный каркас приложения.
- `sidebar` - боковая панель навигации.
- `brand` - брендовый блок в sidebar.
- `nav-list` - список навигационных ссылок.
- `nav-item` - ссылка навигации с active-состоянием.
- `main-shell` - контейнер основного контента.
- `page` - внутренний контейнер страницы.
- `stack` - вертикальная раскладка страницы.
- `Outlet` - место рендера текущего маршрута.
- `Navigate` fallback - редирект неизвестных маршрутов на главную.

Маршруты верхнего уровня:

- `/` - `DashboardPage`.
- `/tasks/new` - `NewTaskPage`.
- `/registry` - `RegistryPage`.
- `/tasks/:taskId` - `TaskWorkspacePage`.
- `/solutions/:solutionId` - `SolutionPage`.
- `/protocols/:protocolId` - `ProtocolPage`.
- `/knowledge` - `KnowledgePage`.
- `/knowledge/bases/:knowledgeBaseId` - `KnowledgeBaseDetailsPage`.
- `/knowledge/documents/:documentId` - `KnowledgeDocumentPage`.
- `/operations` - `OperationsPage`.
- `/operations/:operationId` - `OperationDetailsPage`.

## 2. Страницы и крупные блоки

### `DashboardPage`

- Заголовок страницы с CTA "Создать задачу".
- Карточка активной версии знаний.
- Banner состояния активной версии знаний.
- Блок действий базы знаний: открыть базу знаний, открыть выбранную базу.
- Сетка из 4 статистических карточек: нужны уточнения, готовы к решению, последние решения, последние проверки.
- Карточка последних задач.
- Timeline последних задач.
- Timeline item задачи: заголовок, статус, даты, id, действие.
- Карточка готовых решений.
- Timeline готовых решений.
- Timeline item решения: заголовок, статус, публикация, ссылки на решение и проверку.
- Карточка последних проверок.
- Timeline проверок.
- Timeline item проверки: summary, статус, дата, количество замечаний, ссылка на протокол.
- Карточка уведомлений по базам знаний.
- Timeline уведомлений.
- Timeline item уведомления: заголовок, статус, сообщение, база, дата, ссылки на базу и ход обновления.
- Loading, error и empty-состояния для каждой выборки.

### `NewTaskPage`

- Заголовок страницы.
- Карточка версии знаний для генерации.
- Banner активной/отсутствующей версии знаний.
- `KnowledgeScopeSelector` в compact-режиме.
- Карточка описания задачи.
- Форма создания задачи.
- Поле короткого названия.
- Поле подробного описания.
- Счетчик символов.
- Banner локальной ошибки валидации.
- ErrorNotice сохранения задачи.
- Кнопка сохранения черновика.
- Кнопка отправки на проверку входных данных.
- Карточка подсказок для прохождения без уточнений.
- Compact list подсказок.

### `RegistryPage`

- Заголовок страницы с CTA "Создать задачу".
- Warning banner просроченных уточнений.
- Сетка из 4 статистических карточек: нужны уточнения, можно готовить решение, загружено решений, проверки с ошибкой.
- Карточка фильтров.
- Tab strip вкладок: задачи, решения, проверки.
- Поисковое поле.
- Select статуса, динамический по текущей вкладке.
- Два date input для периода.
- Текст активного диапазона дат.
- Кнопка сброса фильтров.
- LoadingState текущей вкладки.
- Карточка таблицы задач.
- Таблица задач: задача, статус, уточнения, обновлена, действие.
- EmptyState задач с CTA.
- Карточка таблицы решений.
- Таблица решений: решение, статус, проверки, дата публикации, действия.
- Карточка таблицы проверок.
- Таблица проверок: проверка, итог, статус, замечания, создана, действия.
- Actions в заголовках таблиц: счетчик загруженных строк и кнопка "Показать еще".

### `TaskWorkspacePage`

- Заголовок рабочей области задачи.
- ErrorNotice запуска подготовки решения.
- Banner результата dispatch: нужны уточнения или generation run запущен.
- Карточка "База знаний для этого запуска".
- `KnowledgeScopeSelector` в compact-режиме.
- `TaskSummarySection`.
- Карточка "Что нужно для запуска".
- State box готовности к запуску.
- Compact list недостающих входных данных.
- `DraftEditorCard`, если задача в состоянии `draft`.
- `ClarificationsCard`.
- `ClarificationHistoryCard`, если есть история уточнений.
- `SolutionAndProtocolSection`, если уже есть решение или протокол.

### `SolutionPage`

- Заголовок решения с возвратом к задаче.
- ErrorNotice запуска проверки.
- Danger banner последней failed-проверки.
- `SolutionHeaderCards`.
- `KnowledgeScopeSummary`.
- Tab strip вкладок решения: TOGAF-документ, основания и знания, архитектурная модель, история проверок.
- `SolutionContentTab`.
- `SolutionBasisTab`.
- `SolutionModelTab`.
- `SolutionHistoryTab`.
- Hash-scroll к секции решения вида `#section-...`.

### `ProtocolPage`

- Заголовок протокола с возвратом к решению.
- Warning banner incomplete-проверки.
- Danger banner важных замечаний.
- Сетка из 4 карточек: итог, статус протокола, критичные нарушения, замечания по TOGAF/ArchiMate.
- `KnowledgeScopeSummary` области знаний проверки.
- Карточка веб-артефакта протокола.
- `html-preview` rendered HTML протокола.
- Карточка паспорта протокола.
- State box summary протокола.
- Карточка фильтров и агрегатов.
- Toolbar с search input и select-фильтрами по важности, статусу, группе правил.
- Две section-box сводки: по статусам, по важности.
- Карточка `Compliance summary`.
- Внутренние карточки compliance-групп.
- Карточка пояснения к проверке.
- Карточка снимка базы знаний.
- Карточка сводки по снимку.
- Карточка истории публикаций протокола.
- Timeline ревизий публикации.
- Карточка материалов проверки.
- Таблица материалов проверки.
- Карточка замечаний и нарушений.
- Группы нарушений по rule group.
- Timeline замечаний в каждой группе.
- Карточка ручной проверки замечаний без evidence.
- Карточка технической диагностики.
- Diagnostic JSON blocks.

### `KnowledgePage`

- Заголовок реестра баз знаний с переходом в журнал.
- LoadingState загрузки баз.
- Banner выбранной/не выбранной пользовательской базы.
- Сетка из 4 статистических карточек: всего баз, пользовательские базы, обновления, требуют внимания.
- Карточка создания пользовательской базы.
- Поле названия базы.
- Поле описания базы.
- ErrorNotice создания базы.
- Кнопка создания базы.
- Карточка плановых обновлений.
- Banner результата планового запуска.
- ErrorNotice планового запуска.
- Кнопка запуска плановых обновлений.
- Карточка реестра баз знаний.
- Timeline баз знаний.
- Timeline item базы: название, selected badge, status badge, тип, версии, описание, источники, синхронизация, документы, действия.
- Карточка последних уведомлений об обновлениях.
- Timeline уведомлений.
- ErrorNotice источников и метрик.

### `KnowledgeBaseDetailsPage`

- Заголовок карточки базы знаний с возвратом в реестр.
- Сетка из 4 карточек: тип, источники, документы, длительность обновления.
- Banner выбранности базы для подготовки решений.
- Info banner защиты системной baseline-базы.
- Карточка выбора базы для подготовки решений.
- Select версии для генерации.
- Описание выбранной версии.
- ErrorNotice выбора базы.
- Кнопка выбора для подготовки решений.
- Карточка обновления базы.
- Данные последнего запуска: статус, длительность.
- ErrorNotice синхронизации.
- Кнопка ручного обновления.
- Ссылка на ход последнего обновления.
- Карточка источников.
- Timeline источников.
- Timeline item источника: название, status badge, refresh policy badge, тип, URI, ссылка открытия, счетчики и даты.
- Настройки источника: select политики обновления, select статуса, кнопка сохранения.
- Форма нового источника: название, тип, путь/URL, кнопка добавления.
- Карточка дозагрузки документа.
- Поле названия загружаемого документа.
- File input.
- Banner статуса обработки загруженного документа.
- ErrorNotice загрузки.
- Кнопка дозагрузки и запуска обучения.
- Карточка версий базы знаний.
- Timeline версий.
- Timeline item версии: номер, active badge, status badge, даты, причина, документы, ошибки, SLA, кнопки показать состав/активировать.
- Карточка истории обновлений.
- Timeline запусков обновления.
- Timeline item запуска: тип, статус, даты, этап, версии, счетчики, ссылка на процесс.
- Карточка состава выбранной версии.
- Select версии состава.
- Timeline документов версии.
- Timeline item документа: title, delta/status badges, источник, тип, роль, URI, действия открыть/удалить.
- Карточка уведомлений.
- Timeline уведомлений.
- Карточка ошибок последнего обновления.
- Timeline ошибок.

### `KnowledgeDocumentPage`

- Заголовок документа с возвратом к базе.
- Карточка режима просмотра.
- Tab strip режимов: читать, проверить источники, дебаг.
- Help text текущего режима.
- Карточка документа.
- Поля паспорта документа: тип, источник, URI, итоговый URI, статус, даты, checksum.
- Действия открытия исходного и итогового URL.
- Карточка памяти документа.
- Сводка, способ извлечения, признаки LLM/fallback.
- Счетчики типов извлеченных элементов.
- Debug-фильтры памяти: select типа элемента и select качества.
- Banner отсутствующего snapshot.
- ErrorNotice snapshot.
- Banner fallback-извлечения.
- Banner выбранного фрагмента.
- Карточка единого обзора знаний.
- Article/section-box блока знания.
- Meta строка блока знания.
- Pre-wrap контент блока знания.
- Кнопка показать/скрыть источник.
- Кнопка открыть фрагмент в debug-режиме.
- Evidence state-box: цитата, фрагмент, исходный текст.
- Debug-only двухколоночный блок `two-col`.
- Карточка нормализованного текста.
- Preserve-lines section-box нормализованного текста.
- Карточка извлеченных элементов.
- Section-box извлеченного элемента.
- Diagnostic JSON structured payload.
- Карточка фрагментов снимка.
- Section-box фрагмента снимка.
- Состояние выбранного фрагмента `chunk-selected` в JSX.

### `OperationsPage`

- Заголовок журнала.
- Info banner назначения журнала.
- Сетка из 4 статистических карточек: в работе, с ошибкой, с замечаниями, системные события.
- ErrorNotice сводки журнала.
- Карточка фильтров.
- Toolbar фильтров: тип процесса, статус, поиск, сброс.
- Карточка последних процессов.
- Actions заголовка: счетчик загруженных процессов, кнопка "Показать еще".
- Timeline процессов.
- Timeline item процесса: вид операции, статус, старт, длительность, шаг, исполнитель, проблемный шаг, error code, correlation id, ссылка на процесс.
- Карточка последних системных событий.
- Actions заголовка: счетчик загруженных событий, кнопка "Показать еще".
- Timeline audit events.
- Timeline item события: title, severity badge, message, event time, correlation id.

### `OperationDetailsPage`

- Заголовок карточки процесса с возвратом к журналу.
- Карточка режима просмотра.
- Tab strip режимов: читать, проверить ход, дебаг.
- Help text текущего режима.
- Alert banner failed/completed_with_warnings процесса.
- Карточка общей информации.
- `KeyValueTable` со статусом, шагом, датами, длительностью, исполнителем, correlation id, error code, проблемным шагом.
- State box summary процесса.
- Карточка связанных объектов.
- `KeyValueTable` ссылок на задачу, решение, протокол или mono-id.
- Карточка шагов выполнения.
- Timeline шагов.
- Timeline item шага: title, status badge, detail, error code, time, debug payload.
- Карточка метрик обновления базы, только для `knowledge_update_run`.
- Сетка из 4 state-box метрик: обработано, переиспользовано, ошибок обработки, фактическая длительность.
- Debug stage metrics.
- Карточка системных событий, только в verify/debug.
- Timeline системных событий.
- Карточка технических данных, только в debug.

## 3. Доменные feature/entity компоненты

### Knowledge entity

- `KnowledgeScopeSelector` - выбор пользовательской базы знаний и версии для генерации.
- Заголовок/описание селектора в non-compact варианте.
- Banner обязательного baseline.
- Banner отсутствия пользовательских баз.
- Select пользовательской базы.
- Строка метаданных выбранной базы.
- Active badge выбранной базы.
- Select версии базы знаний.
- Описание выбранной версии.
- ErrorNotice применения выбора.
- Кнопка сохранения выбора.
- `KnowledgeScopeSummary` - сводка реально использованного knowledge scope.
- Section-box optional baseline.
- Section-box выбранной пользовательской базы.
- Effective version IDs list.
- Generation snapshot version row.
- `KnowledgeVersionBadge` - thin wrapper над `Badge`.

### Task workspace feature

- `TaskSummarySection` - сводка задачи, подготовки решения и последней проверки.
- Карточка "О задаче".
- State box исходного текста задачи.
- Карточка "Подготовка решения".
- Карточка "Последняя проверка решения".
- CTA подготовки решения.
- CTA проверки решения.
- Ссылки на решение, протокол и операции.
- `DraftEditorCard` - форма редактирования черновика.
- `ClarificationsCard` - список открытых уточнений.
- Form section-box для каждого уточнения.
- Textarea ответа на каждый вопрос.
- Local error banner.
- `ClarificationHistoryCard` - timeline закрытых уточнений и ответов.
- `SolutionAndProtocolSection` - превью решения и итог последней проверки в рабочей области.
- `FindingsGroup` - группа замечаний проверки с переходом к секции решения.

### Solution page feature

- `SolutionHeaderCards` - паспорт решения, блок проверки, KPI-карточки.
- Карточка паспорта решения.
- Карточка проверки решения.
- Сетка KPI: готовые секции, частично готовые, недостаточно данных, связей в модели.
- `SolutionContentTab` - контент решения.
- Карточка краткого вывода.
- Карточка веб-версии решения.
- Banner отсутствующей веб-версии.
- Карточка TOGAF-секций.
- Section-box TOGAF-секции.
- Карточка архитектурных объектов, интеграций и рисков.
- Section-box компонента архитектуры.
- Section-box интеграций.
- Section-box рисков.
- `SolutionBasisTab` - основания и знания.
- Карточка оснований решения.
- Карточка профиля подбора материалов.
- Карточка guidance по секциям.
- Карточка сводки по снимку.
- Таблица использованных материалов.
- Таблица покрытия разделов.
- `SolutionModelTab` - архитектурная модель.
- KPI-карточки модели.
- Карточка готовности секций.
- Карточка диагностики модели.
- Section-box сущностей по слоям ArchiMate.
- Таблица сущностей.
- Таблица связей модели.
- `SolutionHistoryTab` - история проверок и публикаций.
- Timeline проверок.
- Timeline публикаций.

## 4. Общие UI-компоненты

- `PageHeader` - заголовок страницы, optional subtitle, optional actions.
- `Card` - секция с optional title, subtitle, actions и body.
- `Badge` - статусный бейдж с tone через `tone()` и label через `titleStatus()`.
- `Button` - кнопка, поддерживает primary-вариант.
- `Input` - input с базовым классом `input`.
- `Textarea` - textarea с базовым классом `textarea`.
- `Select` - select с базовым классом `input`.
- `FormRow` - label + control + optional hint.
- `LoadingState` - state box загрузки.
- `ErrorState` - state box ошибки.
- `ErrorNotice` - API-aware ошибка с message, error code, request id, operation id.
- `EmptyState` - пустое состояние с title, optional description, optional action.
- `Banner` - информационный/предупреждающий/опасный баннер.
- `StatCard` - компактная карточка метрики.
- `KeyValueTable` - definition list для пар ключ-значение.

## 5. Повторяющиеся layout/pattern компоненты из CSS

- `grid`, `grid-2`, `grid-4` - сетки карточек/таблиц/секций.
- `grid-3` - CSS-вариант сетки, сейчас не встречается в JSX.
- `stack`, `compact` - вертикальные группы и компактный вариант.
- `actions`, `between`, `end-span` - строки действий, разнесение по краям, растяжение на всю сетку.
- `tab-strip` - горизонтальный набор таб-кнопок.
- `toolbar-grid`, `toolbar-grid-4` - панели фильтров.
- `two-col` - двухколоночная раскладка документа в debug-режиме.
- `table-wrap`, `table` - адаптивная обертка и таблица.
- `timeline`, `timeline-item` - вертикальный список событий/сущностей.
- `section-box` - внутренний boxed-блок внутри карточек.
- `state-box`, `state-error` - state container и error-вариант.
- `banner`, `banner-info`, `banner-warning`, `banner-danger` - баннеры состояний.
- `badge`, `badge-success`, `badge-warning`, `badge-danger`, `badge-neutral` - бейджи статусов.
- `button`, `button-primary` - кнопки и ссылочные кнопки через `Link`/`a`.
- `input`, `textarea` - поля формы.
- `form-row`, `form-label` - структура строки формы.
- `card`, `card-header`, `compact-card` - карточки и их шапки.
- `page-header` - область заголовка страницы.
- `muted`, `small`, `mono` - текстовые атомы.
- `compact-list` - компактный список `ul`.
- `pre-wrap`, `preserve-lines` - режимы сохранения переносов.
- `diagnostic-box` - темный блок JSON/diagnostics.
- `html-preview` - контейнер rendered HTML.
- `dl-grid`, `dl-row` - пары ключ-значение.

CSS-классы, которые определены в `styles.css`, но сейчас не используются в JSX как активные компоненты сайта:

- `topbar`
- `checkbox-row`
- `code-block`
- `link-button`
- `row-inline`
- `rendered-html`
- `compare-grid`
- `list-button`
- `timeline-item-selected`
- `inline-code-list`
- `uri-wrap`

Отдельная проверка: `KnowledgeDocumentPage` использует класс состояния `chunk-selected`, но в `styles.css` для него нет правила.

## 6. Атомы и базовые HTML-элементы UI

- Текстовые заголовки: `h1`, `h2`, `h3`, `strong`.
- Обычный текст: `div`, `p`, `span`.
- Muted/secondary text: `muted`, `small`.
- Mono text/id: `mono`.
- Навигационные ссылки: `NavLink`, `Link`, внешний `a`.
- Кнопки: `button`, `Button`, ссылочные кнопки через `className="button"`.
- Поля ввода: text input, date input, file input.
- Многострочное поле: `textarea`.
- Select/option.
- Form и label.
- Списки: `ul`, `li`, `compact-list`.
- Таблицы: `table`, `thead`, `tbody`, `tr`, `th`, `td`.
- Definition list: `dl`, `dt`, `dd`.
- Preformatted blocks: `pre`, `pre-wrap`, `diagnostic-box`.
- Rendered HTML containers через `dangerouslySetInnerHTML`: `html-preview`.
- Status atoms: `Badge`, `Banner`, `state-box`, `EmptyState`, `LoadingState`, `ErrorState`, `ErrorNotice`.
