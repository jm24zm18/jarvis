"""Tests for error hierarchy."""

from jarvis.errors import (
    ChannelError,
    ConfigError,
    JarvisError,
    PolicyError,
    ProviderError,
    ToolError,
)


def test_hierarchy() -> None:
    assert issubclass(ProviderError, JarvisError)
    assert issubclass(ToolError, JarvisError)
    assert issubclass(PolicyError, JarvisError)
    assert issubclass(ChannelError, JarvisError)
    assert issubclass(ConfigError, JarvisError)


def test_retryable_default() -> None:
    assert JarvisError("test").retryable is False
    assert ProviderError("test").retryable is True
    assert ChannelError("test").retryable is True
    assert ToolError("test").retryable is False
    assert PolicyError("test").retryable is False


def test_error_message() -> None:
    err = ProviderError("provider down")
    assert str(err) == "provider down"
    assert err.retryable is True


def test_catch_as_jarvis_error() -> None:
    try:
        raise ProviderError("test")
    except JarvisError as exc:
        assert exc.retryable is True
