# Shadcn-маппинг компонентов фронтенда

Источник локального анализа: `docs/frontend-component-inventory.md`, `docs/frontend-component-style-groups.md`, `frontend/src`.

Источник shadcn/ui: официальный список компонентов shadcn/ui и страницы компонентов `Card`, `Badge`, `Button`, `Alert`, `Field`, `Input`, `Textarea`, `Select`, `Native Select`, `Table`, `Tabs`, `Empty`, `Skeleton`, `Sidebar`, `Typography`.

Цель: зафиксировать, какой единый shadcn-компонент или shadcn-композиция должен стать стилевой основой для каждого текущего компонента/паттерна в коде. Код на этом шаге не меняется.

## 1. Канонические группы -> shadcn/ui

| Группа в проекте | Единая shadcn-основа | Комментарий |
| --- | --- | --- |
| `AppShell` | `Sidebar` + `Navigation Menu` или `Button asChild` для ссылок | Текущий `sidebar/nav-list/nav-item` лучше вести к `Sidebar`, а простые ссылки внутри - к `Button` variant `ghost`/`secondary` через `asChild`. |
| `PageHeader` | `Typography` + `Button Group` | У shadcn нет отдельного page header. Это композиция из `h1`, description text и группы actions. |
| `Card` | `Card`, `CardHeader`, `CardTitle`, `CardDescription`, `CardAction`, `CardContent`, `CardFooter` | Все большие белые поверхности должны идти через один `Card`. |
| `MetricCard` | `Card size="sm"` + `CardHeader/CardContent` | Текущий `StatCard` и KPI-карточки становятся компактным вариантом `Card`. |
| `Panel` | `Card size="sm"` или `Item` | Для `section-box`: если блок самостоятельный - `Card size="sm"`, если строка/элемент списка - `Item`. |
| `Badge` | `Badge` | Статусы, severity, active/version бейджи. |
| `Banner` | `Alert`, `AlertTitle`, `AlertDescription`, `AlertAction` | `Banner` и raw `div.banner` в `OperationDetailsPage` должны стать `Alert`. |
| `Button` | `Button` + `Button Group` | Обычные кнопки, link-button через `Button asChild`, action-группы через `ButtonGroup`. |
| `Tabs` | `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent` | Все `tab-strip` и режимы просмотра. |
| `Toolbar` | `FieldGroup` + `ButtonGroup` + `InputGroup` | Фильтры/поиск/actions. Если это только действия - `ButtonGroup`. |
| `FormField` | `Field`, `FieldLabel`, `FieldDescription`, `FieldError`, `FieldGroup` | Оболочка для форм вместо текущего `FormRow`. |
| `Input` | `Input` | Text/date/file inputs. Для сложных полей - `InputGroup`. |
| `Textarea` | `Textarea` | Многострочный ввод. |
| `Select` | `Native Select` на первом этапе; `Select` для custom dropdown | Сейчас в коде обычный `<select>`, поэтому ближе `NativeSelect`. |
| `Checkbox` | `Checkbox` + `Field` | CSS `checkbox-row` сейчас не используется, но если понадобится - вести к shadcn `Checkbox`. |
| `State.Loading` | `Skeleton` или `Spinner` | Для полной загрузки страницы можно `Spinner`; для карточек/таблиц лучше `Skeleton`. |
| `State.Empty` | `Empty`, `EmptyHeader`, `EmptyTitle`, `EmptyDescription`, `EmptyContent` | Текущий `EmptyState`. |
| `State.Error` | `Alert variant="destructive"` | Текущие `ErrorState` и `ErrorNotice`. |
| `InlineState` | `Alert` или `Card size="sm"` | `state-box` как сообщение - `Alert`; как нейтральный текстовый контейнер - `Card size="sm"`. |
| `DataTable` | `Table`, `TableHeader`, `TableBody`, `TableRow`, `TableHead`, `TableCell`, `TableCaption` | Все таблицы проекта. Для сортировки/пагинации позже можно `Data Table`. |
| `Timeline` | `Item` + `Badge` + `Separator`; при списках - `Card` | У shadcn нет отдельного timeline. Единая композиция: `Item` как строка события, `Separator` для визуального деления. |
| `KeyValueList` | `Table` или `Item` | Для паспортов лучше `Item`/definition-like composition; для плотных списков можно `Table`. |
| `List` | `Item` или обычный `ul` с Typography | Если пункты интерактивные/карточные - `Item`; если текстовые - оставить `ul` под Typography. |
| `CodeBlock` | `Kbd` только для inline keys; для JSON оставить custom `pre` в `Card` | В shadcn нет полноценного code block. Диагностические JSON-блоки остаются custom, но оборачиваются в `Card`/`ScrollArea`. |
| `HtmlPreview` | `Card` + `ScrollArea` | Rendered HTML остается custom-контейнером внутри shadcn `Card`. |
| `Text` | `Typography` | Заголовки, muted/description, mono text. Mono/id можно оставить utility-классом. |
| `Layout` | `Resizable`, `Scroll Area`, `Separator` + Tailwind utilities | Grid/stack/actions обычно остаются layout utilities; `two-col` при необходимости можно вести к `Resizable`. |

## 2. Shared UI компоненты -> shadcn/ui

| Компонент в коде | Сейчас | Shadcn-цель |
| --- | --- | --- |
| `PageHeader` | `div.page-header`, `h1`, subtitle, actions | `Typography` для title/subtitle + `ButtonGroup` для actions. Оставить как project wrapper `PageHeader`. |
| `Card` | `section.card`, custom `card-header` | shadcn `Card` + `CardHeader` + `CardTitle` + `CardDescription` + `CardAction` + `CardContent`. |
| `Badge` | `span.badge badge-*` | shadcn `Badge`; project wrapper может маппить `tone(value)` в `variant`. |
| `Button` | `button.button`, `button-primary` | shadcn `Button`; primary -> default, secondary -> outline/secondary. |
| `Input` | `input.input` | shadcn `Input`. |
| `Textarea` | `textarea.textarea` | shadcn `Textarea`. |
| `Select` | native `<select className="input">` | shadcn `NativeSelect` на первом этапе. Если нужен rich dropdown - shadcn `Select`. |
| `FormRow` | `label.form-row`, label, hint | shadcn `Field` + `FieldLabel` + `FieldDescription`; ошибки через `FieldError`. |
| `LoadingState` | `state-box` с текстом | shadcn `Spinner` для page-level или `Skeleton` для card/table-level. |
| `ErrorState` | `state-box state-error` | shadcn `Alert` destructive + `AlertTitle` + `AlertDescription`. |
| `ErrorNotice` | API-aware `state-box state-error` | project wrapper над shadcn `Alert` destructive, сохраняет вывод `error_code`, `request_id`, `operation_id`. |
| `EmptyState` | `state-box` | shadcn `Empty` + `EmptyHeader` + `EmptyTitle` + `EmptyDescription` + `EmptyContent`. |
| `Banner` | `div.banner banner-tone` | shadcn `Alert`; tone info/warning/danger -> custom variants/classes, danger -> destructive. |
| `StatCard` | `div.card compact-card` | shadcn `Card size="sm"`; лучше переименовать концептуально в `MetricCard`. |
| `KeyValueTable` | `dl.dl-grid` | project wrapper над shadcn `Item` или `Table`; для текущих паспортов предпочтительно `Item`/`ItemContent`. |

## 3. App/layout компоненты -> shadcn/ui

| Компонент в коде | Shadcn-цель |
| --- | --- |
| `App` | UI shadcn не требуется; это composition root. |
| `AppProviders` | UI shadcn не требуется; провайдеры React Query и router. |
| `AppRoutes` | UI shadcn не требуется; routing layer. |
| `AppLayout` | shadcn `Sidebar` + `SidebarHeader`/`SidebarContent` + `SidebarMenu` + `SidebarMenuItem`; текущие `NavLink` можно стилизовать через `Button asChild` или sidebar menu button. |
| `navClassName` | Заменить логикой active state внутри `SidebarMenuButton`/`Button` variant, не отдельный UI-компонент. |
| `createAppQueryClient` | UI shadcn не требуется. |

## 4. Entity/feature компоненты -> shadcn/ui

| Компонент в коде | Shadcn-цель |
| --- | --- |
| `KnowledgeScopeSelector` | `Card` с `Field`, `NativeSelect`, `Alert`, `Badge`, `Button`. Сам компонент остается доменным контейнером. |
| `KnowledgeScopeSummary` | `Card` + вложенные `Card size="sm"` или `Item` для mandatory/user version + `Badge` при статусах. |
| `KnowledgeVersionBadge` | Убрать как отдельную стилистическую сущность или оставить thin wrapper над shadcn `Badge`. |
| `TaskSummarySection` | `Card`, `Alert`, `Badge`, `Button`, `Button asChild`, `Item` для строк метаданных. |
| `ClarificationsCard` | `Card`, `Empty`, `Alert`, `Field`, `Textarea`, `Button`; form panel -> `Card size="sm"` или `Item`. |
| `DraftEditorCard` | `Card`, `Field`, `Input`, `Textarea`, `Alert`, `ButtonGroup`, `Button`. |
| `ClarificationHistoryCard` | `Card`, `Item`, `Badge`, `Separator`, `Typography`. |
| `SolutionAndProtocolSection` | `Card`, `Alert`, `Button asChild`, `ScrollArea` для `HtmlPreview`, `Item` для findings. |
| `FindingsGroup` | `Card` или `Item` group, `Badge`, `Button asChild`, `Separator`. |
| `SolutionHeaderCards` | `Card`, `Badge`, `Button`, `Button asChild`, `ButtonGroup`, `MetricCard` на `Card size="sm"`. |
| `SolutionContentTab` | `Card`, `Alert`, `ScrollArea` для HTML, `Badge`, `Item`/`Card size="sm"` для секций и архитектурных объектов, `List`. |
| `SolutionBasisTab` | `Card`, `Table`, `Empty`, `ScrollArea`/custom `CodeBlock` для JSON, `Item` для guidance. |
| `SolutionModelTab` | `MetricCard`, `Card`, `Table`, `Empty`, `Badge`, `Item`, custom `CodeBlock`. |
| `SolutionHistoryTab` | `Card`, `Empty`, `Item`, `Badge`, `Button asChild`, `Separator`. |

## 5. Page-level компоненты -> shadcn/ui

| Страница | Shadcn-цель |
| --- | --- |
| `DashboardPage` | `PageHeader` composition, `Alert`, `MetricCard`, `Card`, `Item` timeline, `Badge`, `Button asChild`, `Empty`, `Skeleton`/`Spinner`. |
| `NewTaskPage` | `PageHeader`, `Card`, `Alert`, `Field`, `Input`, `Textarea`, `Button`, `ButtonGroup`, `List`, `Empty` где нужно. |
| `RegistryPage` | `PageHeader`, `Alert`, `MetricCard`, `Card`, `Tabs`, `FieldGroup`, `Input`, `NativeSelect`, `Button`, `Table`, `Empty`, `Skeleton`. |
| `TaskWorkspacePage` | `PageHeader`, `Alert`, `Card`, `Field`, `Button`, `Item`, `Empty`, `ScrollArea` для preview. |
| `SolutionPage` | `PageHeader`, `Alert`, `Tabs`, `Card`, `MetricCard`, `Badge`, `Table`, `Item`, `ScrollArea`, custom `CodeBlock`. |
| `ProtocolPage` | `PageHeader`, `Alert`, `MetricCard`, `Card`, `FieldGroup`, `Input`, `NativeSelect`, `Table`, `Item`, `Badge`, `Empty`, `ScrollArea`, custom `CodeBlock`. |
| `KnowledgePage` | `PageHeader`, `Alert`, `MetricCard`, `Card`, `Field`, `Input`, `Button`, `Item`, `Badge`, `Empty`, `Skeleton`. |
| `KnowledgeBaseDetailsPage` | `PageHeader`, `Alert`, `MetricCard`, `Card`, `Field`, `Input`, `NativeSelect`, `Button`, `Item`, `Badge`, `Empty`, `Skeleton`. |
| `KnowledgeDocumentPage` | `PageHeader`, `Tabs`, `Card`, `Alert`, `FieldGroup`, `NativeSelect`, `Button`, `Item`, `Badge`, `ScrollArea`, custom `CodeBlock`, `Empty`, `Skeleton`. |
| `OperationsPage` | `PageHeader`, `Alert`, `MetricCard`, `Card`, `FieldGroup`, `NativeSelect`, `Input`, `Button`, `Item`, `Badge`, `Empty`, `Skeleton`. |
| `OperationDetailsPage` | `PageHeader`, `Tabs`, `Alert`, `Card`, `Item`/`KeyValueList`, `Badge`, `Button asChild`, `Separator`, `MetricCard`, `ScrollArea`, custom `CodeBlock`, `Empty`, `Skeleton`. |

## 6. CSS/pattern компоненты -> shadcn/ui

| Текущий CSS/pattern | Shadcn-цель |
| --- | --- |
| `app-shell`, `sidebar`, `brand`, `nav-list`, `nav-item`, `main-shell` | shadcn `Sidebar` family. |
| `page`, `page-header` | Project layout + shadcn `Typography`/`ButtonGroup`. |
| `card`, `card-header`, `compact-card` | shadcn `Card` family. |
| `badge`, `badge-*` | shadcn `Badge`. |
| `banner`, `banner-*` | shadcn `Alert`. |
| `button`, `button-primary`, `link-button` | shadcn `Button`; groups -> `ButtonGroup`. |
| `input` | shadcn `Input`; native select -> `NativeSelect`. |
| `textarea` | shadcn `Textarea`. |
| `form-row`, `form-label` | shadcn `Field`, `FieldLabel`, `FieldDescription`, `FieldError`. |
| `state-box`, `state-error` | shadcn `Alert`/`Empty`/`Skeleton` depending on state. |
| `table-wrap`, `table` | shadcn `Table`; wrapper can use `ScrollArea`. |
| `timeline`, `timeline-item` | shadcn `Item` + `Separator` + `Badge`; keep as project `Timeline` wrapper if needed. |
| `section-box` | shadcn `Card size="sm"` or `Item`, depending on density. |
| `dl-grid`, `dl-row` | shadcn `Item` or `Table`; keep `KeyValueList` wrapper. |
| `toolbar-grid`, `toolbar-grid-4` | shadcn `FieldGroup`, `ButtonGroup`, `InputGroup`. |
| `tab-strip` | shadcn `TabsList` + `TabsTrigger`. |
| `diagnostic-box`, `code-block` | custom `pre` in `Card`/`ScrollArea`; shadcn has no direct code block equivalent. |
| `html-preview`, `rendered-html` | custom preview in shadcn `Card` + `ScrollArea`. |
| `grid`, `grid-2`, `grid-3`, `grid-4`, `stack`, `compact`, `actions`, `between`, `two-col` | Tailwind layout utilities; shadcn не заменяет layout полностью. |
| `muted`, `small`, `mono`, `pre-wrap`, `preserve-lines` | shadcn `Typography` conventions + utility classes. |
| `checkbox-row` | shadcn `Checkbox` + `Field`, если вернется в JSX. |
| `list-button` | shadcn `Button` variant `ghost`/`outline` или `Item` с action. |
| `compare-grid` | layout utility; при интерактивном resize - shadcn `Resizable`. |
| `timeline-item-selected` | `Item` selected state через `data-state`/custom class. |
| `inline-code-list` | `Kbd` для inline code-like tokens или `Badge` для тегов. |
| `uri-wrap` | utility class поверх `Typography`/`MonoText`. |
| `topbar` | Если понадобится снова - `Card`/`Toolbar` composition, не отдельный shadcn компонент. |

## 7. Рекомендуемый набор shadcn add-компонентов для будущего рефакторинга

Минимальный набор:

- `button`
- `button-group`
- `card`
- `badge`
- `alert`
- `field`
- `input`
- `textarea`
- `native-select`
- `table`
- `tabs`
- `empty`
- `skeleton`
- `spinner`
- `separator`
- `scroll-area`
- `sidebar`
- `item`
- `typography`

Опционально позже:

- `select` - если понадобится custom dropdown вместо native select.
- `input-group` - если поля поиска/фильтры станут составными.
- `checkbox` - если вернутся checkbox-строки.
- `tooltip` - для сокращенных id, статусов и technical hints.
- `alert-dialog` - для подтверждений удаления/активации вместо `window.confirm`.
- `dropdown-menu` - для action-menu в таблицах.
- `resizable` - для двухколоночного debug/read layout.
- `sonner` - для toast-уведомлений вместо inline success banners, если появится такой UX.

## 8. Правило для дальнейшей унификации

- Доменные компоненты остаются доменными: `KnowledgeScopeSelector`, `SolutionContentTab`, `TaskSummarySection` и т.п. не переименовывать в shadcn.
- Стилистическая основа внутри них должна собираться из shadcn: `Card`, `Alert`, `Badge`, `Button`, `Field`, `Table`, `Tabs`, `Empty`, `Skeleton`, `Item`.
- Если прямого shadcn-аналога нет (`Timeline`, `CodeBlock`, `HtmlPreview`, `PageHeader`), оставить project wrapper, но строить его на ближайшей shadcn-композиции.
- Для текущего native `<select>` использовать `NativeSelect`, а не `Select`, чтобы не переписать поведение форм слишком сильно.
- Для `Link` и внешнего `a` использовать `Button asChild`, чтобы не держать отдельные CSS-классы `.button` на ссылках.

## 9. Официальные ссылки shadcn/ui

- Components index: https://ui.shadcn.com/docs/components
- Card: https://ui.shadcn.com/docs/components/card
- Button: https://ui.shadcn.com/docs/components/button
- Alert: https://ui.shadcn.com/docs/components/alert
- Sidebar: https://ui.shadcn.com/docs/components/sidebar
- Table: https://ui.shadcn.com/docs/components/table
- Tabs: https://ui.shadcn.com/docs/components/tabs
- Badge: https://ui.shadcn.com/docs/components/badge
- Field: https://ui.shadcn.com/docs/components/field
- Input: https://ui.shadcn.com/docs/components/input
- Textarea: https://ui.shadcn.com/docs/components/textarea
- Native Select: https://ui.shadcn.com/docs/components/native-select
- Empty: https://ui.shadcn.com/docs/components/empty
- Skeleton: https://ui.shadcn.com/docs/components/skeleton
- Spinner: https://ui.shadcn.com/docs/components/spinner
- Item: https://ui.shadcn.com/docs/components/item
- Button Group: https://ui.shadcn.com/docs/components/button-group
- Input Group: https://ui.shadcn.com/docs/components/input-group
- Scroll Area: https://ui.shadcn.com/docs/components/scroll-area
- Separator: https://ui.shadcn.com/docs/components/separator
- Typography: https://ui.shadcn.com/docs/components/typography
