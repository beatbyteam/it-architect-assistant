from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, cast

import httpx

from app.db.enums import DocumentType, ExtractedKnowledgeType, ExtractionQualityStatus
from app.integrations.openai_compatible import resolve_openai_compatible_endpoint

_RULE_MARKERS = (
    "must",
    "shall",
    "required",
    "should",
    "обязан",
    "должен",
    "необходимо",
    "обязательно",
    "не должен",
    "запрещено",
)
_CONSTRAINT_MARKERS = (
    "constraint",
    "limitation",
    "cannot",
    "must not",
    "shall not",
    "не может",
    "огранич",
    "запрещено",
)
_INTEGRATION_MARKERS = (
    "api",
    "rest",
    "grpc",
    "kafka",
    "rabbitmq",
    "webhook",
    "queue",
    "topic",
    "message",
    "integration",
    "endpoint",
    "http",
    "https",
    "sync",
    "batch",
    "интеграц",
)
_TECH_MARKERS = (
    "postgres",
    "redis",
    "docker",
    "kubernetes",
    "tls",
    "oauth",
    "sso",
    "ldap",
    "nginx",
    "fastapi",
    "react",
    "oracle",
    "mysql",
)
_RISK_MARKERS = ("risk", "dependency", "assumption", "uncertainty", "риск", "зависим", "допущен")
_TERM_RE = re.compile(r"^(?P<term>[A-ZА-Я][\w\- /]{1,120})\s*(?:[:\-—]|is)\s*(?P<definition>.+)$")
_RELATION_RE = re.compile(
    r"(?P<src>[A-ZА-Я][\w .\-/]{1,80})\s*(?:->|→|to)\s*(?P<dst>[A-ZА-Я][\w .\-/]{1,80})",
    re.IGNORECASE,
)
_ENDPOINT_RE = re.compile(r"\b(GET|POST|PUT|PATCH|DELETE)\s+(/\S+)")
_ALLOWED_ITEM_TYPES = {item.value: item for item in ExtractedKnowledgeType}
_ALLOWED_QUALITY_STATUSES = {item.value: item for item in ExtractionQualityStatus}
_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
_LLM_EXTRACTION_WRAPPER_KEYS = ("result", "payload", "data", "response", "extraction")
_LLM_CHUNK_BATCH_SIZE = 4
_LLM_CHUNK_CHAR_LIMIT = 4000


@dataclass(slots=True)
class DocumentMemoryLlmConfig:
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_id: str | None = None
    timeout_sec: float = 30.0

    @classmethod
    def from_settings(cls, settings: Any | None) -> DocumentMemoryLlmConfig | None:
        if settings is None:
            return None
        provider = (getattr(settings, "llm_provider", None) or "").strip().lower()
        base_url = getattr(settings, "llm_base_url", None)
        model_id = getattr(settings, "llm_model_id", None)
        if provider in {"", "statistical"} or not base_url or not model_id:
            return None
        return cls(
            provider=provider,
            base_url=base_url,
            api_key=getattr(settings, "llm_api_key", None),
            model_id=model_id,
            timeout_sec=float(getattr(settings, "llm_timeout_sec", 30.0) or 30.0),
        )

    def is_available(self) -> bool:
        return bool(
            self.base_url
            and self.model_id
            and (self.provider or "").strip().lower() not in {"", "statistical"}
        )


@dataclass(slots=True)
class ExtractedKnowledgeCandidate:
    item_type: ExtractedKnowledgeType
    title: str | None
    content: str
    normalized_value: str | None = None
    source_location: str | None = None
    confidence_score: float | None = None
    quality_status: ExtractionQualityStatus = ExtractionQualityStatus.EXTRACTED
    evidence_quote: str | None = None
    structured_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ExtractedDocumentMemory:
    summary: str
    items: list[ExtractedKnowledgeCandidate]
    counters: dict[str, int]
    extraction_method: str = "heuristic"
    fallback_applied: bool = False
    llm_attempted: bool = False
    fallback_reason: str | None = None


def extract_document_memory(
    *,
    document_title: str,
    document_type: DocumentType,
    normalized_text: str,
    chunks: list[dict[str, Any]],
    llm_config: DocumentMemoryLlmConfig | None = None,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> ExtractedDocumentMemory:
    items: list[ExtractedKnowledgeCandidate]
    summary_text: str

    llm_memory: ExtractedDocumentMemory | None = None
    llm_attempted = bool(llm_config is not None and llm_config.is_available())
    fallback_reason: str | None = None
    if llm_attempted:
        try:
            assert llm_config is not None
            llm_memory = _extract_document_memory_with_llm(
                document_title=document_title,
                document_type=document_type,
                normalized_text=normalized_text,
                chunks=chunks,
                llm_config=llm_config,
                progress_callback=progress_callback,
            )
        except Exception as exc:
            fallback_reason = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            llm_memory = None

    if llm_memory is not None:
        items = llm_memory.items
        summary_text = llm_memory.summary
        extraction_method = "llm"
        fallback_applied = False
    else:
        extraction_method = "heuristic"
        fallback_applied = llm_attempted
        items = []
        for chunk in chunks:
            chunk_content = str(chunk.get("content") or "").strip()
            if not chunk_content:
                continue
            chunk_title = str(chunk.get("title") or document_title or "").strip() or None
            source_location = chunk.get("source_location")
            items.extend(
                _extract_from_chunk(
                    document_type=document_type,
                    document_title=document_title,
                    chunk_title=chunk_title,
                    chunk_content=chunk_content,
                    source_location=source_location,
                )
            )
        summary_text = _build_summary(normalized_text, document_title=document_title)
        items.insert(
            0,
            ExtractedKnowledgeCandidate(
                item_type=ExtractedKnowledgeType.SUMMARY,
                title=document_title,
                content=summary_text,
                source_location=chunks[0].get("source_location") if chunks else "document:summary",
                confidence_score=0.92,
                quality_status=ExtractionQualityStatus.INFERRED,
                evidence_quote=_truncate(normalized_text, 260),
                structured_payload={
                    "document_title": document_title,
                    "document_type": document_type.value,
                    "extraction_method": "heuristic",
                },
            ),
        )

    deduped: list[ExtractedKnowledgeCandidate] = []
    seen: set[tuple[str, str, str]] = set()
    for item in items:
        sig = (
            item.item_type.value,
            (item.normalized_value or item.title or "").casefold(),
            item.content.casefold(),
        )
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(item)
    counters: dict[str, int] = {}
    for item in deduped:
        counters[item.item_type.value] = counters.get(item.item_type.value, 0) + 1
    return ExtractedDocumentMemory(
        summary=summary_text,
        items=deduped,
        counters=dict(sorted(counters.items())),
        extraction_method=extraction_method,
        fallback_applied=fallback_applied,
        llm_attempted=llm_attempted,
        fallback_reason=fallback_reason,
    )


def _extract_document_memory_with_llm(
    *,
    document_title: str,
    document_type: DocumentType,
    normalized_text: str,
    chunks: list[dict[str, Any]],
    llm_config: DocumentMemoryLlmConfig,
    progress_callback: Callable[[dict[str, object]], None] | None = None,
) -> ExtractedDocumentMemory:
    request_url = _resolve_chat_completions_url(llm_config.base_url or "")
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if llm_config.api_key:
        headers["Authorization"] = f"Bearer {llm_config.api_key}"
    serialized_chunks = [
        {
            "document_chunk_id": str(chunk.get("document_chunk_id") or ""),
            "title": str(chunk.get("title") or "").strip() or None,
            "source_location": str(chunk.get("source_location") or "").strip() or None,
            "content": _truncate(str(chunk.get("content") or ""), _LLM_CHUNK_CHAR_LIMIT),
        }
        for chunk in chunks
        if str(chunk.get("content") or "").strip()
    ]
    if not serialized_chunks and normalized_text.strip():
        serialized_chunks.append(
            {
                "document_chunk_id": "",
                "title": document_title,
                "source_location": "document:summary",
                "content": _truncate(normalized_text, _LLM_CHUNK_CHAR_LIMIT),
            }
        )
    chunk_batches = _batch_items(serialized_chunks, _LLM_CHUNK_BATCH_SIZE)
    batch_count = len(chunk_batches)
    batch_memories: list[ExtractedDocumentMemory] = []
    if progress_callback is not None:
        progress_callback(
            {
                "operation": "document_memory_llm",
                "status": "started",
                "completed_batches": 0,
                "total_batches": batch_count,
                "completed_chunks": 0,
                "total_chunks": len(serialized_chunks),
                "batch_size": _LLM_CHUNK_BATCH_SIZE,
            }
        )
    with httpx.Client(timeout=llm_config.timeout_sec) as client:
        for batch_index, chunk_batch in enumerate(chunk_batches, start=1):
            if progress_callback is not None:
                progress_callback(
                    {
                        "operation": "document_memory_llm",
                        "status": "running",
                        "current_batch": batch_index,
                        "completed_batches": batch_index - 1,
                        "total_batches": batch_count,
                        "completed_chunks": min(
                            (batch_index - 1) * _LLM_CHUNK_BATCH_SIZE, len(serialized_chunks)
                        ),
                        "total_chunks": len(serialized_chunks),
                        "batch_size": len(chunk_batch),
                    }
                )
            batch_memories.append(
                _extract_document_memory_batch_with_llm(
                    client=client,
                    request_url=request_url,
                    headers=headers,
                    llm_config=llm_config,
                    document_title=document_title,
                    document_type=document_type,
                    normalized_text=normalized_text,
                    chunk_batch=chunk_batch,
                    batch_index=batch_index,
                    batch_count=batch_count,
                )
            )
            if progress_callback is not None:
                progress_callback(
                    {
                        "operation": "document_memory_llm",
                        "status": "completed",
                        "current_batch": batch_index,
                        "completed_batches": batch_index,
                        "total_batches": batch_count,
                        "completed_chunks": min(
                            batch_index * _LLM_CHUNK_BATCH_SIZE, len(serialized_chunks)
                        ),
                        "total_chunks": len(serialized_chunks),
                        "batch_size": len(chunk_batch),
                    }
                )
    if not batch_memories:
        raise ValueError("LLM document memory payload is missing summary/items")
    batch_summaries = [memory.summary for memory in batch_memories if memory.summary.strip()]
    summary_text = _merge_summaries(batch_summaries, normalized_text, document_title=document_title)
    items: list[ExtractedKnowledgeCandidate] = []
    for memory in batch_memories:
        items.extend(
            item for item in memory.items if item.item_type != ExtractedKnowledgeType.SUMMARY
        )
    items.insert(
        0,
        ExtractedKnowledgeCandidate(
            item_type=ExtractedKnowledgeType.SUMMARY,
            title=document_title,
            content=summary_text,
            source_location=chunk_batch[0].get("source_location")
            if chunk_batch
            else "document:summary",
            confidence_score=0.9,
            quality_status=ExtractionQualityStatus.EXTRACTED,
            evidence_quote=_truncate(normalized_text, 260),
            structured_payload={
                "document_title": document_title,
                "document_type": document_type.value,
                "extraction_method": "llm",
                "extraction_batches": batch_count,
                "covered_chunk_count": len(serialized_chunks),
            },
        ),
    )
    return ExtractedDocumentMemory(
        summary=summary_text,
        items=items,
        counters={},
        extraction_method="llm",
        fallback_applied=False,
        llm_attempted=True,
        fallback_reason=None,
    )


def _extract_document_memory_batch_with_llm(
    *,
    client: httpx.Client,
    request_url: str,
    headers: dict[str, str],
    llm_config: DocumentMemoryLlmConfig,
    document_title: str,
    document_type: DocumentType,
    normalized_text: str,
    chunk_batch: list[dict[str, Any]],
    batch_index: int,
    batch_count: int,
) -> ExtractedDocumentMemory:
    body = {
        "model": llm_config.model_id,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You extract structured knowledge from enterprise architecture documents. "
                    "Return only one JSON object with keys summary and items. "
                    "summary must be a short grounded summary string. "
                    "items must be an array of objects. Each item object may contain: "
                    "item_type, title, content, normalized_value, source_location, confidence_score, quality_status, evidence_quote, structured_payload. "
                    "Allowed item_type values: summary, normative_rule, architectural_principle, constraint, mandatory_requirement, entity, entity_relation, integration_requirement, technology_standard, term, risk. "
                    "Allowed quality_status values: extracted, inferred, review_required, failed. "
                    "Every item must cite a source_location from the provided chunks when possible. "
                    "Do not invent facts that are absent from the document. "
                    "You may be processing one batch of a larger document, so extract all important facts from the provided batch. "
                    "Do not add summary items to items; use the top-level summary field for the batch summary. "
                    "Prefer concise grounded facts over generic summaries."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "document_title": document_title,
                        "document_type": document_type.value,
                        "chunk_batch_index": batch_index,
                        "chunk_batch_count": batch_count,
                        "chunks": chunk_batch,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    response = client.post(request_url, json=body, headers=headers)
    response.raise_for_status()
    payload = response.json()
    raw_content = ((payload.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
    parsed = _unwrap_llm_extraction_payload(_extract_json_object(raw_content))
    if not str(parsed.get("summary") or "").strip() and not isinstance(parsed.get("items"), list):
        raise ValueError("LLM document memory payload is missing summary/items")
    summary_text = str(parsed.get("summary") or "").strip() or _build_summary(
        normalized_text, document_title=document_title
    )
    items: list[ExtractedKnowledgeCandidate] = []
    for raw_item in parsed.get("items") or []:
        if not isinstance(raw_item, dict):
            continue
        item_type_value = str(raw_item.get("item_type") or "").strip().lower()
        item_type = _ALLOWED_ITEM_TYPES.get(item_type_value)
        if item_type is None:
            continue
        content = str(raw_item.get("content") or "").strip()
        if not content:
            continue
        quality_value = (
            str(raw_item.get("quality_status") or ExtractionQualityStatus.EXTRACTED.value)
            .strip()
            .lower()
        )
        quality_status = _ALLOWED_QUALITY_STATUSES.get(
            quality_value, ExtractionQualityStatus.EXTRACTED
        )
        confidence_raw = raw_item.get("confidence_score")
        confidence_score: float | None
        try:
            confidence_score = (
                round(float(confidence_raw), 4) if confidence_raw is not None else None
            )
        except (TypeError, ValueError):
            confidence_score = None
        source_location = str(raw_item.get("source_location") or "").strip() or None
        evidence_quote = str(raw_item.get("evidence_quote") or "").strip() or None
        raw_structured_payload = raw_item.get("structured_payload")
        structured_payload: dict[str, Any] = (
            dict(cast(dict[str, Any], raw_structured_payload))
            if isinstance(raw_structured_payload, dict)
            else {}
        )
        structured_payload = {
            **structured_payload,
            "extraction_method": "llm",
            "chunk_batch_index": batch_index,
            "chunk_batch_count": batch_count,
        }
        items.append(
            ExtractedKnowledgeCandidate(
                item_type=item_type,
                title=str(raw_item.get("title") or "").strip() or None,
                content=content,
                normalized_value=str(raw_item.get("normalized_value") or "").strip() or None,
                source_location=source_location,
                confidence_score=confidence_score,
                quality_status=quality_status,
                evidence_quote=evidence_quote,
                structured_payload=structured_payload,
            )
        )
    items.insert(
        0,
        ExtractedKnowledgeCandidate(
            item_type=ExtractedKnowledgeType.SUMMARY,
            title=document_title,
            content=summary_text,
            source_location=chunk_batch[0].get("source_location")
            if chunk_batch
            else "document:summary",
            confidence_score=0.9,
            quality_status=ExtractionQualityStatus.EXTRACTED,
            evidence_quote=_truncate(normalized_text, 260),
            structured_payload={
                "document_title": document_title,
                "document_type": document_type.value,
                "extraction_method": "llm",
                "chunk_batch_index": batch_index,
                "chunk_batch_count": batch_count,
            },
        ),
    )
    return ExtractedDocumentMemory(
        summary=summary_text,
        items=items,
        counters={},
        extraction_method="llm",
        fallback_applied=False,
        llm_attempted=True,
        fallback_reason=None,
    )


def _batch_items(items: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    if batch_size <= 0:
        return [items] if items else []
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _merge_summaries(summaries: list[str], normalized_text: str, *, document_title: str) -> str:
    clean_summaries = [summary.strip() for summary in summaries if summary.strip()]
    if not clean_summaries:
        return _build_summary(normalized_text, document_title=document_title)
    return "\n\n".join(clean_summaries)


def _resolve_chat_completions_url(base_url: str) -> str:
    return resolve_openai_compatible_endpoint(
        base_url=base_url,
        endpoint_path="/chat/completions",
        dependency_name="llm_base_url",
        missing_message="LLM_BASE_URL is required for document memory extraction",
    )


def _extract_json_object(raw_content: str) -> dict[str, Any]:
    if not isinstance(raw_content, str):
        return {}
    raw = raw_content.strip()
    if not raw:
        return {}
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
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            continue
    return {}


def _unwrap_llm_extraction_payload(payload: dict[str, Any]) -> dict[str, Any]:
    current = payload
    for _ in range(3):
        if not isinstance(current, dict):
            return {}
        if "summary" in current or "items" in current:
            return current
        nested = next(
            (
                current.get(key)
                for key in _LLM_EXTRACTION_WRAPPER_KEYS
                if isinstance(current.get(key), dict)
            ),
            None,
        )
        if nested is None:
            return current
        current = nested
    return current if isinstance(current, dict) else {}


def _extract_from_chunk(
    *,
    document_type: DocumentType,
    document_title: str,
    chunk_title: str | None,
    chunk_content: str,
    source_location: str | None,
) -> list[ExtractedKnowledgeCandidate]:
    items: list[ExtractedKnowledgeCandidate] = []
    sentences = _split_sentences(chunk_content)

    if document_type == DocumentType.API:
        for match in _ENDPOINT_RE.finditer(chunk_content):
            method, path = match.groups()
            items.append(
                ExtractedKnowledgeCandidate(
                    item_type=ExtractedKnowledgeType.INTEGRATION_REQUIREMENT,
                    title=f"{method} {path}",
                    content=f"API contract exposes endpoint {method} {path}",
                    normalized_value=f"{method} {path}",
                    source_location=source_location,
                    confidence_score=0.94,
                    evidence_quote=match.group(0),
                    structured_payload={
                        "http_method": method,
                        "path": path,
                        "document_title": document_title,
                        "extraction_method": "heuristic",
                    },
                )
            )

    for line in chunk_content.splitlines():
        term_match = _TERM_RE.match(line.strip())
        if term_match:
            term = term_match.group("term").strip()
            definition = term_match.group("definition").strip()
            if len(term.split()) <= 10 and len(definition) >= 8:
                items.append(
                    ExtractedKnowledgeCandidate(
                        item_type=ExtractedKnowledgeType.TERM,
                        title=term,
                        content=definition,
                        normalized_value=term,
                        source_location=source_location,
                        confidence_score=0.88,
                        evidence_quote=_truncate(line, 220),
                        structured_payload={"term": term, "extraction_method": "heuristic"},
                    )
                )

    entity_candidates: set[str] = set()
    if chunk_title and len(chunk_title) > 3:
        entity_candidates.add(chunk_title.strip())
    for match in re.finditer(
        r"\b([A-ZА-Я][A-Za-zА-Яа-я0-9\-]{2,}(?:\s+[A-ZА-Я][A-Za-zА-Яа-я0-9\-]{2,}){0,3})\b",
        chunk_content,
    ):
        entity_candidates.add(match.group(1).strip())
    for entity in sorted(entity_candidates)[:6]:
        items.append(
            ExtractedKnowledgeCandidate(
                item_type=ExtractedKnowledgeType.ENTITY,
                title=entity,
                content=f"Entity referenced in document '{document_title}'",
                normalized_value=entity,
                source_location=source_location,
                confidence_score=0.62,
                quality_status=ExtractionQualityStatus.INFERRED,
                evidence_quote=_truncate(chunk_content, 220),
                structured_payload={"entity_name": entity, "extraction_method": "heuristic"},
            )
        )

    for sentence in sentences:
        lowered = sentence.casefold()
        if any(marker in lowered for marker in _RISK_MARKERS):
            items.append(
                ExtractedKnowledgeCandidate(
                    ExtractedKnowledgeType.RISK,
                    _derive_title(sentence),
                    sentence,
                    source_location=source_location,
                    confidence_score=0.79,
                    evidence_quote=sentence,
                    structured_payload={"category": "risk", "extraction_method": "heuristic"},
                )
            )
        if any(marker in lowered for marker in _CONSTRAINT_MARKERS):
            items.append(
                ExtractedKnowledgeCandidate(
                    ExtractedKnowledgeType.CONSTRAINT,
                    _derive_title(sentence),
                    sentence,
                    source_location=source_location,
                    confidence_score=0.86,
                    evidence_quote=sentence,
                    structured_payload={"category": "constraint", "extraction_method": "heuristic"},
                )
            )
        if any(marker in lowered for marker in _RULE_MARKERS):
            item_type = (
                ExtractedKnowledgeType.NORMATIVE_RULE
                if document_type == DocumentType.NORMATIVE
                else ExtractedKnowledgeType.MANDATORY_REQUIREMENT
            )
            if "principle" in lowered or "принцип" in lowered:
                item_type = ExtractedKnowledgeType.ARCHITECTURAL_PRINCIPLE
            items.append(
                ExtractedKnowledgeCandidate(
                    item_type,
                    _derive_title(sentence),
                    sentence,
                    source_location=source_location,
                    confidence_score=0.9 if document_type == DocumentType.NORMATIVE else 0.82,
                    evidence_quote=sentence,
                    structured_payload={
                        "category": item_type.value,
                        "extraction_method": "heuristic",
                    },
                )
            )
        if any(marker in lowered for marker in _INTEGRATION_MARKERS):
            items.append(
                ExtractedKnowledgeCandidate(
                    ExtractedKnowledgeType.INTEGRATION_REQUIREMENT,
                    _derive_title(sentence),
                    sentence,
                    source_location=source_location,
                    confidence_score=0.8,
                    evidence_quote=sentence,
                    structured_payload={
                        "category": "integration",
                        "extraction_method": "heuristic",
                    },
                )
            )
        if any(marker in lowered for marker in _TECH_MARKERS):
            items.append(
                ExtractedKnowledgeCandidate(
                    ExtractedKnowledgeType.TECHNOLOGY_STANDARD,
                    _derive_title(sentence),
                    sentence,
                    source_location=source_location,
                    confidence_score=0.78,
                    evidence_quote=sentence,
                    structured_payload={
                        "category": "technology_standard",
                        "extraction_method": "heuristic",
                    },
                )
            )
        relation = _RELATION_RE.search(sentence)
        if relation:
            items.append(
                ExtractedKnowledgeCandidate(
                    item_type=ExtractedKnowledgeType.ENTITY_RELATION,
                    title=f"{relation.group('src').strip()} -> {relation.group('dst').strip()}",
                    content=sentence,
                    normalized_value=f"{relation.group('src').strip()}->{relation.group('dst').strip()}",
                    source_location=source_location,
                    confidence_score=0.73,
                    evidence_quote=sentence,
                    structured_payload={
                        "from": relation.group("src").strip(),
                        "to": relation.group("dst").strip(),
                        "extraction_method": "heuristic",
                    },
                )
            )
    return items


def _split_sentences(text: str) -> list[str]:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return []
    return [
        item.strip(" -•\n\t")
        for item in re.split(r"(?<=[.!?;])\s+", collapsed)
        if len(item.strip(" -•\n\t")) >= 20
    ][:20]


def _build_summary(text: str, *, document_title: str) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return f"Document '{document_title}' was normalized but no clear narrative summary could be extracted."
    return " ".join(sentences[:2])[:800]


def _derive_title(text: str) -> str:
    return " ".join(re.sub(r"\s+", " ", text).strip().split()[:8])[:120] or "Extracted knowledge"


def _truncate(text: str, limit: int) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"
