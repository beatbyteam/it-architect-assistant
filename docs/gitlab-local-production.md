# GitLab local production setup

This project is delivered as a local Docker Compose application for each user's personal workstation. GitLab CI/CD validates the code and builds release images, while users can run the same production-style stack locally from the repository.

## Pipeline

`.gitlab-ci.yml` runs:

- backend linting, selected mypy checks, pytest with JUnit and Cobertura coverage reports;
- Alembic migration validation against PostgreSQL with pgvector;
- frontend linting, typecheck, bundled tests, and build;
- Docker Compose config validation for the default and local-production compose files;
- shell syntax validation for local release helper scripts;
- Postman/Newman smoke checks against a running local-production stack;
- GitLab SAST and Secret Detection templates;
- backend and frontend image builds on the default branch and tags;
- `latest` image promotion on the default branch.

There is no SSH deploy job because production runtime is local on each user's PC.

## Local Release Runbook

Prerequisites:

- Git;
- Docker Desktop or Docker Engine with the Docker Compose plugin;
- enough disk space for PostgreSQL, Redis, Ollama, backend, and frontend images.

Start on Windows PowerShell:

```powershell
.\deploy\scripts\local_release_up.ps1
```

The script creates `.env.local` when it is missing, starts Docker Compose, and pulls the configured Ollama models. Knowledge bases are updated explicitly from the application UI.

Skip model pulling when you only need to restart containers:

```powershell
.\deploy\scripts\local_release_up.ps1 -SkipModelPull
```

Start on Linux/macOS:

```bash
sh deploy/scripts/local_release_up.sh
```

Skip model pulling when you only need to restart containers:

```bash
sh deploy/scripts/local_release_up.sh --skip-model-pull
```

The first run creates `.env.local` from `deploy/local-production.env.example`. Edit `.env.local` for machine-specific values such as model endpoints and ports. Local `.env*` files are ignored by Git.

Open:

```text
http://localhost:8080
```

Stop:

```powershell
.\deploy\scripts\local_release_down.ps1
```

Update from GitLab and rebuild:

```powershell
.\deploy\scripts\local_release_update.ps1
```

Run Postman/Newman smoke tests against the already running local stack:

```powershell
.\deploy\scripts\run_postman_smoke.ps1
```

Linux/macOS:

```bash
sh deploy/scripts/run_postman_smoke.sh
```

## Pre-Push Gate

The repository includes a versioned pre-push hook in `.githooks/pre-push`. Enable it once after cloning:

```bash
git config core.hooksPath .githooks
```

The hook runs Docker-based backend checks, frontend checks, Compose validation, and Postman/Newman smoke tests. A failing check stops `git push`.

Run the same gate manually on Windows:

```powershell
.\deploy\scripts\pre_push_check.ps1
```

Run it manually on Linux/macOS:

```bash
sh deploy/scripts/pre_push_check.sh
```

Use `-SkipPostman` on PowerShell or `SKIP_POSTMAN=true` on shell only when the local stack smoke check is intentionally unavailable.

## Runtime Notes

The local-production compose file uses built images, a static nginx frontend, PostgreSQL with pgvector, Redis with append-only persistence, API, worker, gateway, and Ollama. It sets `DEBUG=false` but keeps `APP_ENV=local` and `AUTH_MODE=local_noauth` because the app is intentionally bound to a user's local workstation at `localhost`.

For a real shared server later, do not reuse this local auth profile. Add an SSO/reverse-proxy auth layer and switch to `APP_ENV=production` with non-local CORS origins.

## GitLab Project Settings

Keep these project settings enabled:

- protect `main` and disallow force pushes;
- require merge requests before merging to `main`;
- enable GitLab Container Registry;
- use a runner that supports Docker-in-Docker or replace Docker build jobs with the organization's approved builder;
- keep SAST and Secret Detection jobs enabled.
