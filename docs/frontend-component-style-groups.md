# Группировка компонентов к единой стилистике

Источник: `docs/frontend-component-inventory.md`.

Цель этого документа - первый слой унификации. Он не меняет код, а сводит похожие UI-блоки к каноническим названиям дизайн-системы, чтобы дальше можно было безопасно выносить/переименовывать компоненты.

## 1. Канонические группы

| Каноническое имя | Что объединяет сейчас | Варианты |
| --- | --- | --- |
| `AppShell` | `app-shell`, `sidebar`, `brand`, `nav-list`, `nav-item`, `main-shell`, `page` | `SidebarNav`, `Brand`, `MainContent`, `PageContainer` |
| `PageHeader` | общий заголовок страницы, subtitle, actions | `PageHeader`, `PageHeaderWithActions` |
| `Card` | `Card`, карточки страниц, карточки KPI, карточки вложенных summary-блоков | `Card`, `MetricCard`, `InnerCard`, `PreviewCard`, `FormCard` |
| `Panel` | `section-box`, вложенные boxed-блоки внутри карточек | `SectionPanel`, `EvidencePanel`, `DebugPanel`, `FormPanel`, `MetricPanel` |
| `Badge` | `Badge`, `KnowledgeVersionBadge`, `badge-*`, active/status/severity бейджи | `StatusBadge`, `SeverityBadge`, `ActiveBadge`, `VersionBadge` |
| `Banner` | `Banner`, raw alert banner в `OperationDetailsPage`, info/warning/danger сообщения | `InfoBanner`, `WarningBanner`, `DangerBanner` |
| `Button` | `Button`, `Link className="button"`, `a className="button"`, tab-кнопки, action-кнопки | `Button`, `PrimaryButton`, `LinkButton`, `ExternalLinkButton`, `TabButton` |
| `FormField` | `FormRow`, `Input`, `Textarea`, `Select`, date/file inputs | `TextField`, `TextareaField`, `SelectField`, `DateField`, `FileField` |
| `Toolbar` | `toolbar-grid`, `toolbar-grid-4`, строки фильтров и actions в заголовках карточек | `FilterToolbar`, `CardActions`, `LoadMoreToolbar` |
| `Tabs` | `tab-strip`, кнопки режимов и вкладок | `TabList`, `ViewModeTabs`, `ContentTabs` |
| `State` | `LoadingState`, `ErrorState`, `ErrorNotice`, `EmptyState`, `state-box`, `state-error` | `LoadingState`, `ErrorState`, `ErrorNotice`, `EmptyState`, `InlineState` |
| `DataTable` | `table-wrap`, `table`, все табличные реестры и покрытия | `RegistryTable`, `MaterialsTable`, `CoverageTable`, `ModelTable` |
| `Timeline` | `timeline`, `timeline-item`, карточки событий/версий/уведомлений/шагов | `Timeline`, `TimelineItem`, `ProcessStepItem`, `NotificationItem`, `RevisionItem` |
| `KeyValueList` | `KeyValueTable`, `dl-grid`, `dl-row`, ad hoc строки `<strong>Ключ:</strong> значение` | `KeyValueList`, `PassportList`, `MetadataList` |
| `List` | `compact-list`, списки подсказок, ответов, недостающих данных, агрегатов | `CompactList`, `Checklist`, `ReasonList` |
| `CodeBlock` | `diagnostic-box`, `code-block`, `pre-wrap` с JSON/diagnostics | `DiagnosticBlock`, `JsonBlock`, `PreformattedText` |
| `HtmlPreview` | `html-preview`, `rendered-html`, rendered HTML решения/протокола | `HtmlPreview`, `ArtifactPreview` |
| `Text` | `muted`, `small`, `mono`, `pre-wrap`, `preserve-lines` | `MutedText`, `SmallText`, `MonoText`, `PreWrapText` |
| `Layout` | `grid`, `grid-2`, `grid-3`, `grid-4`, `stack`, `compact`, `actions`, `between`, `two-col` | `Grid`, `Grid2`, `Grid4`, `Stack`, `InlineActions`, `SplitLayout` |

## 2. Группа `Card`

Единое имя: `Card`.

Оставить как отдельные варианты:

- `Card` - основная белая поверхность с optional title, subtitle, actions.
- `MetricCard` - компактная карточка метрики. Сейчас это `StatCard` и raw `<Card title="..."><strong>...</strong></Card>`.
- `FormCard` - карточки с формами: создание задачи, создание базы, источники, upload документа.
- `PreviewCard` - карточки rendered/preview-контента: веб-версия решения, веб-артефакт протокола, превью решения в рабочей области.
- `PassportCard` - карточки паспортов: решение, протокол, документ, процесс, база.
- `ListCard` - карточки, где основной контент timeline/list/table.

Что попадает в эту группу:

- Все использования `Card` из `shared/ui/components.tsx`.
- `StatCard` как будущий `MetricCard`, а не отдельная стилистическая сущность.
- KPI-карточки, написанные как raw `Card title="..."`.

Что не смешивать с `Card`:

- `section-box` лучше назвать `Panel`, потому что это вложенная поверхность внутри карточки.
- `state-box` лучше назвать `State`, потому что это состояние, а не обычная карточка.

## 3. Группа `Panel`

Единое имя: `Panel`.

Варианты:

- `SectionPanel` - обычный вложенный блок: TOGAF-секция, сущность, источник, фрагмент, извлеченный элемент.
- `EvidencePanel` - блок цитаты/основания в `KnowledgeDocumentPage`.
- `FormPanel` - форма уточнения внутри `ClarificationsCard`.
- `MetricPanel` - маленькая метрика внутри карточки процесса.
- `DebugPanel` - вложенный блок с техническими данными.

Текущие реализации:

- `section-box`.
- В отдельных местах raw `div className="state-box"` для summary-текста; для них лучше выбирать `InlineState`, если это сообщение состояния, или `SectionPanel`, если это обычная поверхность.

## 4. Группа `Badge`

Единое имя: `Badge`.

Варианты:

- `StatusBadge` - статусы задач, решений, протоколов, процессов, источников, версий.
- `SeverityBadge` - важность findings/audit events.
- `ActiveBadge` - выбранная/активная база или версия.
- `VersionBadge` - `KnowledgeVersionBadge`, сейчас это thin wrapper над `Badge`.

Текущие реализации:

- `Badge value={...}`.
- `KnowledgeVersionBadge`.
- CSS: `badge`, `badge-success`, `badge-warning`, `badge-danger`, `badge-neutral`.
- Текстовые статусы через `titleStatus(...)` без `Badge` лучше постепенно приводить к `StatusBadge`, если статус должен визуально считываться как состояние.

## 5. Группа `Banner`

Единое имя: `Banner`.

Варианты:

- `InfoBanner`.
- `WarningBanner`.
- `DangerBanner`.

Текущие реализации:

- `Banner tone="info"`.
- `Banner tone="warning"`.
- `Banner tone="danger"`.
- Raw alert в `OperationDetailsPage`: `<div className={\`banner ...\`}>`. Его стоит привести к `Banner`, чтобы не было второй реализации.

Не смешивать:

- `ErrorNotice` - это `State/Error`, а не `Banner`, потому что он показывает API-ошибку и payload.
- `EmptyState` - это пустое состояние, а не предупреждение.

## 6. Группа `Button`

Единое имя: `Button`.

Варианты:

- `Button` - secondary/default.
- `PrimaryButton` - `primary` или `button button-primary`.
- `LinkButton` - внутренний `Link` с `className="button"`.
- `ExternalLinkButton` - внешний `a` с `className="button"`.
- `TabButton` - кнопка внутри `tab-strip`.
- `DangerButton` - пока отсутствует, но нужен для удаления документа, если будет усиливаться семантика.

Текущие реализации:

- Компонент `Button`.
- `Link className="button"`.
- `Link className="button button-primary"`.
- `a className="button"`.
- Raw `<button className={\`button ...\`}>` в tab strip.

Рекомендация для следующего шага:

- Вынести `LinkButton` и `TabButton`, чтобы табы и навигационные действия не писались raw-классами.

## 7. Группа `FormField`

Единое имя: `FormField`.

Варианты:

- `TextField` - `Input` с обычным текстом.
- `DateField` - `Input type="date"`.
- `FileField` - `Input type="file"`.
- `TextareaField` - `Textarea`.
- `SelectField` - `Select`.
- `FieldRow` - текущий `FormRow`.

Текущие реализации:

- `FormRow`.
- `Input`.
- `Textarea`.
- `Select`.
- Raw `option` внутри `Select`.

Рекомендация:

- Переименовывать `FormRow` не обязательно сразу; можно считать `FormRow` канонической оболочкой поля, а `FormField` - названием группы.

## 8. Группа `State`

Единое имя: `State`.

Варианты:

- `LoadingState`.
- `ErrorState`.
- `ErrorNotice`.
- `EmptyState`.
- `InlineState` - обычный `state-box` для summary/готовности/сообщения.
- `StateError` - CSS-вариант `state-error`.

Текущие реализации:

- Компоненты `LoadingState`, `ErrorState`, `ErrorNotice`, `EmptyState`.
- Raw `div className="state-box"` в задачах, решениях, протоколах, документах и процессах.
- `state-error` внутри error-компонентов.

Что унифицировать дальше:

- Добавить общий `StateBox` или `InlineState`, чтобы raw `state-box` не расползался по страницам.

## 9. Группа `DataTable`

Единое имя: `DataTable`.

Варианты:

- `RegistryTable` - таблицы задач/решений/проверок.
- `MaterialsTable` - использованные материалы, материалы проверки.
- `CoverageTable` - покрытие разделов.
- `ModelTable` - сущности и связи архитектурной модели.
- `SourcesTable` - сейчас чаще timeline, но табличная семантика может понадобиться.

Текущие реализации:

- `div.table-wrap`.
- `table.table`.
- Повторяющиеся `thead`/`tbody` вручную в страницах.

Рекомендация:

- Пока оставить таблицы в страницах, но считать `DataTable` единым паттерном: обертка `table-wrap`, таблица `table`, hover rows, uppercase header.

## 10. Группа `Timeline`

Единое имя: `Timeline`.

Варианты:

- `TimelineItem` - базовая единица.
- `TaskTimelineItem`.
- `SolutionTimelineItem`.
- `ProtocolTimelineItem`.
- `KnowledgeBaseTimelineItem`.
- `SourceTimelineItem`.
- `VersionTimelineItem`.
- `OperationTimelineItem`.
- `AuditEventTimelineItem`.
- `FindingTimelineItem`.
- `RevisionTimelineItem`.

Текущие реализации:

- `div.timeline`.
- `div.timeline-item`.
- Повторяющиеся шапки `actions between` + `strong` + `Badge`.

Рекомендация:

- Вынести минимум `Timeline` и `TimelineItem` с props `title`, `meta`, `badge`, `actions`, чтобы сохранить доменную гибкость.

## 11. Группа `Tabs` и `Toolbar`

Единое имя для вкладок: `Tabs`.

Варианты:

- `ContentTabs` - вкладки решения и реестра.
- `ViewModeTabs` - режимы читать/проверить/дебаг.

Текущие реализации:

- `tab-strip`.
- Raw `button className="button ..."` в `RegistryPage`, `SolutionPage`, `KnowledgeDocumentPage`, `OperationDetailsPage`.

Единое имя для фильтров/панелей действий: `Toolbar`.

Варианты:

- `FilterToolbar` - фильтры реестра, журнала, протокола.
- `LoadMoreToolbar` - счетчик загруженного + кнопка "Показать еще".
- `CardActions` - actions в заголовке `Card`.

Текущие реализации:

- `toolbar-grid`, `toolbar-grid-4`.
- `actions`.
- `actions end-span`.

## 12. Группа `CodeBlock` и `HtmlPreview`

Единое имя для технических блоков: `CodeBlock`.

Варианты:

- `DiagnosticBlock` - темный блок JSON/diagnostics.
- `JsonBlock` - JSON payload.
- `PreformattedText` - текст с сохранением переносов.

Текущие реализации:

- `diagnostic-box`.
- `pre-wrap`.
- `preserve-lines`.
- CSS `code-block`, сейчас не используется в JSX.

Единое имя для rendered HTML: `HtmlPreview`.

Варианты:

- `HtmlPreview`.
- `ArtifactPreview`.

Текущие реализации:

- `html-preview`.
- CSS `rendered-html`, сейчас не используется в JSX.

Рекомендация:

- Оставить `html-preview` как единственную реализацию, `rendered-html` удалить или переименовать после проверки.

## 13. Группа `Text`

Единое имя: `Text`.

Варианты:

- `MutedText` - `muted`.
- `SmallText` - `small`.
- `MonoText` - `mono`.
- `PreWrapText` - `pre-wrap`.
- `PreserveLinesText` - `preserve-lines`.

Текущие реализации:

- CSS utility-классы `muted`, `small`, `mono`, `pre-wrap`, `preserve-lines`.

Рекомендация:

- Не обязательно выносить в React-компоненты. Это нормальные utility-классы, но в документации и дизайне их стоит считать единой группой текстовых атомов.

## 14. Страницы через канонические группы

| Страница | Основные группы |
| --- | --- |
| `DashboardPage` | `PageHeader`, `Banner`, `Card`, `MetricCard`, `Timeline`, `Badge`, `Button`, `State` |
| `NewTaskPage` | `PageHeader`, `Card`, `Banner`, `FormField`, `Button`, `List`, `State` |
| `RegistryPage` | `PageHeader`, `Banner`, `MetricCard`, `Card`, `Tabs`, `Toolbar`, `FormField`, `DataTable`, `Badge`, `Button`, `State` |
| `TaskWorkspacePage` | `PageHeader`, `Banner`, `Card`, `FormField`, `Timeline`, `Panel`, `Button`, `State`, `HtmlPreview` |
| `SolutionPage` | `PageHeader`, `Card`, `MetricCard`, `Tabs`, `Badge`, `Button`, `HtmlPreview`, `DataTable`, `Timeline`, `CodeBlock`, `Panel` |
| `ProtocolPage` | `PageHeader`, `Banner`, `MetricCard`, `Card`, `FormField`, `Toolbar`, `DataTable`, `Timeline`, `Panel`, `CodeBlock`, `HtmlPreview`, `Badge` |
| `KnowledgePage` | `PageHeader`, `Banner`, `MetricCard`, `Card`, `FormField`, `Button`, `Timeline`, `Badge`, `State` |
| `KnowledgeBaseDetailsPage` | `PageHeader`, `Banner`, `MetricCard`, `Card`, `FormField`, `Timeline`, `Badge`, `Button`, `State` |
| `KnowledgeDocumentPage` | `PageHeader`, `Card`, `Tabs`, `Banner`, `FormField`, `Panel`, `CodeBlock`, `State`, `Button`, `Text` |
| `OperationsPage` | `PageHeader`, `Banner`, `MetricCard`, `Card`, `Toolbar`, `FormField`, `Timeline`, `Badge`, `Button`, `State` |
| `OperationDetailsPage` | `PageHeader`, `Card`, `Tabs`, `Banner`, `KeyValueList`, `Timeline`, `MetricPanel`, `CodeBlock`, `Badge`, `Button`, `State` |

## 15. Первые кандидаты на рефакторинг

Минимальный безопасный порядок:

1. `LinkButton` - заменить повторяющийся `Link className="button"` и `a className="button"`.
2. `StateBox` или `InlineState` - заменить raw `div className="state-box"`.
3. `Tabs`/`TabButton` - заменить повторяющиеся `tab-strip` + raw `button`.
4. `Timeline`/`TimelineItem` - унифицировать повторяющийся паттерн `actions between` + title + badge + meta.
5. `DataTable` - оставить таблицы доменными, но вынести общую обертку и базовую структуру.
6. `Panel` - заменить raw `section-box`, если нужно централизованно править внутренние поверхности.

Не трогать на первом шаге:

- `Card`, `Badge`, `Button`, `Input`, `Textarea`, `Select`, `FormRow`, `Banner`, `LoadingState`, `ErrorState`, `ErrorNotice`, `EmptyState`, `StatCard`, `KeyValueTable`: они уже существуют как shared UI.
- Доменные компоненты вроде `SolutionContentTab`, `KnowledgeScopeSelector`, `TaskSummarySection`: они должны оставаться доменными контейнерами, а не превращаться в дизайн-системные атомы.

