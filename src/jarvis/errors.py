"""Jarvis exception hierarchy.

All Jarvis-specific exceptions inherit from JarvisError,
enabling structured error handling and cleaner catch clauses.
"""


class JarvisError(Exception):
    """Base exception for all Jarvis errors."""

    def __init__(self, message: str = "", *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderError(JarvisError):
    """Error communicating with an LLM provider."""

    def __init__(self, message: str = "", *, retryable: bool = True) -> None:
        super().__init__(message, retryable=retryable)


class ToolError(JarvisError):
    """Error executing a tool."""


class PolicyError(JarvisError):
    """Action denied by policy engine."""


class ChannelError(JarvisError):
    """Error in channel send/receive operations."""

    def __init__(self, message: str = "", *, retryable: bool = True) -> None:
        super().__init__(message, retryable=retryable)


class ConfigError(JarvisError):
    """Invalid or missing configuration."""


class MemoryError(JarvisError):
    """Error in memory/search operations."""
