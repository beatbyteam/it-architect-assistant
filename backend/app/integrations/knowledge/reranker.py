from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol, cast

import httpx

from app.core.config import Settings
from app.integrations.knowledge.retrieval_policies import (
    RetrievalCandidate,
    RetrievalPolicy,
    RetrievalReranker,
    RetrievalScoredCandidate,
)
from app.integrations.openai_compatible import resolve_openai_compatible_endpoint

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_RERANKER_WRAPPER_KEYS = ("result", "payload", "data", "response")


@dataclass(slots=True)
class RerankerDiagnostics:
    provider_name: str
    model_id: str | None = None
    latency_ms: float | None = None
    fallback_used: bool = False
    candidate_count: int = 0
    reranked_count: int = 0
    backend: str = "heuristic"


class RerankerProvider(Protocol):
    provider_name: str

    def rerank(
        self,
        *,
        query_text: str,
        candidates: list[RetrievalCandidate],
        policy: RetrievalPolicy,
    ) -> tuple[list[RetrievalScoredCandidate], RerankerDiagnostics]: ...


class HeuristicRerankerProvider:
    provider_name = "heuristic"

    def __init__(self) -> None:
        self.engine = RetrievalReranker()

    def rerank(
        self,
        *,
        query_text: str,
        candidates: list[RetrievalCandidate],
        policy: RetrievalPolicy,
    ) -> tuple[list[RetrievalScoredCandidate], RerankerDiagnostics]:
        started = time.perf_counter()
        scored = self.engine.rerank(candidates=candidates, query_text=query_text, policy=policy)
        return scored, RerankerDiagnostics(
            provider_name=self.provider_name,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            candidate_count=len(candidates),
            reranked_count=len(scored),
            backend="heuristic",
        )


class OpenAICompatibleRerankerProvider:
    provider_name = "openai_compatible"

    def __init__(
        self, *, base_url: str | None, api_key: str | None, timeout_sec: float, model_id: str | None
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.model_id = model_id or "qwen-reranker"
        self.heuristic = HeuristicRerankerProvider()

    def rerank(
        self,
        *,
        query_text: str,
        candidates: list[RetrievalCandidate],
        policy: RetrievalPolicy,
    ) -> tuple[list[RetrievalScoredCandidate], RerankerDiagnostics]:
        if not self.base_url or not candidates:
            scored, diagnostics = self.heuristic.rerank(
                query_text=query_text, candidates=candidates, policy=policy
            )
            diagnostics.provider_name = self.provider_name
            diagnostics.fallback_used = True
            diagnostics.backend = "heuristic_fallback"
            diagnostics.model_id = self.model_id
            return scored, diagnostics

        url = resolve_openai_compatible_endpoint(
            base_url=self.base_url,
            endpoint_path="/chat/completions",
            dependency_name="reranker_base_url",
            missing_message="RERANKER_BASE_URL is required for openai_compatible reranker",
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict semantic reranker. Return JSON only in the form "
                    '{"scores": [{"fragment_id": "...", "score": 0.0-1.0}, ...]}. '
                    "Score each fragment for how well it answers the query. Do not invent fragment ids."
                ),
            },
            {
                "role": "user",
                "content": self._build_user_prompt(query_text=query_text, candidates=candidates),
            },
        ]
        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout_sec) as client:
                response = client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
            raw_content = ((body.get("choices") or [{}])[0].get("message") or {}).get(
                "content"
            ) or "{}"
            parsed = _unwrap_reranker_payload(_extract_json_object(raw_content))
            raw_scores = cast(list[object], parsed.get("scores") or [])
            score_map = {
                str(item.get("fragment_id")): float(item.get("score") or 0.0)
                for item in raw_scores
                if isinstance(item, dict) and item.get("fragment_id")
            }
        except Exception:
            scored, diagnostics = self.heuristic.rerank(
                query_text=query_text, candidates=candidates, policy=policy
            )
            diagnostics.provider_name = self.provider_name
            diagnostics.model_id = self.model_id
            diagnostics.fallback_used = True
            diagnostics.backend = "heuristic_fallback"
            diagnostics.latency_ms = round((time.perf_counter() - started) * 1000, 2)
            return scored, diagnostics

        heuristic_scored, _ = self.heuristic.rerank(
            query_text=query_text, candidates=candidates, policy=policy
        )
        merged: list[RetrievalScoredCandidate] = []
        for item in heuristic_scored:
            llm_score = score_map.get(item.candidate.fragment_id)
            final_score = (
                item.score
                if llm_score is None
                else round((item.score * 0.45) + (llm_score * 0.55), 8)
            )
            merged.append(
                RetrievalScoredCandidate(
                    candidate=item.candidate,
                    score=final_score,
                    lexical_score=item.lexical_score,
                    vector_score=item.vector_score,
                    metadata_score=item.metadata_score,
                    keyword_score=item.keyword_score,
                )
            )
        merged.sort(key=lambda item: item.score, reverse=True)
        merged = merged[: policy.rerank_limit]
        return merged, RerankerDiagnostics(
            provider_name=self.provider_name,
            model_id=self.model_id,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            candidate_count=len(candidates),
            reranked_count=len(merged),
            backend="semantic_llm",
        )

    @staticmethod
    def _build_user_prompt(*, query_text: str, candidates: list[RetrievalCandidate]) -> str:
        lines = [f"Query: {query_text}", "Fragments:"]
        for candidate in candidates:
            title = candidate.title or candidate.fragment_type or "Knowledge fragment"
            lines.append(f"- fragment_id={candidate.fragment_id}")
            lines.append(f"  title={title}")
            lines.append(f"  source_location={candidate.source_location or 'n/a'}")
            lines.append(f"  content={candidate.content[:1200]}")
        return "\n".join(lines)


def _extract_json_object(raw_content: str) -> dict[str, Any]:
    if not isinstance(raw_content, str):
        raise ValueError("Reranker payload is not textual JSON")
    raw = raw_content.strip()
    if not raw:
        raise ValueError("Reranker payload is empty")
    candidates = [raw]
    fenced = _JSON_BLOCK_RE.search(raw)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    inline = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if inline:
        inline_candidate = inline.group(0).strip()
        if inline_candidate not in candidates:
            candidates.append(inline_candidate)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    raise ValueError("Reranker returned invalid JSON")


def _unwrap_reranker_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current: dict[str, Any] = payload
    for _ in range(3):
        if not isinstance(current, dict):
            raise ValueError("Reranker payload is not an object")
        if isinstance(current.get("scores"), list):
            return current
        nested = cast(
            dict[str, Any] | None,
            next(
            (
                current.get(key)
                for key in _RERANKER_WRAPPER_KEYS
                if isinstance(current.get(key), dict)
            ),
            None,
            ),
        )
        if nested is None:
            raise ValueError("Reranker payload is missing scores")
        current = nested
    if isinstance(current.get("scores"), list):
        return current
    raise ValueError("Reranker payload is missing scores")


class RerankerService:
    def __init__(self, settings: Settings) -> None:
        provider = (settings.reranker_provider or "heuristic").strip().lower()
        self.fallback = HeuristicRerankerProvider()
        if provider == "openai_compatible":
            self.provider: RerankerProvider = OpenAICompatibleRerankerProvider(
                base_url=settings.reranker_base_url,
                api_key=settings.reranker_api_key,
                timeout_sec=settings.reranker_timeout_sec,
                model_id=settings.reranker_model_id,
            )
        else:
            self.provider = self.fallback

    def rerank(
        self,
        *,
        query_text: str,
        candidates: list[RetrievalCandidate],
        policy: RetrievalPolicy,
    ) -> tuple[list[RetrievalScoredCandidate], RerankerDiagnostics]:
        return self.provider.rerank(query_text=query_text, candidates=candidates, policy=policy)
