# GitLab local production setup

Проект поставляется как локальное Docker Compose-приложение для персональной рабочей станции каждого пользователя.
GitLab CI/CD проверяет код и собирает релизные образы, а пользователи могут запускать тот же production-style стек локально из репозитория.

## Pipeline

`.gitlab-ci.yml` runs:

Оставьте включёнными следующие проверки и настройки проекта:

- линтинг backend, выборочные проверки mypy, запуск pytest с формированием отчётов JUnit и Cobertura coverage;
- проверку миграций Alembic на PostgreSQL с расширением pgvector;
- линтинг frontend, проверку типов, встроенные тесты и сборку;
- проверку конфигурации Docker Compose для compose-файлов default и local-production;
- проверку синтаксиса shell-скриптов локального релиза;
- smoke-проверки Postman/Newman на запущенном local-production-стеке;
- шаблоны GitLab SAST и Secret Detection;
- сборку backend- и frontend-образов для основной ветки и тегов;
- продвижение образа `latest` из основной ветки.

SSH deploy job не используется, так как production runtime разворачивается локально на ПК каждого пользователя.

## Local Release Runbook

Требования:

- Git;
- Docker Desktop или Docker Engine с Docker Compose plugin;
- Свободное место под PostgreSQL, Redis, Ollama, backend, и frontend images.

Первый запуск на Windows:

```powershell
.\deploy\scripts\local_release_up.ps1
```

Скрипт создаёт `.env.local`, если файл ещё не существует, запускает Docker Compose, подтягивает сконфигурированные модели Ollama и ждёт готовности API. Пользовательские базы знаний создаются и выбираются отдельно от системной baseline-базы.

Skip model pulling or knowledge bootstrap when you only need to restart containers:

```powershell
.\deploy\scripts\local_release_up.ps1 -SkipModelPull -SkipBootstrapKnowledge
```

Linux/macOS:

```bash
sh deploy/scripts/local_release_up.sh
```

Обновление баз знаний происходит через web-интерфейс.

Быстрый перезапуск:
```powershell
.\deploy\scripts\local_release_up.ps1 -SkipModelPull
```
Linux/macOS:
```bash
sh deploy/scripts/local_release_up.sh --skip-model-pull --skip-bootstrap-knowledge
```

При первом запуске файл `.env.local` создается на основе `deploy/local-production.env.example`.
Отредактируйте `.env.local`, указав значения, зависящие от конкретной машины, например, endpointы и порты.
Локальные `.env*` файлы игнорируются Git.

Создайте резервную копию PostgreSQL, конфигурации развертывания и загруженных документов базы знаний:

```powershell
.\deploy\scripts\local_backup.ps1 -EnvFile ".env.local" -OutputDir "backups"
```

Linux/macOS:

```bash
sh deploy/scripts/local_backup.sh --env-file .env.local --output-dir backups
```

Документация по восстановлению: [backup-and-restore.md](backup-and-restore.md).

Открыть website проекта:

```text
http://localhost:8080
```

Остановка проекта:

```powershell
.\deploy\scripts\local_release_down.ps1
```

Обновление GitLab и пересборка проекта:

```powershell
.\deploy\scripts\local_release_update.ps1
```
Запустить Postman/Newman smoke-тесты на уже поднятом локальном стеке:
```powershell
.\deploy\scripts\run_postman_smoke.ps1
```
Linux/macOS:
```bash
sh deploy/scripts/run_postman_smoke.sh
```

## Pre-Push Gate

Репозиторий включает версионируемый pre-push хук в `.githooks/pre-push`. Включите его один раз после клонирования проекта:
```bash
git config core.hooksPath .githooks
```

Хук запускает Docker-based проверка backend, frontend, валидацию Docker Compose и Postman/Newman smoke-тесты.
Если одна их проверка завершается ошибкой, git push останавливается

Ручной запуск на Windows:
```powershell
.\deploy\scripts\pre_push_check.ps1
```
Linux/macOS:
```bash
sh deploy/scripts/pre_push_check.sh
```

Используйте `-SkipPostman` в Powershell или `SKIP_POSTMAN=true` в shell только в случаях, когда smoke-проверка локального стека намеренно недоступна.

## Runtime Notes

Compose-файл local-production использует собранные образы, статический nginx frontend,
PostgreSQL с pgvector, Redis с append-only persistence, API, worker, gateway и Ollama. В нём установлено `DEBUG=false`, но сохранены `APP_ENV=local` и `AUTH_MODE=local_noauth`,
потому что приложение намеренно привязано к локальной рабочей станции пользователя по адресу localhost.


Для будущего развертывания на общем сервере не используйте этот локальный профиль авторизации. Добавьте слой SO/reverse-proxy аутентификации и переключитесь на
`APP_ENV=production` с  non-local CORS origins.


## GitLab Project Settings

Оставляйте включенными следующие параметры проекта:

- защищать ветку `main` и запретить force pushes;
- требовать merge request перед слиянием изменений в `main`;
- включить GitLab Container Registry;
- использовать runner с поддержкой Docker-in-Docker или заменить задания сборки Docker на утвержденной в организации инструмент разработки;
- оставить включенным задания SAST и Secret Detection.
