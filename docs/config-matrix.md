# Config matrix

## Supported runtime

| Runtime | APP_ENV | AUTH_MODE | Generation/Verification | Intended use |
|---|---|---:|---|---|
| Docker local | `local` | `local_noauth` | async via Celery worker | single supported local stack |

## Environment file

| File | Target runtime | Notes |
|---|---|---|
| `.env.example` | Docker local | copy to `.env` and override local values there |

## Key variables

| Variable | Default / example                    | Used by | Required in |
|---|--------------------------------------|---|---|
| `APP_ENV` | `local`                              | backend settings | Docker local |
| `DEBUG` | `true`                               | FastAPI runtime | Docker local |
| `AUTH_MODE` | `local_noauth`                       | auth resolver / route guards | Docker local |
| `ALLOWED_CORS_ORIGINS` | localhost gateway origins            | CORS middleware | Docker local |
| `DATABASE_URL` | `postgresql+psycopg://...`           | SQLAlchemy | Docker local |
| `REDIS_URL` | `redis://...`                        | Celery + cache | Docker local |
| `CELERY_BROKER_URL` | `redis://.../0`                      | Celery worker | Docker local |
| `CELERY_RESULT_BACKEND` | `redis://.../1`                      | Celery result backend | Docker local |
| `CELERY_WORKER_CONCURRENCY` | `2`                                  | local worker process count | optional |
| `CELERY_WORKER_QUEUES` | `default,knowledge_extraction,knowledge_vectorization,knowledge_llm_extraction,architecture_generation,architecture_verification` | queues consumed by the local worker | optional |
| `GENERATION_EXECUTE_INLINE` | `false`                              | generation runtime switch | Docker local |
| `GENERATION_RETRIEVAL_LIMIT` | `12`                                 | max knowledge fragments selected for generation | optional |
| `GENERATION_SECTION_RETRIEVAL_LIMIT` | `1`                                  | extra per-section retrieval snippets for generation grounding | optional |
| `GENERATION_PROMPT_FRAGMENT_CHAR_LIMIT` | `1600`                               | per-fragment prompt evidence cap | optional |
| `VERIFICATION_EXECUTE_INLINE` | `false`                              | verification runtime switch | Docker local |
| `VERIFICATION_RULE_RAG_LIMIT` | `2`                                   | max retrieved evidence snippets attached to each verification rule | optional |
| `HEALTH_CHECK_WORKER` | `true`                               | health endpoints | Docker local |
| `LLM_PROVIDER` | `openai_compatible`                  | generation gateway | Docker local |
| `LLM_BASE_URL` | local Ollama endpoint                | generation gateway | Docker local |
| `LLM_API_KEY` | empty local value                    | generation gateway | optional |
| `LLM_TIMEOUT_SEC` | `1800`                               | upper bound for one LLM generation HTTP call | optional |
| `LLM_TEMPERATURE` | `0.1`                                | generation determinism | optional |
| `LLM_TOP_P` | empty local value                    | generation sampling cap | optional |
| `LLM_MAX_TOKENS` | empty local value                    | optional generation output cap | optional |
| `EMBEDDING_PROVIDER` | `local_openai_compatible`            | retrieval + knowledge pipeline | Docker local |
| `EMBEDDING_BASE_URL` | local Ollama endpoint                | embeddings | Docker local |
| `EMBEDDING_API_KEY` | empty local value                    | embeddings | optional |
| `EMBEDDING_BATCH_SIZE` | `64`                                 | knowledge indexing batch size for remote embeddings | optional |
| `RERANKER_PROVIDER` | `heuristic`                          | retrieval reranking | optional |
| `RERANKER_BASE_URL` | empty unless remote reranker enabled | reranker client | when `RERANKER_PROVIDER=openai_compatible` |
| `KNOWLEDGE_ALLOWED_LOCAL_SOURCE_ROOTS` | local bundle + uploads               | knowledge source guard | Docker local |
| `KNOWLEDGE_FETCH_TIMEOUT_SEC` | `30`                                 | remote knowledge source connect/read timeout | optional |
| `KNOWLEDGE_MAX_DOCUMENT_SIZE_BYTES` | `104857600`                          | per-document fetch limit | optional |
| `KNOWLEDGE_MAX_UPLOAD_SIZE_BYTES` | `104857600`                          | per-file upload limit | optional |
| `KNOWLEDGE_LARGE_DOCUMENT_THRESHOLD_BYTES` | `1048576`                            | threshold for faster large-document indexing policy | optional |
| `KNOWLEDGE_LARGE_DOCUMENT_MAX_CHUNKS` | `240`                                | target chunk cap for large documents | optional |
| `KNOWLEDGE_LLM_EXTRACTION_MAX_CHUNKS` | `48`                                 | max chunks for LLM document-memory extraction before heuristic mode | optional |
| `KNOWLEDGE_LOCAL_EMBEDDING_MAX_CHUNKS` | `96`                                 | max chunks for local dense embeddings before lexical-only indexing | optional |

## Compose

Use the single root compose file:

```bash
docker compose up --build -d
```
