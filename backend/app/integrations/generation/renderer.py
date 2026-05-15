from __future__ import annotations

from html import escape

from app.domain.architecture import get_section_definition, render_togaf_heading
from app.integrations.generation.contracts import GenerationSolutionPayload


class SolutionRenderer:
    def render_markdown(self, payload: GenerationSolutionPayload) -> str:
        lines: list[str] = [f"# {payload.solution_title}", "", payload.executive_summary, ""]
        for section in payload.sections:
            section_definition = get_section_definition(section.section_code)
            heading_prefix = (
                "###" if section_definition is not None and section_definition.level > 1 else "##"
            )
            lines.extend(
                [
                    f"{heading_prefix} {render_togaf_heading(section.section_code)}",
                    section.body_markdown,
                    "",
                ]
            )
        if payload.assumptions:
            lines.append("## Assumptions")
            lines.extend([f"- {item}" for item in payload.assumptions])
            lines.append("")
        if payload.next_steps:
            lines.append("## Next steps")
            lines.extend([f"- {item}" for item in payload.next_steps])
            lines.append("")
        if payload.risks:
            lines.append("## Risks")
            for risk in payload.risks:
                lines.append(f"- **{risk.title}** ({risk.severity.value}): {risk.description}")
            lines.append("")
        return "\n".join(lines).strip()

    def render_html(self, payload: GenerationSolutionPayload) -> str:
        sections_html = "".join(
            (
                f'<section id="{escape(section.section_code)}">'
                f"<h2>{escape(section.title)}</h2>"
                f"<p>{escape(section.body_markdown).replace(chr(10), '<br/>')}</p>"
                f"</section>"
            )
            for section in payload.sections
        )
        assumptions_html = "".join(f"<li>{escape(item)}</li>" for item in payload.assumptions)
        next_steps_html = "".join(f"<li>{escape(item)}</li>" for item in payload.next_steps)
        risks_html = "".join(
            (
                f"<li><strong>{escape(risk.title)}</strong> "
                f"({escape(risk.severity.value)}): {escape(risk.description)}</li>"
            )
            for risk in payload.risks
        )
        return (
            '<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8"/>'
            f"<title>{escape(payload.solution_title)}</title>"
            "</head><body>"
            f"<h1>{escape(payload.solution_title)}</h1>"
            f"<p>{escape(payload.executive_summary)}</p>"
            f"{sections_html}"
            f"<section><h2>Assumptions</h2><ul>{assumptions_html}</ul></section>"
            f"<section><h2>Next steps</h2><ul>{next_steps_html}</ul></section>"
            f"<section><h2>Risks</h2><ul>{risks_html}</ul></section>"
            "</body></html>"
        )
