"""Provider compatibility matrix for OSS and frontier model quirks."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderCompat:
    """Per-provider behavioural flags passed to the request builder."""

    tool_choice: str | None = "auto"
    parallel_tool_calls: bool = True
    strict_tool_schema: bool = False


OPENROUTER_COMPAT = ProviderCompat(tool_choice="auto", parallel_tool_calls=True)
SGLANG_COMPAT = ProviderCompat(tool_choice="auto", parallel_tool_calls=False)
