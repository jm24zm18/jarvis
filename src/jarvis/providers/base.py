"""Provider contracts."""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(slots=True)
class ModelResponse:
    text: str
    tool_calls: list[dict[str, Any]]
    reasoning_text: str = ""
    reasoning_parts: list[dict[str, Any]] = field(default_factory=list)


class ModelProvider(Protocol):
    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ModelResponse: ...

    async def health_check(self) -> bool: ...
