from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.integrations.generation.contracts import (
    REQUIRED_SECTION_CODES,
    GenerationSolutionPayload,
)

from .payload_normalization_common import (
    MULTI_VALUE_SPLIT_RE,
    _build_quote_excerpt,
    _clean_text_value,
    _extract_first_text,
    _extract_list_payload,
    _normalize_text_for_evidence_match,
    _tokenize_for_match,
    re,
)

if TYPE_CHECKING:
    from app.integrations.generation.llm_gateway import RetrievedFragment

SOURCE_REF_TYPED_VALUE_RE = re.compile(
    (
        r"^(?:(?P<section>[a-z][a-z0-9_ -]*):)?"
        r"(?P<kind>fragment|document)(?:_id)?\s*[:=#/]\s*"
        r"(?P<identifier>.+)$"
    ),
    re.IGNORECASE,
)


def _looks_like_placeholder_source_ref_id(value: Any) -> bool:
    cleaned = _clean_text_value(value)
    if not cleaned:
        return True
    normalized = re.sub(r"[\s<>{}\[\]()\"'`]+", "", cleaned).casefold()
    normalized = normalized.replace("-", "").replace("_", "")
    return normalized in {
        "uuid",
        "fragmentuuid",
        "documentuuid",
        "fragmentid",
        "documentid",
        "sourceid",
        "sourceref",
        "refid",
        "id",
        "placeholder",
        "example",
        "sample",
        "todo",
        "tbd",
        "unknown",
        "none",
        "null",
        "na",
        "n/a",
    }


def _parse_source_ref_value(
    value: Any, *, preferred_target: str | None = None
) -> dict[str, str] | None:
    cleaned = _clean_text_value(value)
    if not cleaned:
        return None
    cleaned = cleaned.strip("[]{}()<>\"'`")
    if _looks_like_placeholder_source_ref_id(cleaned):
        return None

    match = SOURCE_REF_TYPED_VALUE_RE.match(cleaned)
    if match:
        identifier = match.group("identifier").strip("[]{}()<>\"'` ")
        if _looks_like_placeholder_source_ref_id(identifier):
            return None
        target_key = (
            "fragment_id" if match.group("kind").casefold() == "fragment" else "document_id"
        )
        return {target_key: identifier}

    if preferred_target in {"fragment_id", "document_id"}:
        return {preferred_target: cleaned}
    return {"fragment_id": cleaned}


def _deduplicate_source_ref_dicts(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str | None, str | None, str | None]] = set()
    for item in refs:
        key = (
            _clean_text_value(item.get("fragment_id")),
            _clean_text_value(item.get("document_id")),
            _clean_text_value(item.get("quote_text")),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _normalize_source_refs(source_refs: Any) -> list[Any]:
    if source_refs is None:
        return []
    if isinstance(source_refs, str):
        source_refs = [
            part
            for part in (
                _clean_text_value(part) for part in MULTI_VALUE_SPLIT_RE.split(source_refs)
            )
            if part
        ]
    elif isinstance(source_refs, tuple):
        source_refs = list(source_refs)
    elif isinstance(source_refs, dict):
        extracted = _extract_list_payload(
            source_refs,
            wrapper_keys=("items", "entries", "source_refs", "references", "citations", "evidence"),
            allow_mapping_values=True,
        )
        source_refs = extracted if extracted is not None else [source_refs]
    elif not isinstance(source_refs, list):
        return []

    patched_refs: list[dict[str, Any] | Any] = []
    for item in source_refs:
        if isinstance(item, str):
            parsed_ref = _parse_source_ref_value(item)
            if parsed_ref is not None:
                patched_refs.append(parsed_ref)
            continue

        if isinstance(item, dict):
            ref = dict(item)

            parsed_fragment = _parse_source_ref_value(
                ref.get("fragment_id"), preferred_target="fragment_id"
            )
            ref["fragment_id"] = (
                parsed_fragment.get("fragment_id") if parsed_fragment is not None else None
            )
            parsed_document = _parse_source_ref_value(
                ref.get("document_id"), preferred_target="document_id"
            )
            ref["document_id"] = (
                parsed_document.get("document_id") if parsed_document is not None else None
            )

            alias_map = (
                ("fragment_uuid", "fragment_id"),
                ("fragment_ref", "fragment_id"),
                ("fragment", "fragment_id"),
                ("source_ref", "fragment_id"),
                ("source_id", "fragment_id"),
                ("ref", "fragment_id"),
                ("id", "fragment_id"),
                ("evidence_id", "fragment_id"),
                ("document_uuid", "document_id"),
                ("document_ref", "document_id"),
                ("document", "document_id"),
            )
            for alias_key, target_key in alias_map:
                if ref.get(target_key):
                    continue
                parsed_alias = _parse_source_ref_value(
                    ref.get(alias_key), preferred_target=target_key
                )
                if parsed_alias is not None:
                    ref[target_key] = parsed_alias.get(target_key)

            for alias_key, target_key in (
                ("fragment_ids", "fragment_id"),
                ("fragments", "fragment_id"),
                ("document_ids", "document_id"),
                ("documents", "document_id"),
            ):
                if ref.get(target_key):
                    continue
                alias_items = _extract_list_payload(ref.get(alias_key), allow_mapping_values=True)
                if not alias_items:
                    continue
                for alias_item in alias_items:
                    parsed_alias_item = _parse_source_ref_value(
                        alias_item, preferred_target=target_key
                    )
                    if parsed_alias_item is not None:
                        ref[target_key] = parsed_alias_item.get(target_key)
                        break

            quote_text = _extract_first_text(
                ref, ("quote_text", "quote", "excerpt", "snippet", "text")
            )
            ref["quote_text"] = quote_text

            if ref.get("fragment_id") or ref.get("document_id"):
                patched_refs.append(ref)
            continue

        patched_refs.append(item)

    return _deduplicate_source_ref_dicts([item for item in patched_refs if isinstance(item, dict)])


def _match_retrieved_fragment_by_quote(
    quote_text: str, *, retrieved_fragments: list[RetrievedFragment]
) -> RetrievedFragment | None:
    cleaned_quote = _clean_text_value(quote_text)
    if not cleaned_quote or len(cleaned_quote) < 12:
        return None

    normalized_quote = _normalize_text_for_evidence_match(cleaned_quote)
    quote_tokens = _tokenize_for_match(cleaned_quote)
    best_fragment: RetrievedFragment | None = None
    best_score = 0.0

    for fragment in retrieved_fragments:
        fragment_text = " ".join(
            part for part in (fragment.title or "", fragment.content or "") if part
        )
        normalized_fragment = _normalize_text_for_evidence_match(fragment_text)
        score = 0.0
        if normalized_quote and normalized_quote in normalized_fragment:
            score = float(len(normalized_quote))
        elif quote_tokens:
            fragment_tokens = _tokenize_for_match(fragment_text)
            overlap = len(quote_tokens.intersection(fragment_tokens))
            if overlap >= max(3, min(len(quote_tokens), 6) // 2):
                score = float(overlap)
        if score > best_score:
            best_score = score
            best_fragment = fragment

    return best_fragment


def _canonicalize_source_refs_against_retrieved(
    source_refs: list[Any],
    *,
    retrieved_fragments: list[RetrievedFragment],
) -> list[dict[str, Any]]:
    normalized_refs = _normalize_source_refs(source_refs)
    if not normalized_refs:
        return []
    if not retrieved_fragments:
        return []

    fragments_by_id = {item.fragment_id: item for item in retrieved_fragments if item.fragment_id}
    retrieved_document_ids = {item.document_id for item in retrieved_fragments if item.document_id}
    canonical_refs: list[dict[str, Any]] = []

    for item in normalized_refs:
        if not isinstance(item, dict):
            continue
        ref = dict(item)
        fragment_id = _clean_text_value(ref.get("fragment_id"))
        document_id = _clean_text_value(ref.get("document_id"))
        quote_text = _clean_text_value(ref.get("quote_text"))

        matched_fragment: RetrievedFragment | None = None
        if fragment_id and fragment_id in fragments_by_id:
            matched_fragment = fragments_by_id[fragment_id]
        elif quote_text:
            matched_fragment = _match_retrieved_fragment_by_quote(
                quote_text, retrieved_fragments=retrieved_fragments
            )

        if matched_fragment is not None:
            canonical_refs.append(
                {
                    "fragment_id": matched_fragment.fragment_id,
                    "document_id": matched_fragment.document_id,
                    "quote_text": quote_text or _build_quote_excerpt(matched_fragment.content),
                }
            )
            continue

        if document_id and document_id in retrieved_document_ids:
            canonical_refs.append(
                {
                    "document_id": document_id,
                    "quote_text": quote_text,
                }
            )

    return _deduplicate_source_ref_dicts(canonical_refs)


def _enrich_critical_section_source_refs(
    payload: GenerationSolutionPayload,
    *,
    retrieved_fragments: list[RetrievedFragment],
) -> GenerationSolutionPayload:
    patched = payload.model_dump()
    patched_sections: list[dict[str, Any] | Any] = []

    for section in patched.get("sections", []):
        if not isinstance(section, dict):
            patched_sections.append(section)
            continue

        source_refs = _canonicalize_source_refs_against_retrieved(
            section.get("source_refs", []),
            retrieved_fragments=retrieved_fragments,
        )
        section_code = _clean_text_value(section.get("section_code")) or ""

        if not source_refs and section_code in REQUIRED_SECTION_CODES:
            from .payload_normalization_sections import _pick_fragment_for_section

            chosen_fragment = _pick_fragment_for_section(
                section_code=section_code,
                section_title=_clean_text_value(section.get("title")) or section_code.title(),
                body_markdown=_clean_text_value(section.get("body_markdown")) or "",
                retrieved_fragments=retrieved_fragments,
            )
            if chosen_fragment is not None:
                source_refs = [
                    {
                        "fragment_id": chosen_fragment.fragment_id,
                        "document_id": chosen_fragment.document_id,
                        "quote_text": _build_quote_excerpt(chosen_fragment.content),
                    }
                ]

        section["source_refs"] = source_refs
        patched_sections.append(section)

    patched["sections"] = patched_sections
    from .payload_normalization_validation import _coerce_generation_solution_payload

    return _coerce_generation_solution_payload(patched)


__all__ = [name for name in globals() if name != "__builtins__"]
