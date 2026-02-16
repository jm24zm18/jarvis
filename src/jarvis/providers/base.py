"""Provider contracts."""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class ModelResponse:
    text: str
    tool_calls: list[dict[str, Any]]


class ModelProvider(Protocol):
    async def generate(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> ModelResponse: ...

    async def health_check(self) -> bool: ...
