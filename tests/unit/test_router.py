import pytest

from jarvis.errors import ProviderError
from jarvis.providers.base import ModelResponse
from jarvis.providers.router import ProviderRouter


class OkProvider:
    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        return ModelResponse(text="ok", tool_calls=[])

    async def health_check(self) -> bool:
        return True


class FailProvider:
    async def generate(self, messages, tools=None, temperature=0.7, max_tokens=4096):
        raise RuntimeError("boom")

    async def health_check(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_primary_success() -> None:
    router = ProviderRouter(OkProvider(), OkProvider())
    response, lane, primary_error = await router.generate([{"role": "user", "content": "x"}])
    assert response.text == "ok"
    assert lane == "primary"
    assert primary_error is None


@pytest.mark.asyncio
async def test_fallback_on_failure() -> None:
    router = ProviderRouter(FailProvider(), OkProvider())
    response, lane, primary_error = await router.generate([{"role": "user", "content": "x"}])
    assert response.text == "ok"
    assert lane == "fallback"
    assert primary_error is not None


@pytest.mark.asyncio
async def test_both_fail_raises() -> None:
    router = ProviderRouter(FailProvider(), FailProvider())
    with pytest.raises(ProviderError):
        await router.generate([{"role": "user", "content": "x"}])


@pytest.mark.asyncio
async def test_low_priority_skips_fallback_when_local_llm_overloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = ProviderRouter(FailProvider(), OkProvider())
    async def _overloaded() -> bool:
        return True

    monkeypatch.setattr(router, "_local_llm_overloaded", _overloaded)
    with pytest.raises(ProviderError):
        await router.generate([{"role": "user", "content": "x"}], priority="low")
