"""Tool registration helpers."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

ToolCallable = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ToolDef:
    name: str
    description: str
    handler: ToolCallable
    parameters: dict[str, object] = field(
        default_factory=lambda: {"type": "object", "properties": {}}
    )


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDef] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: ToolCallable,
        parameters: dict[str, object] | None = None,
    ) -> None:
        self._tools[name] = ToolDef(
            name=name,
            description=description,
            handler=handler,
            parameters=parameters or {"type": "object", "properties": {}},
        )

    def get(self, name: str) -> ToolDef | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, object]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            }
            for tool in self._tools.values()
        ]
