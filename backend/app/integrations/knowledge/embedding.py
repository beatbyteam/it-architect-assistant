from __future__ import annotations

import math
import re
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.exceptions import DependencyUnavailableError, ValidationError
from app.integrations.openai_compatible import resolve_openai_compatible_endpoint

TOKEN_RE = re.compile(r"[\w\-/\.]+", re.UNICODE)
DEFAULT_REMOTE_EMBEDDING_BATCH_SIZE = 64


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    code: str
    provider_name: str
    model_id: str
    dimensions: int
    query_prefix: str = ""
    document_prefix: str = ""
    normalize_l2: bool = True
    truncate_dim: int | None = None
    max_input_tokens: int | None = None
    description: str | None = None

    def format_query(self, text: str, *, title: str | None = None) -> str:
        payload = _prepare_payload(text=text, title=title, prefix=self.query_prefix)
        return payload

    def format_document(self, text: str, *, title: str | None = None) -> str:
        payload = _prepare_payload(text=text, title=title, prefix=self.document_prefix)
        return payload


class EmbeddingProfileRegistry:
    _profiles: dict[str, EmbeddingProfile] = {
        "statistical_default": EmbeddingProfile(
            code="statistical_default",
            provider_name="statistical",
            model_id="local-statistical-v2",
            dimensions=16,
            description="Development fallback profile",
        ),
        "bge_m3_default": EmbeddingProfile(
            code="bge_m3_default",
            provider_name="local_openai_compatible",
            model_id="bge-m3",
            dimensions=1024,
            description="Multilingual dense retrieval profile for local production use",
        ),
        "embeddinggemma_lite": EmbeddingProfile(
            code="embeddinggemma_lite",
            provider_name="local_openai_compatible",
            model_id="embeddinggemma-300m",
            dimensions=768,
            query_prefix="task: retrieval.query\n",
            document_prefix="task: retrieval.document\n",
            description="Lighter multilingual retrieval profile for weaker local machines",
        ),
    }

    @classmethod
    def get(cls, code: str) -> EmbeddingProfile:
        normalized = (code or "").strip().lower()
        try:
            return cls._profiles[normalized]
        except KeyError as exc:
            raise DependencyUnavailableError(
                "embedding_profile", f"Unsupported embedding profile: {code}"
            ) from exc

    @classmethod
    def resolve(
        cls,
        *,
        profile_code: str | None,
        provider_name: str | None,
        dimensions: int | None,
        model_id: str | None,
    ) -> EmbeddingProfile:
        if profile_code:
            profile = cls.get(profile_code)
            resolved_provider = (
                provider_name or profile.provider_name
            ).strip() or profile.provider_name
            resolved_dimensions = int(dimensions or profile.dimensions)
            resolved_model = (model_id or profile.model_id).strip() or profile.model_id
            if (
                resolved_provider == profile.provider_name
                and resolved_dimensions == profile.dimensions
                and resolved_model == profile.model_id
            ):
                return profile
            return EmbeddingProfile(
                code=profile.code,
                provider_name=resolved_provider,
                model_id=resolved_model,
                dimensions=resolved_dimensions,
                query_prefix=profile.query_prefix,
                document_prefix=profile.document_prefix,
                normalize_l2=profile.normalize_l2,
                truncate_dim=profile.truncate_dim,
                max_input_tokens=profile.max_input_tokens,
                description=profile.description,
            )
        resolved_provider = (provider_name or "statistical").strip().lower() or "statistical"
        resolved_dimensions = int(dimensions or 16)
        resolved_model = (model_id or _default_model_id_for_provider(resolved_provider)).strip()
        code = f"custom_{resolved_provider}_{resolved_model.replace('/', '_').replace(':', '_')}"
        return EmbeddingProfile(
            code=code,
            provider_name=resolved_provider,
            model_id=resolved_model,
            dimensions=resolved_dimensions,
            description="Custom profile resolved from legacy embedding settings",
        )


@dataclass(slots=True)
class EmbeddingBatchResult:
    vectors: list[list[float]]
    provider_name: str
    model_id: str
    dimensions: int
    diagnostics: dict[str, object]


class EmbeddingProvider(Protocol):
    provider_name: str
    model_id: str

    def encode_texts(self, texts: list[str], *, dimensions: int) -> EmbeddingBatchResult: ...


class StatisticalEmbeddingProvider:
    provider_name = "statistical"
    model_id = "local-statistical-v2"

    def encode_texts(self, texts: list[str], *, dimensions: int) -> EmbeddingBatchResult:
        vectors = [self._encode_single(text, dimensions=dimensions) for text in texts]
        return EmbeddingBatchResult(
            vectors=vectors,
            provider_name=self.provider_name,
            model_id=self.model_id,
            dimensions=dimensions,
            diagnostics={
                "text_count": len(texts),
                "mode": "local",
                "provider_type": "development_fallback",
            },
        )

    def _encode_single(self, text: str, *, dimensions: int) -> list[float]:
        dims = max(4, dimensions)
        vector = [0.0] * dims
        tokens = [token.lower() for token in TOKEN_RE.findall(text)]
        if not tokens:
            return vector
        token_counts = Counter(tokens)
        max_tf = max(token_counts.values()) or 1
        for token, count in token_counts.items():
            tf = 0.5 + 0.5 * (count / max_tf)
            for index, fragment in enumerate(self._feature_fragments(token), start=1):
                slot = self._stable_slot(fragment, dims)
                sign = 1.0 if self._stable_slot(fragment[::-1], 2) == 0 else -1.0
                vector[slot] += sign * tf / index
        lexicon = {
            0: {"api", "openapi", "endpoint", "rest", "graphql"},
            1: {"postgres", "database", "pgvector", "sql", "schema"},
            2: {"service", "component", "module", "backend", "frontend"},
            3: {"rule", "must", "shall", "required", "обязан", "должен"},
            4: {"integration", "event", "queue", "message", "broker"},
            5: {"risk", "constraint", "assumption", "nfr", "latency"},
        }
        lowered = set(tokens)
        for axis, keywords in lexicon.items():
            if axis >= dims:
                break
            overlap = len(lowered & keywords)
            if overlap:
                vector[axis] += overlap * 0.75
        return _normalize(vector, dimensions=dims)

    @staticmethod
    def _feature_fragments(token: str) -> list[str]:
        fragments = [token]
        if len(token) >= 3:
            fragments.extend(token[index : index + 3] for index in range(len(token) - 2))
        if len(token) >= 5:
            fragments.append(token[:5])
            fragments.append(token[-5:])
        return fragments

    @staticmethod
    def _stable_slot(value: str, modulus: int) -> int:
        result = 0
        for char in value:
            result = (result * 131 + ord(char)) % modulus
        return result


class HttpEmbeddingProvider:
    provider_name = "http_json"
    model_id = "external-http-json"

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None = None,
        timeout_sec: float = 30.0,
        model_id: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        if model_id:
            self.model_id = model_id

    def encode_texts(self, texts: list[str], *, dimensions: int) -> EmbeddingBatchResult:
        if not self.base_url:
            raise DependencyUnavailableError(
                "embedding_base_url", "EMBEDDING_BASE_URL is required for http_json provider"
            )
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        started = time.perf_counter()
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(
                self.base_url, json={"texts": texts, "dimensions": dimensions}, headers=headers
            )
            response.raise_for_status()
            body = response.json()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        vectors = body.get("vectors")
        if not isinstance(vectors, list):
            raise DependencyUnavailableError(
                "embedding_http_response", "Embedding provider returned invalid payload"
            )
        normalized = [
            _normalize([float(item) for item in vector], dimensions=dimensions)
            for vector in vectors
        ]
        if len(normalized) != len(texts):
            raise DependencyUnavailableError(
                "embedding_http_response",
                f"Embedding provider returned {len(normalized)} vectors for {len(texts)} texts",
            )
        return EmbeddingBatchResult(
            vectors=normalized,
            provider_name=self.provider_name,
            model_id=str(body.get("model_id") or self.model_id),
            dimensions=dimensions,
            diagnostics={"text_count": len(texts), "mode": "http_json", "latency_ms": latency_ms},
        )


class OpenAICompatibleEmbeddingProvider(HttpEmbeddingProvider):
    provider_name = "openai_compatible"
    model_id = "text-embedding-default"

    def _resolve_embeddings_url(self) -> str:
        return resolve_openai_compatible_endpoint(
            base_url=self.base_url,
            endpoint_path="/embeddings",
            dependency_name="embedding_base_url",
            missing_message="EMBEDDING_BASE_URL is required for openai_compatible provider",
        )

    def encode_texts(self, texts: list[str], *, dimensions: int) -> EmbeddingBatchResult:
        request_url = self._resolve_embeddings_url()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body: dict[str, Any] = {"input": texts, "model": self.model_id}
        if dimensions > 0:
            body["dimensions"] = dimensions
        started = time.perf_counter()
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(request_url, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        data = payload.get("data")
        if not isinstance(data, list):
            raise DependencyUnavailableError(
                "embedding_openai_response",
                "OpenAI-compatible embedding provider returned invalid payload",
            )
        ordered_rows = sorted(
            (row for row in data if isinstance(row, dict)), key=lambda row: int(row.get("index", 0))
        )
        vectors: list[list[float]] = []
        for row in ordered_rows:
            raw = row.get("embedding")
            if not isinstance(raw, list):
                raise DependencyUnavailableError(
                    "embedding_openai_response", "Embedding row does not contain numeric vector"
                )
            vectors.append(_normalize([float(item) for item in raw], dimensions=dimensions))
        if len(vectors) != len(texts):
            raise DependencyUnavailableError(
                "embedding_openai_response",
                f"Embedding provider returned {len(vectors)} vectors for {len(texts)} texts",
            )
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
        return EmbeddingBatchResult(
            vectors=vectors,
            provider_name=self.provider_name,
            model_id=str(payload.get("model") or self.model_id),
            dimensions=dimensions,
            diagnostics={
                "text_count": len(texts),
                "mode": "openai_compatible",
                "latency_ms": latency_ms,
                "usage": usage,
            },
        )


class LocalInferenceEmbeddingProvider(OpenAICompatibleEmbeddingProvider):
    provider_name = "local_inference"


class EmbeddingService:
    def __init__(
        self,
        *,
        profile_code: str | None = None,
        provider_name: str | None = None,
        dimensions: int | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_sec: float = 30.0,
        model_id: str | None = None,
        batch_size: int | None = None,
    ) -> None:
        self.profile = EmbeddingProfileRegistry.resolve(
            profile_code=profile_code,
            provider_name=provider_name,
            dimensions=dimensions,
            model_id=model_id,
        )
        self.provider_name = self.profile.provider_name
        self.dimensions = self.profile.dimensions
        if self.dimensions <= 0:
            raise ValidationError(
                "Embedding dimensions must be positive", error_code="EMBEDDING_DIMENSIONS_INVALID"
            )
        self.remote_batch_size = max(1, int(batch_size or DEFAULT_REMOTE_EMBEDDING_BATCH_SIZE))
        if self.provider_name in {"statistical", "local"}:
            self.provider: EmbeddingProvider = StatisticalEmbeddingProvider()
        elif self.provider_name == "http_json":
            self.provider = HttpEmbeddingProvider(
                base_url=base_url,
                api_key=api_key,
                timeout_sec=timeout_sec,
                model_id=self.profile.model_id,
            )
        elif self.provider_name == "openai_compatible":
            self.provider = OpenAICompatibleEmbeddingProvider(
                base_url=base_url,
                api_key=api_key,
                timeout_sec=timeout_sec,
                model_id=self.profile.model_id,
            )
        elif self.provider_name in {"local_inference", "ollama", "local_openai_compatible"}:
            self.provider = LocalInferenceEmbeddingProvider(
                base_url=base_url,
                api_key=api_key,
                timeout_sec=timeout_sec,
                model_id=self.profile.model_id,
            )
        else:
            raise DependencyUnavailableError(
                "embedding_provider", f"Unsupported embedding provider: {self.provider_name}"
            )

    def describe(self) -> dict[str, object]:
        return {
            "profile_code": self.profile.code,
            "provider_name": self.provider.provider_name,
            "model_id": self.profile.model_id,
            "dimensions": self.profile.dimensions,
            "query_prefix": self.profile.query_prefix,
            "document_prefix": self.profile.document_prefix,
            "normalize_l2": self.profile.normalize_l2,
            "truncate_dim": self.profile.truncate_dim,
        }

    def encode_query(self, text: str, *, title: str | None = None) -> EmbeddingBatchResult:
        formatted = self.profile.format_query(text, title=title)
        return self.provider.encode_texts([formatted], dimensions=self.profile.dimensions)

    def encode_document(self, text: str, *, title: str | None = None) -> EmbeddingBatchResult:
        return self.encode_documents([text], titles=[title])

    def encode_documents(
        self,
        texts: list[str],
        *,
        titles: list[str | None] | None = None,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> EmbeddingBatchResult:
        if titles is None:
            titles = [None] * len(texts)
        if len(titles) != len(texts):
            raise ValidationError(
                "Document titles count must match document texts count",
                error_code="EMBEDDING_TITLES_LENGTH_MISMATCH",
            )
        payloads = [
            self.profile.format_document(text, title=title)
            for text, title in zip(texts, titles, strict=False)
        ]
        if not payloads:
            return EmbeddingBatchResult(
                vectors=[],
                provider_name=self.provider.provider_name,
                model_id=self.profile.model_id,
                dimensions=self.profile.dimensions,
                diagnostics={"text_count": 0, "mode": "empty"},
            )
        if self.provider_name in {"statistical", "local"} or len(payloads) <= self.remote_batch_size:
            if progress_callback is not None:
                progress_callback(
                    {
                        "completed_batches": 0,
                        "total_batches": 1 if payloads else 0,
                        "completed_texts": 0,
                        "total_texts": len(payloads),
                        "batch_size": len(payloads),
                    }
                )
            result = self.provider.encode_texts(payloads, dimensions=self.profile.dimensions)
            if progress_callback is not None:
                progress_callback(
                    {
                        "completed_batches": 1 if payloads else 0,
                        "total_batches": 1 if payloads else 0,
                        "completed_texts": len(result.vectors),
                        "total_texts": len(payloads),
                        "batch_size": len(payloads),
                        "last_batch": result.diagnostics,
                    }
                )
            return result

        vectors: list[list[float]] = []
        provider_name = self.provider.provider_name
        model_id = self.profile.model_id
        batch_count = 0
        total_batches = math.ceil(len(payloads) / self.remote_batch_size)
        total_latency_ms = 0.0
        last_diagnostics: dict[str, object] = {}
        for batch in _batch_items(payloads, self.remote_batch_size):
            batch_count += 1
            if progress_callback is not None:
                progress_callback(
                    {
                        "completed_batches": batch_count - 1,
                        "total_batches": total_batches,
                        "completed_texts": len(vectors),
                        "total_texts": len(payloads),
                        "batch_size": len(batch),
                    }
                )
            result = self.provider.encode_texts(batch, dimensions=self.profile.dimensions)
            vectors.extend(result.vectors)
            provider_name = result.provider_name
            model_id = result.model_id
            last_diagnostics = dict(result.diagnostics or {})
            latency = last_diagnostics.get("latency_ms")
            if isinstance(latency, int | float):
                total_latency_ms += float(latency)
            if progress_callback is not None:
                progress_callback(
                    {
                        "completed_batches": batch_count,
                        "total_batches": total_batches,
                        "completed_texts": len(vectors),
                        "total_texts": len(payloads),
                        "batch_size": self.remote_batch_size,
                        "last_batch": last_diagnostics,
                    }
                )

        return EmbeddingBatchResult(
            vectors=vectors,
            provider_name=provider_name,
            model_id=model_id,
            dimensions=self.profile.dimensions,
            diagnostics={
                "text_count": len(payloads),
                "mode": "batched",
                "batch_size": self.remote_batch_size,
                "batch_count": batch_count,
                "latency_ms_total": round(total_latency_ms, 2),
                "last_batch": last_diagnostics,
            },
        )

    def encode_text(self, text: str) -> EmbeddingBatchResult:
        return self.encode_query(text)

    def encode_texts(self, texts: list[str]) -> EmbeddingBatchResult:
        return self.encode_documents(texts)

    def healthcheck(self) -> dict[str, object]:
        if self.provider_name == "statistical":
            return {"healthy": True, "details": "statistical_fallback", **self.describe()}
        try:
            probe = self.encode_query("health check retrieval query")
            vector_len = len(probe.vectors[0]) if probe.vectors else 0
            return {
                "healthy": vector_len == self.profile.dimensions,
                "details": "ok"
                if vector_len == self.profile.dimensions
                else f"unexpected vector length: {vector_len}",
                "vector_length": vector_len,
                **self.describe(),
            }
        except Exception as exc:
            return {"healthy": False, "details": str(exc), **self.describe()}


def _default_model_id_for_provider(provider_name: str) -> str:
    if provider_name in {"statistical", "local"}:
        return "local-statistical-v2"
    if provider_name in {"local_inference", "ollama", "local_openai_compatible"}:
        return "bge-m3"
    if provider_name == "openai_compatible":
        return "text-embedding-default"
    return "custom-embedding-model"


def _prepare_payload(*, text: str, title: str | None, prefix: str) -> str:
    normalized_text = (text or "").strip()
    normalized_title = (title or "").strip()
    if normalized_title:
        body = (
            f"Title: {normalized_title}\n\n{normalized_text}"
            if normalized_text
            else f"Title: {normalized_title}"
        )
    else:
        body = normalized_text
    return f"{prefix}{body}" if prefix else body


def _batch_items(items: list[str], batch_size: int) -> list[list[str]]:
    size = max(1, int(batch_size))
    return [items[index : index + size] for index in range(0, len(items), size)]


def _normalize(vector: list[float], *, dimensions: int) -> list[float]:
    if len(vector) < dimensions:
        vector = vector + [0.0] * (dimensions - len(vector))
    elif len(vector) > dimensions:
        vector = vector[:dimensions]
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return [0.0] * dimensions
    return [value / magnitude for value in vector]
