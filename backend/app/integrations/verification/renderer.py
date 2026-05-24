from __future__ import annotations

from collections import defaultdict
from html import escape
import re
from typing import Any

from pydantic import BaseModel

from app.integrations.verification.contracts import VerificationProtocolPayload


def _compact_evidence_label(value: str | None) -> str:
    if not value:
        return ""
    source_match = re.search(
        r"([A-Za-z0-9А-Яа-яЁё_. -]+\.(?:pdf|docx?|xlsx?|md|txt|csv))",
        value,
        flags=re.IGNORECASE,
    )
    location_match = re.search(
        r"(?:fragment|chunk|compact|section|раздел|фрагмент)\s*[:#]?\s*([A-Za-zА-Яа-яЁё0-9_.-]+)",
        value,
        flags=re.IGNORECASE,
    )
    if source_match:
        source = source_match.group(1).split("/")[-1].split("\\")[-1]
        source = re.sub(r"^[a-f0-9]{32}_", "", source, flags=re.IGNORECASE)
        source = re.sub(
            r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}[_-]",
            "",
            source,
            flags=re.IGNORECASE,
        )
        if location_match:
            return f"{source} · фрагмент {location_match.group(1)}"
        return source
    cleaned = re.sub(
        r"[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
        "",
        value,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\b[a-f0-9]{24,}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" |:;,-")
    return cleaned[:160] or "Документ-основание"


class VerificationProtocolRenderer:
    def render_html(
        self,
        *,
        protocol_no: str | None,
        payload: VerificationProtocolPayload,
        basis_documents: list[dict[str, Any]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        basis_documents = basis_documents or []
        metadata = metadata or {}
        grouped_results: dict[str, list[Any]] = defaultdict(list)
        for item in payload.check_results:
            grouped_results[item.rule_group or "other"].append(item)

        group_labels = {
            "technical": "Техническая готовность",
            "structure": "Структура TOGAF",
            "normative": "Соответствие ArchiMate / нормативам",
            "consistency": "Семантическая согласованность",
            "other": "Прочие проверки",
        }
        status_counters = {"failed": 0, "warning": 0, "not_determined": 0, "passed": 0}
        for item in payload.check_results:
            status_counters[item.status.value] = status_counters.get(item.status.value, 0) + 1

        group_sections: list[str] = []
        preferred_group_order = ["technical", "structure", "normative", "consistency", "other"]
        ordered_group_codes = [group for group in preferred_group_order if group in grouped_results]
        ordered_group_codes.extend(
            sorted(group for group in grouped_results if group not in preferred_group_order)
        )
        for group_code in ordered_group_codes:
            items = grouped_results.get(group_code)
            if not items:
                continue
            rows = []
            for item in items:
                rows.append(
                    "<tr>"
                    f"<td>{escape(item.rule_code or '')}</td>"
                    f"<td>{escape(item.check_name)}</td>"
                    f"<td>{escape(item.status.value)}</td>"
                    f"<td>{escape(item.severity.value)}</td>"
                    f"<td>{escape(item.finding_text or '')}</td>"
                    f"<td>{escape(_compact_evidence_label(item.evidence_ref))}</td>"
                    f"<td>{escape(item.related_section_ref or '')}</td>"
                    "</tr>"
                )
            group_sections.append(
                f"<h2>{escape(group_labels.get(group_code, group_code.title()))}</h2>"
                "<table border='1' cellpadding='6' cellspacing='0'>"
                "<thead><tr><th>Rule</th><th>Check</th><th>Status</th><th>Severity</th><th>Finding</th><th>Evidence</th><th>Section</th></tr></thead>"
                f"<tbody>{''.join(rows)}</tbody></table>"
            )

        basis_rows = []
        for basis_item in basis_documents:
            basis_document = (
                basis_item.model_dump() if isinstance(basis_item, BaseModel) else dict(basis_item)
            )
            basis_rows.append(
                "<tr>"
                f"<td>{escape(str(basis_document.get('title') or ''))}</td>"
                f"<td>{escape(str(basis_document.get('role_code') or ''))}</td>"
                f"<td>{escape(str(basis_document.get('version_ref') or ''))}</td>"
                f"<td>{'yes' if basis_document.get('required_flag') else 'no'}</td>"
                "</tr>"
            )
        protocol_label = escape(protocol_no or "Draft protocol")
        metadata_rows = []
        for key, value in metadata.items():
            if value in (None, "", [], {}):
                continue
            metadata_rows.append(
                f"<li><strong>{escape(str(key))}:</strong> {escape(str(value))}</li>"
            )
        executive_summary = (
            "<ul>"
            f"<li><strong>Failed:</strong> {status_counters.get('failed', 0)}</li>"
            f"<li><strong>Warnings:</strong> {status_counters.get('warning', 0)}</li>"
            f"<li><strong>Incomplete:</strong> {status_counters.get('not_determined', 0)}</li>"
            f"<li><strong>Passed:</strong> {status_counters.get('passed', 0)}</li>"
            "</ul>"
        )
        return (
            "<html><head><style>"
            "body{font-family:Arial,sans-serif;color:#111827;}"
            "table{width:100%;border-collapse:collapse;margin:12px 0;}"
            "th,td{border:1px solid #d1d5db;padding:8px;text-align:left;vertical-align:top;}"
            "th{background:#f3f4f6;font-weight:700;}"
            "</style></head><body>"
            f"<h1>Verification protocol {protocol_label}</h1>"
            f"<p><strong>Final status:</strong> {escape(payload.final_status.value)}</p>"
            f"<p>{escape(payload.summary)}</p>"
            f"<h2>Executive summary</h2>{executive_summary}"
            + (
                f"<h2>Protocol passport</h2><ul>{''.join(metadata_rows)}</ul>"
                if metadata_rows
                else ""
            )
            + (
                "<h2>Basis documents</h2>"
                "<table border='1' cellpadding='6' cellspacing='0'>"
                "<thead><tr><th>Title</th><th>Role</th><th>Version</th><th>Required</th></tr></thead>"
                f"<tbody>{''.join(basis_rows)}</tbody></table>"
                if basis_rows
                else ""
            )
            + "".join(group_sections)
            + "</body></html>"
        )
