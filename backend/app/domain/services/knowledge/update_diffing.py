from __future__ import annotations

import re
from typing import Any


def build_version_document_signature(
    version: Any | None,
) -> set[tuple[str, str | None, str | None, bool]]:
    if version is None:
        return set()
    signature: set[tuple[str, str | None, str | None, bool]] = set()
    for item in version.version_documents or []:
        document = item.document
        signature.add(
            (
                str(getattr(document, "document_id", None) or ""),
                getattr(document, "checksum", None),
                getattr(item, "role_code", None),
                bool(getattr(item, "required_flag", False)),
            )
        )
    return signature


def build_version_diff_summary(candidate: Any, active: Any | None) -> dict[str, Any] | None:
    if active is None or str(active.knowledge_version_id) == str(candidate.knowledge_version_id):
        return None
    active_docs = {item[0]: item[1:] for item in build_version_document_signature(active)}
    candidate_docs = {item[0]: item[1:] for item in build_version_document_signature(candidate)}
    added = set(candidate_docs) - set(active_docs)
    removed = set(active_docs) - set(candidate_docs)
    changed = {
        doc_id
        for doc_id in set(candidate_docs) & set(active_docs)
        if candidate_docs.get(doc_id) != active_docs.get(doc_id)
    }
    active_summary = dict((active.summary or {}) if active is not None else {})
    candidate_summary = dict(candidate.summary or {})
    return {
        "active_knowledge_version_id": str(active.knowledge_version_id),
        "candidate_knowledge_version_id": str(candidate.knowledge_version_id),
        "active_version_no": active.version_no,
        "candidate_version_no": candidate.version_no,
        "added_document_count": len(added),
        "removed_document_count": len(removed),
        "changed_document_count": len(changed),
        "added_document_ids": sorted(added),
        "removed_document_ids": sorted(removed),
        "changed_document_ids": sorted(changed),
        "validation_delta": {
            "active": active_summary.get("validation"),
            "candidate": candidate_summary.get("validation"),
        },
        "required_package_health_delta": {
            "active_missing_required_packages": list(
                active_summary.get("missing_required_packages") or []
            ),
            "candidate_missing_required_packages": list(
                candidate_summary.get("missing_required_packages") or []
            ),
            "active_required_source_failures": list(
                active_summary.get("required_source_failures") or []
            ),
            "candidate_required_source_failures": list(
                candidate_summary.get("required_source_failures") or []
            ),
        },
    }


def classify_document_error_code(message: str, *, default: str) -> str:
    lowered = (message or "").lower()
    if "exceeds allowed limit" in lowered or ("size" in lowered and "limit" in lowered):
        return "DOCUMENT_SIZE_LIMIT_EXCEEDED"
    if "unsupported" in lowered and (
        "document" in lowered or "format" in lowered or "type" in lowered
    ):
        return "UNSUPPORTED_DOCUMENT_TYPE"
    if "forbidden" in lowered and "host" in lowered:
        return "SOURCE_URL_FORBIDDEN_HOST"
    if "forbidden" in lowered and "network" in lowered:
        return "SOURCE_URL_FORBIDDEN_NETWORK"
    if any(
        marker in lowered
        for marker in (
            "timed out",
            "timeout",
            "connection refused",
            "connection reset",
            "network is unreachable",
            "temporary failure",
            "name resolution",
            "could not resolve",
            "connection aborted",
            "connection error",
            "remote disconnected",
            "server disconnected",
            "read error",
        )
    ):
        return "SOURCE_CONNECTION_INTERRUPTED"
    if (
        "httpstatuserror" in lowered
        or "client error" in lowered
        or "server error" in lowered
        or re.search(r"\b(?:4\d\d|5\d\d)\b", lowered)
    ):
        return "SOURCE_UNAVAILABLE"
    if any(
        marker in lowered
        for marker in (
            "failed to parse",
            "failed to read",
            "fallback",
            "unreadable",
            "damaged",
            "corrupt",
            "invalid document",
            "no extractable text",
            "empty document",
            "bad zip file",
            "not a zip file",
            "malformed",
        )
    ):
        return "DOCUMENT_PARSE_FAILED"
    return default


def _message_has_cyrillic(message: str) -> bool:
    return any("а" <= char.lower() <= "я" or char.lower() == "ё" for char in message)


def user_friendly_knowledge_error_message(
    error_code: str | None,
    message: str | None = None,
    *,
    stage: str | None = None,
) -> str:
    code = str(error_code or "").strip().upper()
    raw_message = str(message or "").strip()
    normalized = raw_message.lower()
    if code == "CANCELED_BY_USER":
        return "Обновление базы знаний остановлено пользователем."
    if code in {"DOCUMENT_SIZE_LIMIT_EXCEEDED", "SOURCE_DOCUMENT_SIZE_LIMIT_EXCEEDED"}:
        return "Файл слишком большой для загрузки в базу знаний."
    if code in {"SOURCE_URL_FORBIDDEN_HOST", "SOURCE_URL_FORBIDDEN_NETWORK"}:
        return "Ссылка не загружена: адрес запрещён политикой безопасности базы знаний."
    if code == "KNOWLEDGE_UPDATE_QUEUE_DISPATCH_ERROR":
        return (
            "Не удалось запустить обновление базы знаний: worker/Celery или очередь задач "
            "недоступны. Восстановите worker и повторите запуск."
        )
    if code == "KNOWLEDGE_UPDATE_WORKER_INTERRUPTED":
        return (
            "Обновление базы знаний прервано: worker/Celery недоступен или соединение с "
            "очередью потеряно. Восстановите worker и запустите обновление повторно."
        )
    if code in {
        "SOURCE_CONNECTION_INTERRUPTED",
        "SOURCE_UNAVAILABLE",
        "SOURCE_READER_ERROR",
        "FETCH_FAILED",
        "KNOWLEDGE_SOURCE_UNAVAILABLE",
    }:
        return (
            "Не удалось загрузить ссылку: источник недоступен или соединение было прервано. "
            "Проверьте интернет, URL и права доступа, затем повторите обновление."
        )
    if code in {
        "UNSUPPORTED_DOCUMENT_TYPE",
        "DOCUMENT_PARSE_FAILED",
        "PARSE_FAILED",
        "KNOWLEDGE_UPLOAD_FILE_INVALID",
    }:
        if code == "UNSUPPORTED_DOCUMENT_TYPE" or "unsupported" in normalized:
            return (
                "Файл не загружен: формат не поддерживается. Поддерживаются PDF, DOCX, "
                "ODT, XLSX, ArchiMate, HTML, Markdown, TXT и JSON."
            )
        return (
            "Файл не удалось разобрать: он повреждён, пустой или имеет неподдерживаемое "
            "содержимое. Загрузите корректный файл в поддерживаемом формате."
        )
    if code == "KNOWLEDGE_UPLOAD_FILE_EMPTY":
        return "Файл пустой или не читается."
    if code == "UPLOAD_FILES_REQUIRED":
        return "Выберите хотя бы один файл для загрузки."
    if raw_message and _message_has_cyrillic(raw_message):
        return raw_message
    if stage == "fetching":
        return (
            "Не удалось загрузить источник базы знаний. Проверьте доступность ссылки или "
            "файла и повторите обновление."
        )
    if stage == "parsing":
        return (
            "Не удалось разобрать документ базы знаний. Проверьте формат и целостность "
            "файла, затем повторите загрузку."
        )
    return "Не удалось обработать материал базы знаний. Проверьте источник и повторите операцию."
