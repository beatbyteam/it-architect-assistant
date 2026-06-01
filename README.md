# 💡Помощник ИТ-архитектора


**Помощник ИТ‑архитектора** — сервис для автоматического формирования ИТ‑архитектуры решения по текстовой бизнес‑задаче и последующей проверки этого решения на соответствие корпоративным стандартам и нормативам. 

[![MVP](https://img.shields.io/badge/status-MVP-yellow)](LICENSE) [![Python](https://img.shields.io/badge/python-3.12-blue)](https://www.python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com/) [![React](https://img.shields.io/badge/React-18.3-cyan)](https://react.dev/) [![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue)](https://www.postgresql.org/) [![Ollama](https://img.shields.io/badge/Ollama-LLM-orange)](https://ollama.com/)

## 📋 Оглавление

- [📋 Требования к системе](#system-requirements)
- [✨ Основные возможности](#features)
- [🖥️ Способы запуска](#run-options)
- [🛠️ Технологический стек](#tech-stack)
- [⚙️ Конфигурация](#configuration)
- [💾 Резервное копирование и восстановление](#backup-restore)
- [🧯 Частые ошибки и решения](#troubleshooting)
- [📁 Структура проекта](#project-structure)
- [🏗️ Архитектура](#architecture)
- [📒 Документация](#documentation)
- [🔬 Тестовый стенд авторов](#test-stand)

<a id="system-requirements"></a>

## 📋 Требования к системе

| Компонент | Минимально | Рекомендуется |
|-----------|-----------|---------------|
| **CPU** | 2 ядра | 4+ ядер |
| **RAM** | 8 ГБ | 16+ ГБ |
| **Диск** | 20 ГБ | 40+ ГБ |
| **GPU** | — | NVIDIA 6+ ГБ VRAM |
| **Docker** | 4.20+ | последняя версия |
| **ОС** | Windows 10 / macOS 11 / Linux | — |

> [!NOTE]
> При первом запуске требуется интернет для загрузки Docker-образов и LLM-моделей (≈12 ГБ).  

<a id="features"></a>

## ✨ Основные возможности

- 📝 **Приём бизнес‑задачи** на естественном языке
- 🔁 **Контролируемый цикл уточнений** при недостатке данных
- 🤖 **Генерация ИТ-архитектуры** на основе активной базы знаний
- ✅ **Постгенерационная проверка** на соответствие корпоративной архитектуре, стандартам и НТД
- 📎 **Импорт входных документов**: PDF, DOCX, ODT, XLSX, ArchiMate, Markdown, TXT, JSON, изображения
- 🧠 **Локальный LLM** — не требуется облачных сервисов
- 🐳 **Docker Compose** — простое развертывание

<a id="run-options"></a>

## 📋 Способы запуска
- [Требования](#-требования)
- [GPU-ускорение](#-gpu-ускорение)
- [Автоматический запуск (рекомендуемый)](#-автоматический-запуск-рекомендуемый)
- [Ручной запуск (Docker Compose)](#-ручной-запуск-docker-compose)

### 📦 Требования

- **Docker Desktop** или **Docker Engine** с Docker Compose plugin*
- **Свободное место** в Docker под Docker-образы, PostgreSQL, Redis и модели Ollama (~12 ГБ)
- **Git** (для обновления проекта)

### 🔨 GPU-ускорение

GPU-ускорение работает только на системах с NVIDIA GPU.  
Если GPU нет, проект работает в CPU-режиме (медленнее, но функциональность сохраняется).

<details>
<summary>🪟 Windows</summary>

На хостовой машине должны быть:

- Windows 10/11;

- NVIDIA GPU;

- свежий NVIDIA Driver с поддержкой WSL 2;

- установленный WSL;

- Docker Desktop с включенным WSL 2 backend;

- Git

Проверить WSL:
```PowerShell
wsl --status
```

Обновить WSL:
```Powershell
wsl --update
```

Проверить видеокарту в Windows:
```Powershell
nvidia-smi
```

Проверить, что Docker видит GPU:
```PowerShell
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi
```
</details> 

<details>
<summary>🐧 Linux</summary>

На хостовой машине должны быть установлены:

- NVIDIA Driver;

- NVIDIA Container Toolkit;

- Docker и Docker Compose;

- Git

Проверить, что видеокарта видна системе:
```bash
nvidia-smi
```

Настроить NVIDIA Container Toolkit для Docker:
```bash
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker
```

Проверить, что Docker видит GPU:
```bash
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu22.04 nvidia-smi
```
</details> 

### 🤖 Автоматический запуск (рекомендуемый)

> [!NOTE]
> Перед запуском убедитесь, что у вас включен Docker.

<details>
<summary>🪟 Windows</summary>

**1. Переход в директорию проекта**
```PowerShell
cd C:\путь\к\проекту\it-architect-assistant
```

**2. Разблокировка скриптов (только при первом запуске)**
```PowerShell
Unblock-File .\deploy\scripts\local_release_up.ps1
Unblock-File .\deploy\scripts\local_release_update.ps1
Unblock-File .\deploy\scripts\local_release_down.ps1
```
**3. Запуск проекта**

##### Первый запуск без GPU
```Powershell
.\deploy\scripts\local_release_up.ps1
```
##### Первый запуск с GPU
```Powershell
.\deploy\scripts\local_release_up.ps1 -Gpu
```
##### Быстрый перезапуск без загрузки моделей без GPU
```Powershell
.\deploy\scripts\local_release_up.ps1 -SkipModelPull
```
##### Быстрый перезапуск без загрузки моделей с GPU
```Powershell
.\deploy\scripts\local_release_up.ps1 -SkipModelPull -Gpu
```

**4. Обновление проекта**

#### 📌 Требуется Git — скачивает последние изменения и пересобирает стек

##### Обновление проекта без GPU
```Powershell
.\deploy\scripts\local_release_update.ps1
```
##### Обновление проекта с GPU
```Powershell
.\deploy\scripts\local_release_update.ps1 -Gpu
```

**5. Остановка проекта**

##### Остановка проекта без GPU
```Powershell
.\deploy\scripts\local_release_down.ps1
```
##### Остановка проекта с GPU
```Powershell
.\deploy\scripts\local_release_down.ps1 -Gpu
```
</details> 

<details> 
<summary>🐧 Linux/MacOS</summary>

**1.Переход в директорию проекта**
```Bash
cd /путь/к/проекту/it-architect-assistant
```

**2.Запуск проекта**
##### Первый запуск без GPU
```Bash
sh deploy/scripts/local_release_up.sh
```
##### Первый запуск с GPU
```Bash
sh deploy/scripts/local_release_up.sh --gpu
```
##### Быстрый перезапуск без GPU
```Bash
sh deploy/scripts/local_release_up.sh --skip-model-pull
```
##### Быстрый перезапуск с GPU
```Bash
sh deploy/scripts/local_release_up.sh --skip-model-pull --gpu
```

**3. Обновление проекта**
#### 📌 Требуется Git — скачивает последние изменения и пересобирает стек
##### Обновление c GPU
```Bash
sh deploy/scripts/local_release_update.sh
```
##### Обновление с GPU 
```Bash
sh deploy/scripts/local_release_update.sh --gpu
```

**4. Остановка проекта**
##### Остановка без GPU
```Bash
sh deploy/scripts/local_release_down.sh
```
##### Остановска с GPU
```Bash
sh deploy/scripts/local_release_down.sh --gpu
```
</details> 

### 🐳 Ручной запуск (Docker Compose)

> Для опытных пользователей, желающих больше контроля над процессом.
> Перед запуском убедитесь, что у вас включен Docker.

<details> 
<summary> Linux/MacOS/Windows</summary>

### 📝 Подготовка
#### Переход в директорию проекта

```
cd /путь/к/проекту/it-architect-assistant
```
#### Копирование файла конфигурации
```
cp deploy/local-production.env.example .env.local
```

### ▶️ Запуск стека
#### Без GPU:
```
docker compose --env-file .env.local -f deploy/compose.local-production.yml up --build -d
```
#### С GPU:
```
docker compose --env-file .env.local \
  -f deploy/compose.local-production.yml \
  -f deploy/compose.local-production.gpu.yml \
  up --build -d
```

### 📊 Проверка статуса
```
docker compose --env-file .env.local -f deploy/compose.local-production.yml ps
```

### 🔄 Обновление проекта

#### 1. Получить последние изменения из репозитория

```bash
git pull --ff-only
````

#### 2. Пересобрать и запустить стек заново

##### Без GPU:

```bash
docker compose --env-file .env.local \
  -f deploy/compose.local-production.yml \
  up --build -d
```

##### С GPU:

```bash
docker compose --env-file .env.local \
  -f deploy/compose.local-production.yml \
  -f deploy/compose.local-production.gpu.yml \
  up --build -d
```

### ⏹️ Остановка проекта

##### Без GPU:

```bash
docker compose --env-file .env.local \
  -f deploy/compose.local-production.yml \
  down
```

##### С GPU:

```bash
docker compose --env-file .env.local \
  -f deploy/compose.local-production.yml \
  -f deploy/compose.local-production.gpu.yml \
  down
```

### 🧹 Полная остановка с удалением данных

> Команда удаляет контейнеры и тома проекта.
> После этого локальная база данных и загруженные файлы могут быть потеряны.

##### Без GPU:

```bash
docker compose --env-file .env.local \
  -f deploy/compose.local-production.yml \
  down --volumes --remove-orphans
```

##### С GPU:

```bash
docker compose --env-file .env.local \
  -f deploy/compose.local-production.yml \
  -f deploy/compose.local-production.gpu.yml \
  down --volumes --remove-orphans
```


### 📜 Просмотр логов
#### Все логи
```
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs -f
```
#### Логи конкретного сервиса
```
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs backend -f
```

```
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs frontend -f
```

```
docker compose --env-file .env.local -f deploy/compose.local-production.yml logs ollama -f
```

### 🧹 Полная очистка (с удалением томов)
```
docker compose --env-file .env.local -f deploy/compose.local-production.yml down
```

### 🤖 Ручная загрузка моделей Ollama
```
docker compose --env-file .env.local -f deploy/compose.local-production.yml exec ollama ollama pull qwen2.5:7b-instruct
```

```
docker compose --env-file .env.local -f deploy/compose.local-production.yml exec ollama ollama pull bge-m3
```
</details>

### [ОТКРЫТЬ ПРИЛОЖЕНИЕ - http://localhost:8080](http://localhost:8080)

<a id="tech-stack"></a>

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

<a id="configuration"></a>

## ⚙️ Конфигурация

<details>
<summary> Основные параметры конфигурации сервиса </summary>

#### Файлы конфигурации
| Файл | Назначение |
|------|------------|
| `deploy/local-production.env.example` | Шаблон для production-запуска |
| `.env.local` | Локальная конфигурация (создаётся из примера) |
| `.env.example` | Шаблон для разработки |

### Модели по умолчанию

| Модель | Назначение |
|--------|------------|
| `qwen2.5:7b-instruct` | Генерация текста и проверка решений |
| `bge-m3` | Векторный поиск (embeddings) |

### Основные переменные окружения

```env
# Режим приложения
APP_ENV=local                 # local / test / production
DEBUG=false                   # Режим отладки
```

```
# Аутентификация
AUTH_MODE=local_noauth        # Только для local/test окружений
```

```
# База данных
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/it_architect
```

```env
# Модели Ollama
LLM_MODEL_ID=qwen2.5:7b-instruct
EMBEDDING_MODEL_ID=bge-m3

# Анализ изображений (опционально)
VISION_PROVIDER=disabled      # disabled / openai_compatible
VISION_BASE_URL=http://ollama:11434/v1
VISION_MODEL_ID=
```

Если нужно разбирать схемы и скриншоты, установите:
```env
VISION_PROVIDER=openai_compatible
VISION_MODEL_ID=<модель с поддержкой изображений>
```
</details>

#### ⚡ Настройка производительности 
<details>
<summary>Для GPU-стенда (по умолчанию)</summary>
Настройки для более качественной обработки базы знаний:

- Меньшие чанки, overlap 12%
- До 640 чанков для крупных документов
- До 128 чанков для LLM-извлечения
- KNOWLEDGE_LOCAL_EMBEDDING_MAX_CHUNKS=0 (отключает пропуск dense embeddings)
- VERIFICATION_RULE_RAG_LIMIT=8 (правила видят больше фрагментов стандарта)
</details>

<details>
<summary>Для слабого стенда (быстрый режим)</summary>
Если ресурсов недостаточно, используйте:

- KNOWLEDGE_LOCAL_EMBEDDING_MAX_CHUNKS=96
- KNOWLEDGE_LLM_EXTRACTION_MAX_CHUNKS=48
- VERIFICATION_RULE_RAG_LIMIT=2
</details>

### 📅 Обновление базы знаний

Плановые обновления выполняет сервис `scheduler`:

| Политика | Описание |
|----------|----------|
| `weekly` / `monthly` / `scheduled` / `auto` | Обновляются автоматически |
| `manual` | Обновляются только вручную (кнопка «Обновить сейчас» или перезагрузка файла) |

### ⚠️ Важно про аутентификацию

> [!WARNING]
> `AUTH_MODE=local_noauth` разрешён **только** для `APP_ENV=local` и `APP_ENV=test`

Для production-сервера используйте отдельный профиль:

- SSO / reverse proxy
- `APP_ENV=production`
- Строгие CORS origins

<a id="backup-restore"></a>

## 💾 Резервное копирование и восстановление

Локальные резервные копии защищают:
- Опубликованные решения
- Протоколы верификации
- Записи баз знаний
- Конфигурации развёртки
- Загруженные исходные документы

> [!IMPORTANT]
> Резервные копии содержат дамп базы данных, загруженные документы и локальную конфигурацию (включая `.env.local`).  
> **Не публикуйте их** — они могут содержать секреты и конфиденциальные данные.

<details>
<summary> 📦 Создание резервной копии </summary>

**Linux / macOS:**
```bash
sh deploy/scripts/local_backup.sh --env-file .env.local --output-dir backups
```

**Windows**
```bash
 .\deploy\scripts\local_backup.ps1 -EnvFile ".env.local" -OutputDir "backups"
 ```
 
 Скрипт создаёт папку backups/backup-YYYYMMDD-HHMMSS с:

postgres.dump — дамп PostgreSQL

deployment_config.tgz / .zip — compose-файлы, скрипты, примеры окружения и .env.local

knowledge_uploads.tgz — загруженные документы базы знаний

manifest.json и SHA256SUMS — для проверки целостности

</details>

<details>
<summary> 🔄 Восстановление из резервной копии </summary>

**Linux / macOS:**
```bash
sh deploy/scripts/local_restore.sh --env-file .env.local --backup-dir backups/<backup-id>
```

**Windows**
```bash
 .\deploy\scripts\local_restore.ps1 -EnvFile ".env.local" -BackupDir "backups\<backup-id>"
 ```
 
 Cкрипт восстановления:

Останавливает сервисы приложения
Пересоздаёт базу данных PostgreSQL
Восстанавливает загруженные документы
Запускает стек заново

> Скрипт запрашивает подтверждение перед восстановлением.
> Чтобы пропустить запрос, добавьте флаг --yes (Linux/macOS) или -Yes (Windows).

</details>

<a id="troubleshooting"></a>

## 🧯 Частые ошибки и решения

В этом разделе собраны наиболее частые проблемы при локальном запуске проекта и способы их решения.

<details>
<summary> Ошибка загрузки модели Ollama </summary>

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

</details>

<details>
<summary> Контейнер не запускается после изменения `env.local` </summary>

**Признак:**

Изменения в `.env.local` не применяются, сервис продолжает работать со старыми настройками.

**Решение: **

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
</details>


<details>
<summary> Нужно пересобрать только один сервис </summary>
**Признак:**

Был изменён код backend/frontend/celery, но не нужно перезапускать весь проект.

**Решение:**
Перезапустить код в Bash/Powershell c нужным контейнером.

Для `backend`:
```bash
docker compose --env-file .env.local -f deploy/compose.local-production.yml up -d --build --no-deps api
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
</details>

<details>
<summary> Нужно полностью удалить локальное окружение проекта </summary>

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

</details>

<details>
<summary> Порт уже занят </summary>

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

</details>

<details>
<summary> Backend не может подключиться к базе данных </summary>

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
</details>

<details>
<summary> ⚠️ Ошибка сборки Docker-образа </summary>

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
``` Powershell
.\deploy\scripts\local_release_up.ps1
```

Linux / macOS:
``` Bash
sh deploy/scripts/local_release_up.sh
```

Если Docker сообщает, что образ используется контейнером, сначала остановите проект:

Windows:
``` Powershell
.\deploy\scripts\local_release_down.ps1
```

Linux / macOS:
```bash
sh deploy/scripts/local_release_down.sh
```

Затем снова удалите образ:
``` bash/Powershell
docker rmi it-arch-assistant-backend:local
```

Если образ не удаляется, можно выполнить принудительное удаление:
``` Bash/Powershell
docker rmi -f it-arch-assistant-backend:local
```
</details>

<a id="architecture"></a>

## 🏗️ Архитектура

```mermaid
flowchart LR
    User[Пользователь] --> Frontend[React + TypeScript]
    Frontend --> Backend[FastAPI API]
    Backend --> DB[(PostgreSQL + pgvector)]
    Backend --> Redis[(Redis)]
    Redis --> Celery[Celery Worker]
    Celery --> Ollama[Ollama LLM]
    Celery --> DB
```

<a id="project-structure"></a>

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

<a id="documentation"></a>

## 📒 Документация 

### 📄 Интерактивная документация API

После запуска приложения доступны автоматические спецификации API:

**Swagger UI**: [http://localhost:8080/docs](http://localhost:8080/docs)

<a id="test-stand"></a>

## 🔬 Тестовый стенд авторов

Проект разрабатывался и тестировался на конфигурации:

- **CPU**: Intel Core i5-13500 (14 ядер/ 20 потоков)
- **RAM**: 32 ГБ
- **GPU**: NVIDIA GeForce RTX 4070 Ti (12 ГБ VRAM)
- **ОС**: Windows 11 Pro

> [!Note]
Для лучшего user experience использовать конфигурации не ниже указанных.
Загрузка файла в базу знаний занимает около двух минут.
Генерация и проверка архитектурного решения занимает около минуты.

<div align="center">

**BeatByte**  
Пермь, 2026  

<sub>Учебный MVP сервиса поддержки проектирования ИТ-архитектуры</sub>

</div>

