from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha1
from statistics import mean
from typing import TYPE_CHECKING, Any

from app.db.enums import DocumentType, FragmentType, NormativeRuleStatus, RuleCategory, Severity

if TYPE_CHECKING:
    from app.db.models.knowledge import NormativeRule


@dataclass(slots=True)
class ChunkedText:
    title: str | None
    content: str
    source_location: str | None
    fragment_type: FragmentType
    metadata: dict[str, object] = field(default_factory=dict)


RULE_KEYWORDS = (
    "must",
    "shall",
    "should",
    "required",
    "must not",
    "shall not",
    "обязан",
    "должен",
    "необходимо",
    "обязательно",
    "не должен",
    "запрещено",
)
NEGATION_KEYWORDS = (
    "must not",
    "shall not",
    "not ",
    "не ",
    "не должен",
    "запрещено",
    "forbidden",
    "forbid",
)
HEADING_RE = re.compile(r"^(#+\s+.+|\d+(?:\.\d+)*\s+.+|[A-Z][^\n]{0,80}:)$", re.MULTILINE)
API_SPLIT_RE = re.compile(r"(?=\b(?:GET|POST|PUT|PATCH|DELETE)\s+/)")
TABLE_LINE_RE = re.compile(r"\|.+\|")
RULE_SPLIT_RE = re.compile(r"\n\s*(?:[-*•]|\d+[\).])\s+")
NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)
TOKEN_RE = re.compile(r"\S+", re.UNICODE)


CHUNKING_POLICY_VERSION = "chunking-policy-v4-token-aware"

DOCUMENT_BASE_WEIGHTS: dict[DocumentType, float] = {
    DocumentType.NORMATIVE: 1.2,
    DocumentType.API: 1.1,
    DocumentType.ARCHITECTURE: 1.05,
    DocumentType.TECHNOLOGY: 1.0,
    DocumentType.OTHER: 0.95,
}

DOCUMENT_TARGET_TOKENS: dict[DocumentType, int] = {
    DocumentType.NORMATIVE: 320,
    DocumentType.API: 360,
    DocumentType.ARCHITECTURE: 480,
    DocumentType.TECHNOLOGY: 420,
    DocumentType.OTHER: 400,
}


@dataclass(slots=True)
class _SectionSeed:
    heading: str | None
    content: str
    source_location: str | None
    metadata: dict[str, Any]


def estimate_token_count(text: str) -> int:
    return len(TOKEN_RE.findall(text or ""))


def summarize_chunk_distribution(chunks: list[ChunkedText]) -> dict[str, object]:
    token_counts = [estimate_token_count(chunk.content) for chunk in chunks]
    if not token_counts:
        return {
            "chunk_count": 0,
            "avg_tokens": 0,
            "max_tokens": 0,
            "min_tokens": 0,
            "total_tokens": 0,
            "title_coverage": 0.0,
        }
    titled = sum(1 for chunk in chunks if chunk.title)
    return {
        "chunk_count": len(chunks),
        "avg_tokens": round(mean(token_counts), 2),
        "max_tokens": max(token_counts),
        "min_tokens": min(token_counts),
        "total_tokens": sum(token_counts),
        "title_coverage": round(titled / len(chunks), 4),
    }


# Legacy-compatible API retained for older call sites.
def chunk_text(
    text: str,
    *,
    max_chars: int = 1200,
    document_type: DocumentType = DocumentType.OTHER,
) -> list[ChunkedText]:
    return chunk_document(
        text,
        max_chars=max_chars,
        document_type=document_type,
        sections=None,
        target_tokens=None,
        overlap_tokens=None,
        document_title=None,
    )


def chunk_document(
    text: str,
    *,
    max_chars: int = 1200,
    document_type: DocumentType = DocumentType.OTHER,
    sections: list[Any] | None = None,
    target_tokens: int | None = None,
    overlap_tokens: int | None = None,
    document_title: str | None = None,
) -> list[ChunkedText]:
    resolved_target_tokens = max(
        120, int(target_tokens or DOCUMENT_TARGET_TOKENS.get(document_type, 400))
    )
    resolved_overlap_tokens = (
        max(0, int(overlap_tokens))
        if overlap_tokens is not None
        else max(12, round(resolved_target_tokens * 0.05))
    )
    if document_type == DocumentType.NORMATIVE:
        return _chunk_normative(
            text,
            max_chars=max_chars,
            sections=sections,
            target_tokens=resolved_target_tokens,
            overlap_tokens=resolved_overlap_tokens,
            document_title=document_title,
        )
    if document_type == DocumentType.ARCHITECTURE:
        return _chunk_structured_sections(
            text,
            max_chars=max_chars,
            document_type=document_type,
            sections=sections,
            target_tokens=resolved_target_tokens,
            overlap_tokens=resolved_overlap_tokens,
            document_title=document_title,
        )
    if document_type == DocumentType.API:
        return _chunk_api(
            text,
            max_chars=max_chars,
            document_type=document_type,
            sections=sections,
            target_tokens=resolved_target_tokens,
            overlap_tokens=resolved_overlap_tokens,
            document_title=document_title,
        )
    if _looks_tabular(text):
        return _chunk_tabular(
            text,
            max_chars=max_chars,
            document_type=document_type,
            target_tokens=resolved_target_tokens,
            overlap_tokens=resolved_overlap_tokens,
            document_title=document_title,
        )
    return _chunk_structured_sections(
        text,
        max_chars=max_chars,
        document_type=document_type,
        sections=sections,
        target_tokens=resolved_target_tokens,
        overlap_tokens=resolved_overlap_tokens,
        document_title=document_title,
    )


def _build_normative_rule(**kwargs: Any) -> NormativeRule:
    from app.db.models.knowledge import NormativeRule

    return NormativeRule(**kwargs)


def extract_normative_rules(
    *, knowledge_version_id, document_id, document_type: DocumentType, text: str
) -> list[NormativeRule]:
    if document_type != DocumentType.NORMATIVE:
        return []
    rules: list[NormativeRule] = []
    rule_counter: defaultdict[str, int] = defaultdict(int)
    candidates = _extract_rule_candidates(text)
    seen_signatures: set[str] = set()
    for candidate in candidates:
        if not any(keyword in candidate.lower() for keyword in RULE_KEYWORDS):
            continue
        signature = _canonical_rule_signature(candidate)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        rule_category = _guess_rule_category(candidate)
        prefix = rule_category.value[:4].upper()
        rule_counter[prefix] += 1
        doc_suffix = str(document_id).replace("-", "")[-6:].upper()
        code = f"{prefix}-{doc_suffix}-{rule_counter[prefix]:03d}"
        rules.append(
            _build_normative_rule(
                knowledge_version_id=knowledge_version_id,
                document_id=document_id,
                rule_code=code,
                rule_name=_derive_title(candidate) or code,
                rule_text=candidate,
                rule_category=rule_category,
                applicability_condition={
                    "negated": _has_negation(candidate),
                    "modal_strength": _modal_strength(candidate),
                    "signature": signature,
                    "confidence": _rule_confidence(candidate),
                },
                severity_default=_guess_rule_severity(candidate),
                status=NormativeRuleStatus.ACTIVE,
            )
        )
    return rules


def detect_rule_conflicts(rules: list[NormativeRule]) -> list[dict[str, str]]:
    by_signature: dict[str, list[NormativeRule]] = defaultdict(list)
    for rule in rules:
        signature = _conflict_signature(rule.rule_text)
        by_signature[signature].append(rule)
    conflicts: list[dict[str, str]] = []
    for signature, items in by_signature.items():
        polarities = {_has_negation(item.rule_text) for item in items}
        if len(items) > 1 and len(polarities) > 1:
            conflicts.append(
                {
                    "rule_signature": signature[:80],
                    "rule_count": str(len(items)),
                    "conflict_type": "polarity_conflict",
                    "rule_codes": ",".join(sorted(item.rule_code for item in items)),
                }
            )
        elif len(items) > 1:
            conflicts.append(
                {
                    "rule_signature": signature[:80],
                    "rule_count": str(len(items)),
                    "conflict_type": "duplicate_rule",
                    "rule_codes": ",".join(sorted(item.rule_code for item in items)),
                }
            )
    return conflicts


def _chunk_normative(
    text: str,
    *,
    max_chars: int,
    sections: list[Any] | None,
    target_tokens: int,
    overlap_tokens: int,
    document_title: str | None,
) -> list[ChunkedText]:
    seeds = _build_section_seeds(text, sections=sections)
    chunks: list[ChunkedText] = []
    chunk_index = 0
    for seed_index, seed in enumerate(seeds, start=1):
        paragraphs = [
            part.strip() for part in re.split(r"\n\s*\n", seed.content) if part.strip()
        ] or ([seed.content.strip()] if seed.content.strip() else [])
        logical_units: list[str] = []
        for paragraph in paragraphs:
            bullet_split = [item.strip() for item in RULE_SPLIT_RE.split(paragraph) if item.strip()]
            if len(bullet_split) > 1:
                logical_units.extend(bullet_split)
            else:
                logical_units.append(paragraph)
        logical_units = [
            unit
            for part in logical_units
            for unit in _split_if_needed(part, max_chars=max_chars, target_tokens=target_tokens)
        ]
        for piece_index, content in enumerate(
            _assemble_token_windows(
                logical_units, target_tokens=target_tokens, overlap_tokens=overlap_tokens
            ),
            start=1,
        ):
            chunk_index += 1
            fragment_type = (
                FragmentType.RULE
                if any(keyword in content.lower() for keyword in RULE_KEYWORDS)
                else FragmentType.REQUIREMENT
            )
            title = seed.heading or _derive_title(content)
            chunks.append(
                ChunkedText(
                    title=title,
                    content=content,
                    source_location=seed.source_location or f"rule:{seed_index}.{piece_index}",
                    fragment_type=fragment_type,
                    metadata=_build_chunk_metadata(
                        document_type=DocumentType.NORMATIVE,
                        fragment_type=fragment_type,
                        title=title,
                        source_location=seed.source_location or f"rule:{seed_index}.{piece_index}",
                        section_path=[seed.heading or f"rule_{seed_index}"],
                        content=content,
                        extra={
                            **seed.metadata,
                            "chunk_index": chunk_index,
                            "document_title": document_title,
                            "chunk_token_count": estimate_token_count(content),
                        },
                    ),
                )
            )
    return chunks


def _chunk_structured_sections(
    text: str,
    *,
    max_chars: int,
    document_type: DocumentType,
    sections: list[Any] | None,
    target_tokens: int,
    overlap_tokens: int,
    document_title: str | None,
) -> list[ChunkedText]:
    seeds = _build_section_seeds(text, sections=sections)
    chunks: list[ChunkedText] = []
    chunk_index = 0
    for seed_index, seed in enumerate(seeds, start=1):
        logical_units = _logical_units_from_seed(
            seed, document_type=document_type, max_chars=max_chars, target_tokens=target_tokens
        )
        for piece_index, content in enumerate(
            _assemble_token_windows(
                logical_units, target_tokens=target_tokens, overlap_tokens=overlap_tokens
            ),
            start=1,
        ):
            chunk_index += 1
            title = seed.heading or _derive_title(content)
            if seed.heading and not content.startswith(seed.heading):
                content_with_heading = f"{seed.heading}\n{content}".strip()
            else:
                content_with_heading = content
            fragment_type = _guess_fragment_type(f"{title or ''}\n{content_with_heading}")
            chunks.append(
                ChunkedText(
                    title=title,
                    content=content_with_heading,
                    source_location=seed.source_location or f"section:{seed_index}.{piece_index}",
                    fragment_type=fragment_type,
                    metadata=_build_chunk_metadata(
                        document_type=document_type,
                        fragment_type=fragment_type,
                        title=title,
                        source_location=seed.source_location
                        or f"section:{seed_index}.{piece_index}",
                        section_path=[seed.heading or f"section_{seed_index}"],
                        content=content_with_heading,
                        extra={
                            **seed.metadata,
                            "chunk_index": chunk_index,
                            "document_title": document_title,
                            "chunk_token_count": estimate_token_count(content_with_heading),
                        },
                    ),
                )
            )
    return chunks


def _chunk_api(
    text: str,
    *,
    max_chars: int,
    document_type: DocumentType,
    sections: list[Any] | None,
    target_tokens: int,
    overlap_tokens: int,
    document_title: str | None,
) -> list[ChunkedText]:
    seeds = _build_section_seeds(text, sections=sections)
    chunks: list[ChunkedText] = []
    chunk_index = 0
    for seed_index, seed in enumerate(seeds, start=1):
        segments = [
            segment.strip() for segment in API_SPLIT_RE.split(seed.content) if segment.strip()
        ] or [seed.content]
        logical_units = [
            unit
            for segment in segments
            for unit in _split_if_needed(segment, max_chars=max_chars, target_tokens=target_tokens)
        ]
        for piece_index, content in enumerate(
            _assemble_token_windows(
                logical_units, target_tokens=target_tokens, overlap_tokens=overlap_tokens
            ),
            start=1,
        ):
            chunk_index += 1
            first_line = content.splitlines()[0][:120] if content.splitlines() else None
            title = seed.heading or first_line or _derive_title(content)
            method = first_line.split(maxsplit=1)[0].upper() if first_line else None
            if (
                title
                and not content.startswith(title)
                and method
                and method in {"GET", "POST", "PUT", "PATCH", "DELETE"}
            ):
                content_with_heading = f"{title}\n{content}".strip()
            else:
                content_with_heading = content
            chunks.append(
                ChunkedText(
                    title=title,
                    content=content_with_heading,
                    source_location=seed.source_location or f"endpoint:{seed_index}.{piece_index}",
                    fragment_type=FragmentType.API,
                    metadata=_build_chunk_metadata(
                        document_type=document_type,
                        fragment_type=FragmentType.API,
                        title=title,
                        source_location=seed.source_location
                        or f"endpoint:{seed_index}.{piece_index}",
                        section_path=[title or f"endpoint_{seed_index}"],
                        content=content_with_heading,
                        extra={
                            **seed.metadata,
                            "http_method": method,
                            "chunk_index": chunk_index,
                            "document_title": document_title,
                            "chunk_token_count": estimate_token_count(content_with_heading),
                        },
                    ),
                )
            )
    return chunks


def _chunk_tabular(
    text: str,
    *,
    max_chars: int,
    document_type: DocumentType,
    target_tokens: int,
    overlap_tokens: int,
    document_title: str | None,
) -> list[ChunkedText]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    groups: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        is_table_line = bool(TABLE_LINE_RE.search(line)) or " | " in line
        if is_table_line:
            current.append(line)
            continue
        if current:
            groups.append(current)
            current = []
        groups.append([line])
    if current:
        groups.append(current)
    chunks: list[ChunkedText] = []
    chunk_index = 0
    for index, group in enumerate(groups, start=1):
        text_block = "\n".join(group)
        windows = _assemble_token_windows(
            _split_if_needed(text_block, max_chars=max_chars, target_tokens=target_tokens),
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
        )
        for piece_index, content in enumerate(windows, start=1):
            chunk_index += 1
            title = _derive_title(group[0])
            chunks.append(
                ChunkedText(
                    title=title,
                    content=content,
                    source_location=f"table:{index}.{piece_index}",
                    fragment_type=FragmentType.OTHER,
                    metadata=_build_chunk_metadata(
                        document_type=document_type,
                        fragment_type=FragmentType.OTHER,
                        title=title,
                        source_location=f"table:{index}.{piece_index}",
                        section_path=[f"table_{index}"],
                        content=content,
                        extra={
                            "table_like": True,
                            "chunk_index": chunk_index,
                            "document_title": document_title,
                            "chunk_token_count": estimate_token_count(content),
                        },
                    ),
                )
            )
    return chunks


def _build_section_seeds(text: str, *, sections: list[Any] | None) -> list[_SectionSeed]:
    if sections:
        seeds: list[_SectionSeed] = []
        for row in sections:
            content = str(getattr(row, "content", "") or "").strip()
            heading = getattr(row, "heading", None)
            if not content:
                continue
            seeds.append(
                _SectionSeed(
                    heading=str(heading).strip() if heading else None,
                    content=content,
                    source_location=getattr(row, "source_location", None),
                    metadata=dict(getattr(row, "metadata", None) or {}),
                )
            )
        if seeds:
            return seeds
    sections_from_text = _split_by_headings(text)
    if sections_from_text:
        return [
            _SectionSeed(
                heading=heading,
                content=body or heading or "",
                source_location=f"section:{index}",
                metadata={},
            )
            for index, (heading, body) in enumerate(sections_from_text, start=1)
        ]
    fallback = text.strip()
    return (
        [_SectionSeed(heading=None, content=fallback, source_location="chunk:1", metadata={})]
        if fallback
        else []
    )


def _logical_units_from_seed(
    seed: _SectionSeed, *, document_type: DocumentType, max_chars: int, target_tokens: int
) -> list[str]:
    content = seed.content.strip()
    if not content:
        return []
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    if not paragraphs:
        paragraphs = [content]
    if document_type == DocumentType.API:
        raw_units = [
            segment.strip() for segment in API_SPLIT_RE.split(content) if segment.strip()
        ] or paragraphs
    elif any(TABLE_LINE_RE.search(line) or " | " in line for line in content.splitlines()):
        raw_units = paragraphs
    else:
        raw_units = paragraphs
    return [
        unit
        for raw in raw_units
        for unit in _split_if_needed(raw, max_chars=max_chars, target_tokens=target_tokens)
    ]


def _split_by_headings(text: str) -> list[tuple[str | None, str]]:
    headings = list(HEADING_RE.finditer(text))
    if not headings:
        return []
    sections: list[tuple[str | None, str]] = []
    preamble = text[: headings[0].start()].strip()
    if preamble:
        sections.append((None, preamble))
    for index, match in enumerate(headings):
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        sections.append((match.group(0).strip(), text[start:end].strip()))
    return sections


def _split_if_needed(text: str, *, max_chars: int, target_tokens: int) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars and estimate_token_count(cleaned) <= target_tokens:
        return [cleaned]
    parts: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[\.!?])\s+", cleaned):
        sentence = sentence.strip()
        if not sentence:
            continue
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) <= max_chars and estimate_token_count(candidate) <= target_tokens:
            current = candidate
            continue
        if current:
            parts.append(current)
        if estimate_token_count(sentence) <= target_tokens and len(sentence) <= max_chars:
            current = sentence
            continue
        sentence_words = sentence.split()
        window: list[str] = []
        for word in sentence_words:
            candidate_window = " ".join([*window, word]).strip()
            if (
                candidate_window
                and len(candidate_window) <= max_chars
                and estimate_token_count(candidate_window) <= target_tokens
            ):
                window.append(word)
                continue
            if window:
                parts.append(" ".join(window).strip())
            window = [word]
        current = " ".join(window).strip()
    if current:
        parts.append(current)
    return parts or [cleaned[:max_chars]]


def _assemble_token_windows(
    units: list[str], *, target_tokens: int, overlap_tokens: int
) -> list[str]:
    normalized_units = [unit.strip() for unit in units if unit and unit.strip()]
    if not normalized_units:
        return []
    windows: list[str] = []
    index = 0
    while index < len(normalized_units):
        current_units: list[str] = []
        token_total = 0
        end_index = index
        while end_index < len(normalized_units):
            candidate = normalized_units[end_index]
            candidate_tokens = estimate_token_count(candidate)
            if current_units and token_total + candidate_tokens > target_tokens:
                break
            current_units.append(candidate)
            token_total += candidate_tokens
            end_index += 1
            if token_total >= target_tokens:
                break
        if not current_units:
            current_units = [normalized_units[index]]
            end_index = index + 1
        window_text = "\n\n".join(current_units).strip()
        if window_text:
            windows.append(window_text)
        if end_index >= len(normalized_units):
            break
        if overlap_tokens <= 0:
            index = end_index
            continue
        overlap_count = 0
        rewind_index = end_index - 1
        while rewind_index >= index:
            overlap_count += estimate_token_count(normalized_units[rewind_index])
            if overlap_count >= overlap_tokens:
                break
            rewind_index -= 1
        index = max(rewind_index, index + 1)
    deduplicated: list[str] = []
    for item in windows:
        if not deduplicated or deduplicated[-1] != item:
            deduplicated.append(item)
    return deduplicated


def _derive_title(text: str) -> str | None:
    compact = " ".join(text.split())
    if not compact:
        return None
    return compact[:120]


def _guess_fragment_type(text: str) -> FragmentType:
    lowered = text.lower()
    if any(token in lowered for token in {"api", "endpoint", "openapi", "swagger"}):
        return FragmentType.API
    if any(token in lowered for token in {"integration", "message broker", "event", "queue"}):
        return FragmentType.INTEGRATION
    if any(token in lowered for token in {"component", "service", "module", "backend", "frontend"}):
        return FragmentType.COMPONENT
    if any(token in lowered for token in RULE_KEYWORDS):
        return FragmentType.RULE
    if any(token in lowered for token in {"requirement", "constraint", "должен", "обязан", "must"}):
        return FragmentType.REQUIREMENT
    if any(token in lowered for token in {"term", "definition", "glossary"}):
        return FragmentType.GLOSSARY
    return FragmentType.OTHER


def _guess_rule_category(text: str) -> RuleCategory:
    lowered = text.lower()
    if any(token in lowered for token in {"api", "endpoint", "openapi", "swagger"}):
        return RuleCategory.API
    if any(token in lowered for token in {"integration", "queue", "event", "message"}):
        return RuleCategory.INTEGRATION
    if any(token in lowered for token in {"component", "module", "service"}):
        return RuleCategory.COMPONENT
    if any(
        token in lowered for token in {"technology", "postgres", "docker", "kubernetes", "python"}
    ):
        return RuleCategory.TECHNOLOGY
    if any(token in lowered for token in {"notation", "diagram", "archimate", "uml"}):
        return RuleCategory.NOTATION
    if any(token in lowered for token in {"governance", "approval", "operator", "audit"}):
        return RuleCategory.GOVERNANCE
    return RuleCategory.ARCHITECTURE


def _looks_tabular(text: str) -> bool:
    table_lines = sum(
        1 for line in text.splitlines() if TABLE_LINE_RE.search(line) or " | " in line
    )
    return table_lines >= 2


def _conflict_signature(text: str) -> str:
    canonical = _canonical_rule_signature(text)
    canonical = re.sub(r"\b(?:not|не|more|than|one|single|multiple|many|only)\b", " ", canonical)
    canonical = canonical.replace(" must ", " ").replace(" shall ", " ").replace(" should ", " ")
    canonical = (
        canonical.replace(" должен ", " ").replace(" обязан ", " ").replace(" необходимо ", " ")
    )
    return re.sub(r"\s+", " ", canonical).strip()


def _extract_rule_candidates(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    candidates: list[str] = []
    for paragraph in paragraphs:
        bullet_split = [item.strip() for item in RULE_SPLIT_RE.split(paragraph) if item.strip()]
        if len(bullet_split) > 1:
            candidates.extend(bullet_split)
        else:
            candidates.append(paragraph)
    return candidates


def _canonical_rule_signature(text: str) -> str:
    normalized = NON_WORD_RE.sub(" ", text.lower())
    normalized = re.sub(
        r"\b(?:must|shall|should|required|обязан|должен|необходимо|обязательно)\b", " ", normalized
    )
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _has_negation(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in NEGATION_KEYWORDS)


def _guess_rule_severity(text: str) -> Severity:
    lowered = text.lower()
    if "must not" in lowered or "shall not" in lowered or "запрещено" in lowered:
        return Severity.CRITICAL
    if "must" in lowered or "shall" in lowered or "должен" in lowered or "обязан" in lowered:
        return Severity.MAJOR
    if "should" in lowered or "рекомендуется" in lowered:
        return Severity.MINOR
    return Severity.INFO


def _modal_strength(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ("must", "shall", "обязан", "должен")):
        return "strong"
    if any(token in lowered for token in ("should", "рекомендуется")):
        return "advisory"
    return "neutral"


def _rule_confidence(text: str) -> float:
    confidence = 0.6
    if _derive_title(text):
        confidence += 0.1
    if _has_negation(text):
        confidence += 0.05
    if len(text.split()) > 8:
        confidence += 0.15
    if any(keyword in text.lower() for keyword in RULE_KEYWORDS):
        confidence += 0.1
    return min(confidence, 0.99)


def _build_chunk_metadata(
    *,
    document_type: DocumentType,
    fragment_type: FragmentType,
    title: str | None,
    source_location: str | None,
    section_path: list[str] | None,
    content: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    lowered = content.lower()
    metadata: dict[str, object] = {
        "document_type": document_type.value,
        "fragment_type": fragment_type.value,
        "section_path": section_path or [],
        "source_weight": DOCUMENT_BASE_WEIGHTS.get(document_type, 1.0),
        "normative_flag": document_type == DocumentType.NORMATIVE
        or fragment_type == FragmentType.RULE,
        "api_flag": document_type == DocumentType.API or fragment_type == FragmentType.API,
        "technology_flag": any(
            token in lowered
            for token in {"postgres", "docker", "kubernetes", "python", "redis", "pgvector"}
        ),
        "content_hash": sha1(content.encode("utf-8")).hexdigest(),
        "chunking_policy_version": CHUNKING_POLICY_VERSION,
    }
    if title:
        metadata["title"] = title
    if source_location:
        metadata["source_location"] = source_location
    if fragment_type == FragmentType.RULE:
        metadata["rule_category"] = _guess_rule_category(content).value
    if extra:
        metadata.update(extra)
    return metadata
