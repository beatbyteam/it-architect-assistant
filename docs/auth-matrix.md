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

In `staging` and production-like environments the backend now refuses to start when any of the following is true:

- `DEBUG=true`
- `ALLOWED_CORS_ORIGINS` contains `*`, `localhost`, or `127.0.0.1`
- `LLM_API_KEY`, `EMBEDDING_API_KEY`, or `RERANKER_API_KEY` use placeholder/test values such as `test`, `dummy`, or `changeme`

## Local developer identity

The local Docker runtime uses the configured local principal:

- `LOCAL_USER_LOGIN`
- `LOCAL_USER_DISPLAY_NAME`
- `LOCAL_USER_ROLES`
- `LOCAL_USER_ACCOUNT_TYPE`

Those values are ignored unless `AUTH_MODE=local_noauth`.
