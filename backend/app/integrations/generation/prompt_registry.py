from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    version_id: str
    template_name: str
    system_prompt: str
    user_prompt_template: str
    output_contract_name: str


class PromptRegistry:
    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = base_dir or Path(__file__).resolve().parents[2] / "templates" / "prompts"
        self._cache: dict[str, PromptTemplate] = {}

    def get_generation_template(self) -> PromptTemplate:
        return self.get_template("generation.v3")

    def get_verification_template(self) -> PromptTemplate:
        return self.get_template("verification.v1")

    def get_template(self, version_id: str) -> PromptTemplate:
        cached = self._cache.get(version_id)
        if cached is not None:
            return cached
        path = self.base_dir / f"{version_id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        template = PromptTemplate(**payload)
        self._cache[version_id] = template
        return template
