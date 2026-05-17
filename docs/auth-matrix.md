# Authentication mode matrix

## Allowed combinations

| APP_ENV | AUTH_MODE | Allowed | Why |
|---|---|---:|---|
| `local` | `local_noauth` | yes | fast local development |
| `test` | `local_noauth` | yes | automated local tests |
| `dev` | `trusted_headers` | yes | shared environment should exercise auth path |
| `staging` | `trusted_headers` | yes | staging must match production auth style |
| `prod` / `production` / `release` | `trusted_headers` | yes | production-safe mode |
| `dev` / `staging` / `prod` | `local_noauth` | no | forbidden by startup guard |

## Additional startup guards

В `staging` и production-like окружениях backend теперь отказывается запускаться, если выполняется любое из следующих условий:

- `DEBUG=true`
- `ALLOWED_CORS_ORIGINS` содержит `*`, `localhost`, или `127.0.0.1`
- `LLM_API_KEY`, `EMBEDDING_API_KEY`, или `RERANKER_API_KEY` используют placeholder/test-значения, например `test`, `dummy`, или `changeme`

## Local developer identity

Локальный Docker runtime использует настроенный локальный principal:

- `LOCAL_USER_LOGIN`
- `LOCAL_USER_DISPLAY_NAME`
- `LOCAL_USER_ROLES`
- `LOCAL_USER_ACCOUNT_TYPE`

Эти значения учитываются только при `AUTH_MODE=local_noauth`.
