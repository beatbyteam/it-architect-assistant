# 💡Помощник ИТ-архитектора


**Помощник ИТ‑архитектора** — сервис для автоматического формирования ИТ‑архитектуры решения по текстовой бизнес‑задаче и последующей проверки этого решения на соответствие корпоративной архитектуре, стандартам и нормативной базе.

[![MVP](https://img.shields.io/badge/status-MVP-yellow)](LICENSE) [![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com/) [![React](https://img.shields.io/badge/React-18.3-cyan)](https://react.dev/) [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue)](https://www.postgresql.org/) [![Ollama](https://img.shields.io/badge/Ollama-LLM-orange)](https://ollama.com/)

![Сайт](IT_ARCH.png)

## 📋 Оглавление
- [✨ Основные возможности](#-основные-возможности)
- [📋 Способы запуска](#-способы-запуска)
- [🛠️Технологический стек](#-технологический-стек)
-  [⚙️ Конфигурация](#️-конфигурация)
- [🚨 Частые ошибки и решения](#-частые-ошибки-и-решения)
- [📁 Структура проекта](#-структура-проекта)
- [📚 Документация](#-документация)

## ✨ Основные возможности

- 📝 **Приём бизнес‑задачи** на естественном языке 
- 🔁 **Контролируемый цикл уточнений** при недостатке данных 
- 🤖 **Генерация проекта ИТ‑архитектуры решения** на основе активной базы знаний 
- 🧠 **Локальный LLM** — не требуется облачных сервисов 
- 🐳 **Docker Compose** — простое развертывание

## 📋 Способы запуска
- [Автоматический запуск (рекомендуемый)](#-автоматический-запуск-рекомендуемый)
- [Ручной запуск (Docker Compose)](#-ручной-запуск-docker-compose)

Требования:
*- Docker Desktop или Docker Engine с Docker Compose plugin*
*- Свободное место в Docker под Docker-образы, PostgreSQL, Redis и модели Ollama*
*- Для обновления проекта наличие Git*

## 🤖 Автоматический запуск (рекомендуемый)
### 🪟 Windows (PowerShell)
#### ⚠️ Первый запуск: отключение блокировки скриптов
По умолчанию выполнение скриптов заблокировано. Для однократной разблокировки ввести в PowerShell:
```
# Разблокировать конкретный скрипт
Unblock-File .\deploy\scripts\local_release_up.ps1
Unblock-File .\deploy\scripts\local_release_update.ps1
Unblock-File .\deploy\scripts\local_release_down.ps1
```
Переход в директорию проекта

```
cd C:\путь\к\проекту\it-architect-assistant
```
Запуск проекта
```
Запустить Docker

# Первый запуск
.\deploy\scripts\local_release_up.ps1

# Быстрый перезапуск без загрузки моделей
.\deploy\scripts\local_release_up.ps1 -SkipModelPull
```

Обновление проекта
```
# Требуется Git — скачивает последние изменения и пересобирает стек
.\deploy\scripts\local_release_update.ps1
```

Остановка проекта
```
.\deploy\scripts\local_release_down.ps1
```
### 🐧 Linux / macOS
Переход в директорию проекта

```
# Переход в директорию проекта
cd /путь/к/проекту/it-architect-assistant
```
Запуск проекта
```
# Первый запуск
sh deploy/scripts/local_release_up.sh

# Быстрый перезапуск
sh deploy/scripts/local_release_up.sh --skip-model-pull
```

Обновление проекта
```
# Обновление (требуется Git)
sh deploy/scripts/local_release_update.sh
```

Остановка проекта
```
# Остановка
sh deploy/scripts/local_release_down.sh
```

## 🐳 Ручной запуск (Docker Compose)


> Для опытных пользователей, желающих больше контроля над процессом.

### 📝 Подготовка
```
# 1. Копирование файла конфигурации
cp deploy/local-production.env.example .env.local
```
### ▶️ Запуск стека
```
# 1. Копирование файла конфигурации
cp deploy/local-production.env.example .env.local
```
### 📊 Проверка статуса
```
# 1. Копирование файла конфигурации
cp deploy/local-production.env.example .env.local
```
### 📜 Просмотр логов
```
# Все логи
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs -f
# Логи конкретного сервиса
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs backend -f
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs frontend -f
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs ollama -f
```
### 🧹 Полная очистка (с удалением томов)
```
docker compose --env-file .env.local -f deploy/compose.local-production.yml down
```
### 🤖 Ручная загрузка моделей Ollama
```
docker compose --env-file .env.local -f deploy/compose.local-production.yml exec ollama ollama pull qwen2.5:7b-instruct
docker compose --env-file .env.local -f deploy/compose.local-production.yml exec ollama ollama pull bge-m3
```
### [ОТКРЫТЬ ПРИЛОЖЕНИЕ - http://localhost:8080](http://localhost:8080)

## 🛠️ Технологический стек
 **- Backend -**
*FastAPI + SQLAlchemy + Alembic  
PostgreSQL + pgvector (векторный поиск)  
Celery + Redis (фоновые задачи)*

**- Frontend -**
*Vite + React + TypeScript  
TanStack Query (управление состоянием)*

 **- Infrastructure -**
*Docker Compose + Nginx Gateway  
Ollama (локальный LLM runtime)*

## ⚙️Конфигурация
### Файлы конфигурации
`deploy/local-production.env.example` - Шаблон для production-запуска
`.env.local` - Локальная конфигурация
`.env.example` - Шаблон для разработки

### Модели по умолчанию
`qwen2.5:7b-instruct` - Генерация текста и проверка решений
`bge-m3` - Векторный поиск

### Параметры окружения
```
# Режим приложения
APP_ENV=local                 # local / test / production
DEBUG=false                   # Режим отладки

# Аутентификация
AUTH_MODE=local_noauth        # Только для local/test окружений

# База данных
DATABASE_URL=postgresql://...

# Модели Ollama
GENERATION_MODEL=qwen2.5:7b-instruct
EMBEDDING_MODEL=bge-m3
```
⚠️ `AUTH_MODE=local_noauth` разрешён только для `APP_ENV=local` и `APP_ENV=test`
Для настоящего общего production-сервера используется отдельный профиль: SSO/reverse proxy, `APP_ENV=production`, строгие CORS origins.

## 🧯 Частые ошибки и решения

В этом разделе собраны наиболее частые проблемы при локальном запуске проекта и способы их решения.

### Быстрая навигация

- [Ошибка загрузки моделей Ollama](#ошибка-загрузки-моделей-ollama)
- [Контейнер не запускается после изменения `.env.local`](#контейнер-не-запускается-после-изменения-envlocal)
- [Нужно пересобрать только один сервис](#нужно-пересобрать-только-один-сервис)
- [Нужно полностью удалить локальное окружение проекта](#нужно-полностью-удалить-локальное-окружение-проекта)
- [Порт уже занят](#порт-уже-занят)
- [Backend не может подключиться к базе данных](#backend-не-может-подключиться-к-базе-данных)

---

### Ошибки загрузки моделей Ollama 

**Признак:**

```text
Error: max retries exceeded
read: connection reset by peer
```

**Причина:**

Обычно ошибка возникает из-за обрыва соединения при загрузке модели Ollama.
Возможные причины: нестабильное интернет-соеднинение, VPN, proxy или корпоративная сеть.

**Решение 1: дозагрузить модели вручную**

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml exec ollama ollama pull qwen2.5:7b-instruct
docker compose --env-file .env.local -f deploy/compose.local-production.yml exec ollama ollama pull bge-m3
```

После успешной загрузки моделей можно запустить проект без повторного скачивания моделей. 

Windows:
```powershell
.\deploy\scripts\local_release_up.ps1 -SkipModelPull
```

Linux/MacOS:
```bash
sh deploy/scripts/local_release_up.sh --skip-model-pull
```

**Решение 2: изменить подключение к сети**

Если ошибка повторяется: 

- Отключить VPN / proxy / подключение к корпоративной сети.
- Переподключиться с другому источнику интернета, например, раздать интернет с телефона. 
- Заново запустить скрипт запуска проекта 

---

### Контейнер не запускается после изменения `env.local`

**Признак:**

Изменения в `.env.local` не применяются, сервис продолжает работать со старыми настройками.

**Решение:**

Перезапустите нужные сервисы:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml restart backend celery
```

Если нужно полностью пересоздать контейнеры:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml up -d --force-recreate backend celery
```

Проверить переменные окружения внутри контейнера:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml exec backend printenv
```

---

### Нужно пересобрать только один сервис

**Признак:**

Был изменён код backend/frontend/celery, но не нужно перезапускать весь проект.

**Решение:**

Например, для `backend`:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml up -d --build --no-deps backend
```

Для `frontend`:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml up -d --build --no-deps frontend
```

Для `celery`:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml up -d --build --no-deps celery
```

Команда пересобирает и перезапускает только указанный сервис, не затрагивая остальные контейнеры проекта.

---

### Нужно полностью удалить локальное окружение проекта

**Признак:**

Нужно удалить контейнеры, сети, тома и локально собранные образы только этого проекта.

**Решение 1:**

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml down --volumes --rmi local --remove-orphans
```

Эта команда удаляет ресурсы, созданные данным Docker Compose проектом, и не затрагивает контейнеры других проектов.

Если также нужно удалить скачанные образы, связанные с compose-файлом:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml down --volumes --rmi all --remove-orphans
```

Используйте `--rmi all` осторожно, если другие проекты используют те же Docker images.

**Решение 2:**

Удалить нужные контейнеры, сети, тома и локально собранные образы вручную 
через Docker Desktop или Docker Engine с Docker Compose plugin.

---

### Порт уже занят

**Признак:**

```text
Bind for 0.0.0.0:PORT failed: port is already allocated
```

или:

```text
address already in use
```

**Причина:**

На нужном порту уже запущен другой процесс или контейнер.

**Решение:**

Посмотреть запущенные контейнеры:

```bash
docker ps
```

Остановить контейнер, который занимает порт:

```bash
docker stop <container_name_or_id>
```

Либо изменить порт в `.env.local` или compose-файле, если проект поддерживает настройку портов через переменные окружения.

---

### Backend не может подключиться к базе данных

**Признак:**

```text
connection refused
could not connect to server
database is not ready
```

**Причина:**

PostgreSQL ещё не успел запуститься или контейнер базы данных работает некорректно.

**Решение:**

Проверить статус контейнеров:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml ps
```

Посмотреть логи базы данных:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs postgres
```

Перезапустить backend после запуска базы:

```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml restart backend
```

---

### ⚠️ Ошибка сборки Docker-образа

При запуске проекта может возникнуть ошибка вида:

```text
target api: failed to solve: image "docker.io/library/it-arch-assistant-backend:local": already exists
```

Обычно ошибка означает, что локальный Docker-образ приложения уже существует и мешает повторной сборке.

#### Решение: удалить старый образ и запустить проект заново

```bash
docker rmi it-arch-assistant-backend:local
```

После этого повторно запустите проект.

Windows:

```powershell
.\deploy\scripts\local_release_up.ps1
```

Linux / macOS:

```bash
sh deploy/scripts/local_release_up.sh
```

Если Docker сообщает, что образ используется контейнером, сначала остановите проект:

Windows:

```powershell
.\deploy\scripts\local_release_down.ps1
```

Linux / macOS:

```bash
sh deploy/scripts/local_release_down.sh
```

Затем снова удалите образ:

```bash
docker rmi it-arch-assistant-backend:local
```

Если образ не удаляется, можно выполнить принудительное удаление:

```bash
docker rmi -f it-arch-assistant-backend:local
```

---


## 📁 Структура проекта
```
it-architect-assistant/
├── backend/                # FastAPI приложение
│   ├── alembic/            # Миграции базы данных
│   ├── app/
│   │   ├── api/            # REST эндпоинты
│   │   ├── bootstrap/      # Инициализация приложения
│   │   ├── core/           # Конфигурация, зависимости
│   │   ├── db/             # Работа с БД
│   │   ├── domain/         # Бизнес-сущности
│   │   ├── integrations/   # Внешние сервисы
│   │   ├── schemas/        # Pydantic модели
│   │   ├── tasks/          # Celery задачи
│   │   ├── templates/      # Шаблоны
│   │   ├── tests/          # Модульные тесты
│   │   └── main.py         # Точка входа
│   └── scripts/            # Вспомогательные скрипты
├── frontend/               # React + TypeScript
│   └── src/
│       ├── app/          # Компоненты страниц
│       ├── entities/     # Бизнес-сущности
│       ├── features/     # Фичи
│       ├── generated/    # Авто-генерируемый API клиент
│       ├── pages/        # Страницы
│       ├── shared/       # UI компоненты
│       ├── types/        # TypeScript типы
│       └── main.tsx
├── deploy/
│   ├── nginx/
│   └── scripts/            # Скрипты управления
│       ├── compose.local-production.yml
│       ├── local-production.env.example
│       ├── local_release_up.ps1/sh
│       ├── local_release_down.ps1/sh
│       └── local_release_update.ps1/sh
├── docs/                   # Документация
└── .env.example            # Dev конфигурация
```


<div align="center"> <sub> by BeatByte • Пермь, 2026</sub> </div> 
