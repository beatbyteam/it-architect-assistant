from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TokenBudgetResult:
    selected_items: list[str]
    dropped_items: list[str]
    consumed_tokens: int
    available_tokens: int
    selected_indexes: list[int]
    dropped_indexes: list[int]


class TokenBudgetManager:
    def __init__(self, *, max_input_tokens: int, reserved_output_tokens: int) -> None:
        self.max_input_tokens = max_input_tokens
        self.reserved_output_tokens = reserved_output_tokens

    @property
    def available_input_tokens(self) -> int:
        if self.max_input_tokens <= 0:
            return 0
        available = self.max_input_tokens - max(0, self.reserved_output_tokens)
        if self.max_input_tokens <= 256:
            return max(0, min(self.max_input_tokens, available))
        return min(self.max_input_tokens, max(256, available))

    def estimate_tokens(self, text: str) -> int:
        # Conservative approximation that behaves predictably in tests and offline mode.
        return max(1, len(text.split()) + (len(text) // 8))

    def trim_items(self, base_text: str, items: list[str]) -> TokenBudgetResult:
        available = self.available_input_tokens
        consumed = self.estimate_tokens(base_text)
        selected: list[str] = []
        dropped: list[str] = []
        selected_indexes: list[int] = []
        dropped_indexes: list[int] = []
        for index, item in enumerate(items):
            item_cost = self.estimate_tokens(item)
            if consumed + item_cost <= available:
                selected.append(item)
                selected_indexes.append(index)
                consumed += item_cost
            else:
                dropped.append(item)
                dropped_indexes.append(index)
        return TokenBudgetResult(
            selected_items=selected,
            dropped_items=dropped,
            consumed_tokens=consumed,
            available_tokens=available,
            selected_indexes=selected_indexes,
            dropped_indexes=dropped_indexes,
        )
