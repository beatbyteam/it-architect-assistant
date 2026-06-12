from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol

import httpx

from app.core.exceptions import DependencyUnavailableError, ValidationError
from app.integrations.generation.contracts import (
    REQUIRED_SECTION_CODES,
    GenerationSolutionPayload,
)
from app.integrations.generation.payload_normalization import (
    _apply_section_guidance,
    _enrich_critical_section_source_refs,
    _enrich_required_generation_lists,
    _extract_json_payload,
    _validate_generation_solution_payload,
)
from app.integrations.openai_compatible import resolve_openai_compatible_endpoint

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetrievedFragment:
    fragment_id: str
    document_id: str
    title: str | None
    content: str
    fragment_type: str | None = None
    source_location: str | None = None
    score: float | None = None
    lexical_score: float | None = None
    vector_score: float | None = None
    keyword_score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProviderCallDiagnostics:
    provider_name: str
    model_id: str
    fallback_used: bool
    latency_ms: float | None = None
    finish_reason: str | None = None


def _is_probe_status_healthy(status_code: int) -> bool:
    if 200 <= int(status_code) < 300:
        return True
    return int(status_code) in {401, 403, 405}


class SolutionProvider(Protocol):
    provider_name: str
    model_id: str

    def generate_solution(
        self, payload: dict[str, Any]
    ) -> tuple[GenerationSolutionPayload, ProviderCallDiagnostics]: ...


def _sanitize_prompt_artifact(prompt_artifact: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(prompt_artifact, dict):
        return None
    allowed_keys = {
        "prompt_version",
        "system_prompt",
        "user_prompt",
        "task_block",
        "context_block",
        "knowledge_block",
        "included_fragment_ids",
        "dropped_fragment_ids",
        "token_budget",
        "retrieval_trace",
        "section_generation_plan",
        "section_readiness",
        "retrieval_contract_version",
        "knowledge_manifest",
    }
    sanitized = {key: prompt_artifact.get(key) for key in allowed_keys if key in prompt_artifact}
    sanitized.setdefault("retrieval_contract_version", "retrieved_fragments_only_v1")
    sanitized["raw_documents_included"] = False
    return sanitized


class HttpJsonSolutionProvider:
    provider_name = "http_json"

    def __init__(
        self,
        *,
        base_url: str | None,
        api_key: str | None = None,
        timeout_sec: float = 60.0,
        model_id: str = "http-json-model",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout_sec = timeout_sec
        self.model_id = model_id
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens

    def generate_solution(
        self, payload: dict[str, Any]
    ) -> tuple[GenerationSolutionPayload, ProviderCallDiagnostics]:
        if not self.base_url:
            raise DependencyUnavailableError(
                "llm_base_url", "LLM_BASE_URL is required for http_json provider"
            )
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        started = time.perf_counter()
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(self.base_url, json=payload, headers=headers)
            response.raise_for_status()
            body: dict[str, Any] = response.json()
        finish_reason = str(body.get("finish_reason") or "completed")
        result = _validate_generation_solution_payload(body)
        return result, ProviderCallDiagnostics(
            provider_name=self.provider_name,
            model_id=str(body.get("model_id") or self.model_id),
            fallback_used=False,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            finish_reason=finish_reason,
        )


class OpenAICompatibleSolutionProvider(HttpJsonSolutionProvider):
    provider_name = "openai_compatible"

    def _resolve_chat_completions_url(self) -> str:
        return resolve_openai_compatible_endpoint(
            base_url=self.base_url,
            endpoint_path="/chat/completions",
            dependency_name="llm_base_url",
            missing_message="LLM_BASE_URL is required for openai_compatible provider",
        )

    def _build_generation_messages(self, payload: dict[str, Any]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (payload.get("prompt_artifact") or {}).get(
                    "system_prompt",
                    " ".join(
                        [
                            "Верни только валидный JSON по контракту архитектурного решения.",
                            (
                                "Используй точные top-level ключи: solution_title,"
                                " executive_summary, sections, components,"
                                " integrations, assumptions, next_steps, risks."
                            ),
                            (
                                "Поле components обязательно и должно содержать"
                                " хотя бы один компонент."
                            ),
                            (
                                "Массив assumptions должен содержать минимум одно конкретное"
                                " допущение по задаче и быть написан на русском."
                            ),
                            (
                                "Массив next_steps должен содержать минимум один конкретный"
                                " следующий шаг на русском."
                            ),
                            (
                                "Risk severity должен быть одним из: critical, major, minor, info."
                                " Не используй low, medium или high."
                            ),
                            (
                                "Каждый риск должен включать русские title, description и mitigation;"
                                " mitigation обязан назвать владельца, конкретное действие,"
                                " контрольную точку проверки и fallback или условие отката."
                            ),
                            (
                                "Каждый component должен содержать component_name, role_description,"
                                " technology_stack, boundary_type, external_flag, and interfaces."
                            ),
                            "Каждый interface item должен включать interface_name.",
                            (
                                "Каждый body_markdown раздела должен быть непустым русским текстом"
                                " с конкретным содержанием."
                            ),
                            (
                                "Критические TOGAF sections general_information,"
                                " business_tasks_description, it_architecture_content,"
                                " business_architecture, data_architecture,"
                                " application_architecture, technology_architecture,"
                                " and additional_information должны включать непустые"
                                " source_refs arrays, если доступны evidence fragments."
                            ),
                        ]
                    ),
                ),
            },
            {
                "role": "user",
                "content": (payload.get("prompt_artifact") or {}).get(
                    "user_prompt", payload.get("task_text", "")
                ),
            },
        ]

    def _build_repair_messages(
        self, *, raw_content: str, validation_error: str
    ) -> list[dict[str, str]]:
        repair_system_prompt = " ".join(
            [
                "Ты исправляешь невалидный JSON для строгого архитектурного контракта.",
                "Верни только один исправленный JSON-объект и ничего больше.",
                ("Не оборачивай объект в ключи architecture, solution, result или payload."),
                (
                    "Используй точные top-level ключи в snake_case: solution_title,"
                    " executive_summary, sections, components, integrations,"
                    " assumptions, next_steps, risks."
                ),
                "Поле components обязательно и должно содержать хотя бы один элемент.",
                (
                    "Массив assumptions должен содержать минимум одно конкретное"
                    " допущение по задаче на русском языке."
                ),
                ("Массив next_steps должен содержать минимум один конкретный следующий шаг."),
                (
                    "Risk severity должен быть одним из: critical, major, minor, info."
                    " Не используй low, medium или high."
                ),
                (
                    "Каждый risk должен включать русские title, description и mitigation;"
                    " mitigation обязан назвать владельца, конкретное действие,"
                    " контрольную точку проверки и fallback или условие отката."
                ),
                (
                    "Если предыдущий JSON пропустил components, но описал архитектуру"
                    " в sections, восстанови top-level массив components из этого содержания."
                ),
                (
                    "Каждый component должен включать component_name, role_description,"
                    " technology_stack, boundary_type, external_flag, and interfaces."
                ),
                "Каждый interface item должен включать interface_name.",
                (
                    "Каждый section должен включать непустой body_markdown с конкретным"
                    " русским содержанием."
                ),
                (
                    "Критические TOGAF sections general_information,"
                    " business_tasks_description, it_architecture_content,"
                    " business_architecture, data_architecture,"
                    " application_architecture, technology_architecture,"
                    " and additional_information должны включать непустые"
                    " source_refs arrays, если evidence доступен."
                ),
                (
                    "Required section_code values: general_information,"
                    " business_tasks_description, it_architecture_content,"
                    " business_architecture, data_architecture,"
                    " application_architecture, technology_architecture,"
                    " additional_information."
                ),
            ]
        )

        repair_user_prompt = (
            "Предыдущий JSON не прошёл валидацию схемы.\n\n"
            f"Ошибка валидации:\n{validation_error}\n\n"
            "Предыдущий JSON:\n"
            f"{raw_content}\n\n"
            "Верни только исправленный JSON, который проходит схему."
        )

        return [
            {"role": "system", "content": repair_system_prompt},
            {"role": "user", "content": repair_user_prompt},
        ]

    def _post_chat_completion(
        self, *, messages: list[dict[str, str]]
    ) -> tuple[str, str, float, str]:
        request_url = self._resolve_chat_completions_url()
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model_id,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            body["temperature"] = float(self.temperature)
        if self.top_p is not None:
            body["top_p"] = float(self.top_p)
        if self.max_tokens is not None:
            body["max_tokens"] = int(self.max_tokens)
        started = time.perf_counter()
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(request_url, json=body, headers=headers)
            response.raise_for_status()
            data = response.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
        finish_reason = str(((data.get("choices") or [{}])[0]).get("finish_reason") or "completed")
        latency_ms = round((time.perf_counter() - started) * 1000, 2)
        resolved_model_id = str(data.get("model") or self.model_id)
        return content, finish_reason, latency_ms, resolved_model_id

    def generate_solution(
        self, payload: dict[str, Any]
    ) -> tuple[GenerationSolutionPayload, ProviderCallDiagnostics]:
        messages = self._build_generation_messages(payload)
        content, finish_reason, latency_ms, resolved_model_id = self._post_chat_completion(
            messages=messages
        )

        try:
            parsed = _extract_json_payload(content)
            result = _validate_generation_solution_payload(parsed)
            return result, ProviderCallDiagnostics(
                provider_name=self.provider_name,
                model_id=resolved_model_id,
                fallback_used=False,
                latency_ms=latency_ms,
                finish_reason=finish_reason,
            )
        except ValidationError as exc:
            logger.warning(
                "llm_output_needs_repair",
                extra={
                    "stage": "llm_call",
                    "stage_status": "repair_requested",
                    "provider_name": self.provider_name,
                    "model_id": self.model_id,
                    "finish_reason": str(finish_reason),
                    "raw_content_preview": content[:4000],
                    "validation_error": str(exc),
                },
            )

            repair_messages = self._build_repair_messages(
                raw_content=content,
                validation_error=str(exc),
            )
            repaired_content, repaired_finish_reason, repaired_latency_ms, repaired_model_id = (
                self._post_chat_completion(messages=repair_messages)
            )

            try:
                repaired_parsed = _extract_json_payload(repaired_content)
                repaired_result = _validate_generation_solution_payload(repaired_parsed)
                return repaired_result, ProviderCallDiagnostics(
                    provider_name=self.provider_name,
                    model_id=repaired_model_id,
                    fallback_used=False,
                    latency_ms=latency_ms + repaired_latency_ms,
                    finish_reason=repaired_finish_reason,
                )
            except ValidationError:
                logger.error(
                    "llm_output_validation_failed",
                    extra={
                        "stage": "llm_call",
                        "stage_status": "invalid_output",
                        "provider_name": self.provider_name,
                        "model_id": self.model_id,
                        "finish_reason": str(repaired_finish_reason),
                        "raw_content_preview": repaired_content[:4000],
                    },
                )
                raise


class LocalInferenceSolutionProvider(OpenAICompatibleSolutionProvider):
    provider_name = "local_inference"


class LLMGateway:
    def __init__(
        self,
        *,
        provider: str = "openai_compatible",
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_sec: float = 60.0,
        model_id: str | None = None,
        fallback_provider: str | None = None,
        fallback_base_url: str | None = None,
        fallback_api_key: str | None = None,
        fallback_model_id: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.last_call_diagnostics: dict[str, Any] = {}
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.primary_provider = self._build_provider(
            provider_name=provider,
            base_url=base_url,
            api_key=api_key,
            timeout_sec=timeout_sec,
            model_id=model_id,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        self.fallback_provider = None
        if fallback_provider:
            self.fallback_provider = self._build_provider(
                provider_name=fallback_provider,
                base_url=fallback_base_url,
                api_key=fallback_api_key,
                timeout_sec=timeout_sec,
                model_id=fallback_model_id,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
            )

    def generate_solution(
        self,
        *,
        task_title: str,
        task_text: str,
        context_items: list[str],
        retrieved_fragments: list[RetrievedFragment],
        prompt_artifact: dict[str, Any] | None = None,
    ) -> GenerationSolutionPayload:
        sanitized_prompt_artifact = _sanitize_prompt_artifact(prompt_artifact)
        payload = {
            "task_title": task_title,
            "task_text": task_text,
            "context_items": context_items,
            "retrieved_fragments": [asdict(item) for item in retrieved_fragments],
            "prompt_artifact": sanitized_prompt_artifact,
        }
        failures: list[dict[str, Any]] = []
        providers = [self.primary_provider]
        if self.fallback_provider is not None:
            providers.append(self.fallback_provider)
        for index, provider in enumerate(providers):
            try:
                result, diagnostics = provider.generate_solution(payload)
                diagnostics.fallback_used = index > 0
                self.last_call_diagnostics = {
                    "provider_name": diagnostics.provider_name,
                    "model_id": diagnostics.model_id,
                    "fallback_used": diagnostics.fallback_used,
                    "finish_reason": diagnostics.finish_reason,
                    "latency_ms": diagnostics.latency_ms,
                    "attempt_count": index + 1,
                    "failures": failures,
                    "retrieval_context_contract": (sanitized_prompt_artifact or {}).get(
                        "retrieval_contract_version"
                    ),
                    "retrieved_fragment_count": len(retrieved_fragments),
                    "raw_documents_included": False,
                    "request_options": {
                        "temperature": self.temperature,
                        "top_p": self.top_p,
                        "max_tokens": self.max_tokens,
                    },
                }
                result = _enrich_required_generation_lists(
                    result,
                    task_text=task_text,
                    context_items=context_items,
                )
                result = _enrich_critical_section_source_refs(
                    result,
                    retrieved_fragments=retrieved_fragments,
                )
                result, section_guidance = _apply_section_guidance(
                    result,
                    task_title=task_title,
                    task_text=task_text,
                    context_items=context_items,
                    retrieved_fragments=retrieved_fragments,
                )
                result = _enrich_critical_section_source_refs(
                    result,
                    retrieved_fragments=retrieved_fragments,
                )
                self.last_call_diagnostics = {
                    **self.last_call_diagnostics,
                    "derived_assumptions": len(result.assumptions),
                    "derived_next_steps": len(result.next_steps),
                    "critical_sections_with_refs": sum(
                        1
                        for section in result.sections
                        if section.section_code in REQUIRED_SECTION_CODES
                        and bool(section.source_refs)
                    ),
                    "section_guidance": section_guidance,
                }
                logger.info(
                    "llm_prompt_artifact",
                    extra={"stage": "llm_call", "stage_status": diagnostics.provider_name},
                )
                return result
            except ValidationError as exc:
                failures.append(
                    {
                        "provider": provider.provider_name,
                        "error": str(exc),
                        "error_code": getattr(exc, "error_code", "LLM_OUTPUT_SCHEMA_INVALID"),
                        "exception": type(exc).__name__,
                    }
                )
                if index == len(providers) - 1:
                    raise
                logger.warning(
                    "llm_provider_validation_failed",
                    extra={
                        "stage": "llm_call",
                        "stage_status": "invalid_output",
                        "provider_name": provider.provider_name,
                        "model_id": getattr(provider, "model_id", None),
                        "error_code": getattr(exc, "error_code", "LLM_OUTPUT_SCHEMA_INVALID"),
                    },
                )
                continue
            except Exception as exc:  # pragma: no cover - defensive fallback path
                logger.exception(
                    "llm_provider_failed",
                    extra={
                        "stage": "llm_call",
                        "stage_status": "failed",
                        "provider_name": provider.provider_name,
                        "model_id": getattr(provider, "model_id", None),
                    },
                )
                failures.append(
                    {
                        "provider": provider.provider_name,
                        "error": str(exc),
                        "exception": type(exc).__name__,
                    }
                )
                continue
        raise DependencyUnavailableError("llm_gateway", f"All LLM providers failed: {failures}")

    def healthcheck(self) -> dict[str, Any]:
        primary = {
            "provider_name": getattr(self.primary_provider, "provider_name", "unknown"),
            "model_id": getattr(self.primary_provider, "model_id", None),
        }
        base_url = getattr(self.primary_provider, "base_url", None)
        if (
            primary["provider_name"] in {"http_json", "openai_compatible", "local_inference"}
            and not base_url
        ):
            return {
                **primary,
                "healthy": False,
                "details": "LLM provider base URL is not configured",
            }
        try:
            if base_url:
                request_url = base_url
                resolver = getattr(self.primary_provider, "_resolve_chat_completions_url", None)
                if callable(resolver):
                    request_url = resolver()
                with httpx.Client(timeout=5.0, follow_redirects=True) as client:
                    response = client.get(request_url)
                healthy = _is_probe_status_healthy(response.status_code)
                return {
                    **primary,
                    "healthy": healthy,
                    "status_code": response.status_code,
                    "endpoint": request_url,
                    "details": "LLM endpoint responded"
                    if healthy
                    else f"LLM endpoint returned probe status {response.status_code}",
                }
            return {
                **primary,
                "healthy": True,
                "details": "Local provider does not require external health probe",
            }
        except Exception as exc:  # pragma: no cover - network dependent
            return {
                **primary,
                "healthy": False,
                "details": str(exc),
                "exception": type(exc).__name__,
            }

    def _build_provider(
        self,
        *,
        provider_name: str,
        base_url: str | None,
        api_key: str | None,
        timeout_sec: float,
        model_id: str | None,
        temperature: float | None,
        top_p: float | None,
        max_tokens: int | None,
    ) -> SolutionProvider:
        resolved_model_id = model_id or f"{provider_name}-default"
        if provider_name == "http_json":
            return HttpJsonSolutionProvider(
                base_url=base_url,
                api_key=api_key,
                timeout_sec=timeout_sec,
                model_id=resolved_model_id,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
            )
        if provider_name == "openai_compatible":
            return OpenAICompatibleSolutionProvider(
                base_url=base_url,
                api_key=api_key,
                timeout_sec=timeout_sec,
                model_id=resolved_model_id,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
            )
        if provider_name in {"local_inference", "ollama", "local_openai_compatible"}:
            return LocalInferenceSolutionProvider(
                base_url=base_url,
                api_key=api_key,
                timeout_sec=timeout_sec,
                model_id=resolved_model_id,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
            )
        raise DependencyUnavailableError(
            "llm_provider",
            f"Unsupported provider: {provider_name}",
            message=f"Unsupported provider: {provider_name}",
        )
